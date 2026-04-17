"""Core MCPLogger class — writes JSONL audit logs.

Writes go through an in-process ``asyncio.Queue`` consumed by a single
worker task so call-sites inside async handlers never block on file I/O.
When no event loop is running (tests, CLI scripts), we fall back to a
synchronous write so logs are still captured.
"""
import asyncio
import json
import sys
import threading
import uuid
from typing import Any

from .config import LoggerConfig
from .formatters import to_jsonl, now_utc
from .rotation import LogRotator
from .sanitizer import sanitize
from .metrics import MetricsCollector

# Drop log records rather than blocking a request if the writer is wedged.
# Set high enough that realistic workloads never hit it; rely on the worker
# running at ~disk-write speed.
_QUEUE_MAX = 10_000


class MCPLogger:
    def __init__(
        self,
        service_name: str,
        log_dir: str = "/var/log/mcp",
        max_body_size: int = 51200,
        retention_days: int = 7,
        config: dict | None = None,
    ):
        cfg = LoggerConfig(config)
        self.service_name = service_name
        self.log_dir = cfg.log_dir if config else log_dir
        self.max_body_size = cfg.max_body_size if config else max_body_size
        self.retention_days = cfg.retention_days if config else retention_days
        self.compress_after_days = cfg.compress_after_days
        self.sensitive_fields = cfg.sensitive_fields

        self._rotator = LogRotator(
            log_dir=self.log_dir,
            service_name=service_name,
            retention_days=self.retention_days,
            compress_after_days=self.compress_after_days,
        )
        self._rotator.run_maintenance()

        self.metrics = MetricsCollector(
            service_name=service_name,
            log_dir=self.log_dir,
            dump_interval=cfg.metrics_dump_interval,
        )

        # Async-write plumbing. The queue is lazily bound to whatever event
        # loop we run the worker on — see ``start_writer()``/``stop_writer``.
        self._queue: asyncio.Queue | None = None
        self._writer_task: asyncio.Task | None = None
        self._writer_loop: asyncio.AbstractEventLoop | None = None
        self._dropped: int = 0
        # Serialize the sync-fallback path so two threads don't interleave
        # bytes inside a single JSONL line.
        self._sync_lock = threading.Lock()

    def log_api_request(
        self,
        method: str,
        url: str,
        http_method: str = "POST",
        request_body: Any = None,
        direction: str = "outgoing",
        request_id: str | None = None,
        correlation_id: str | None = None,
        user_id: str | None = None,
        account_id: str | None = None,
        extra: dict | None = None,
    ) -> str:
        rid = request_id or str(uuid.uuid4())
        body, truncated, original_size = self._prepare_body(request_body)
        record = self._base_record(
            event_type="api_request",
            method=method,
            direction=direction,
            url=url,
            http_method=http_method,
            request_body=body,
            body_truncated=truncated,
            request_id=rid,
            correlation_id=correlation_id,
            user_id=user_id,
            account_id=account_id,
        )
        if truncated and original_size:
            record["extra"]["original_request_body_size"] = original_size
        if extra:
            record["extra"].update(extra)
        self._write(record)
        return rid

    def log_api_response(
        self,
        method: str,
        url: str,
        http_method: str = "POST",
        status_code: int | None = None,
        duration_ms: float = 0.0,
        response_body: Any = None,
        direction: str = "outgoing",
        request_id: str | None = None,
        correlation_id: str | None = None,
        user_id: str | None = None,
        account_id: str | None = None,
        rate_limit_remaining: int | None = None,
        rate_limit_reset: str | None = None,
        extra: dict | None = None,
    ) -> None:
        body, truncated, original_size = self._prepare_body(response_body)
        record = self._base_record(
            event_type="api_response",
            method=method,
            direction=direction,
            url=url,
            http_method=http_method,
            status_code=status_code,
            duration_ms=duration_ms,
            response_body=body,
            body_truncated=truncated,
            request_id=request_id,
            correlation_id=correlation_id,
            user_id=user_id,
            account_id=account_id,
            rate_limit_remaining=rate_limit_remaining,
            rate_limit_reset=rate_limit_reset,
        )
        if truncated and original_size:
            record["extra"]["original_response_body_size"] = original_size
        if extra:
            record["extra"].update(extra)
        self._write(record)
        self.metrics.record_request(
            method=method,
            status_code=status_code,
            duration_ms=duration_ms,
            rate_limit_remaining=rate_limit_remaining,
            rate_limit_reset=rate_limit_reset,
        )

    def log_api_error(
        self,
        method: str,
        url: str,
        error: str,
        error_type: str | None = None,
        http_method: str = "POST",
        duration_ms: float = 0.0,
        direction: str = "outgoing",
        request_id: str | None = None,
        correlation_id: str | None = None,
        user_id: str | None = None,
        account_id: str | None = None,
        extra: dict | None = None,
    ) -> None:
        record = self._base_record(
            event_type="api_error",
            method=method,
            direction=direction,
            url=url,
            http_method=http_method,
            duration_ms=duration_ms,
            error=error,
            error_type=error_type,
            request_id=request_id,
            correlation_id=correlation_id,
            user_id=user_id,
            account_id=account_id,
        )
        if extra:
            record["extra"].update(extra)
        self._write(record)
        self.metrics.record_request(
            method=method,
            status_code=error_type or "error",
            duration_ms=duration_ms,
            is_error=True,
            error_type=error_type,
        )

    def log_mcp_request(
        self,
        method: str,
        request_body: Any = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        user_id: str | None = None,
        extra: dict | None = None,
    ) -> str:
        rid = request_id or str(uuid.uuid4())
        body, truncated, original_size = self._prepare_body(request_body)
        record = self._base_record(
            event_type="mcp_request",
            method=method,
            direction="incoming",
            request_body=body,
            body_truncated=truncated,
            request_id=rid,
            correlation_id=correlation_id,
            user_id=user_id,
        )
        if truncated and original_size:
            record["extra"]["original_request_body_size"] = original_size
        if extra:
            record["extra"].update(extra)
        self._write(record)
        return rid

    def log_mcp_response(
        self,
        method: str,
        duration_ms: float = 0.0,
        response_body: Any = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        user_id: str | None = None,
        extra: dict | None = None,
    ) -> None:
        body, truncated, original_size = self._prepare_body(response_body)
        record = self._base_record(
            event_type="mcp_response",
            method=method,
            direction="incoming",
            duration_ms=duration_ms,
            response_body=body,
            body_truncated=truncated,
            request_id=request_id,
            correlation_id=correlation_id,
            user_id=user_id,
        )
        if truncated and original_size:
            record["extra"]["original_response_body_size"] = original_size
        if extra:
            record["extra"].update(extra)
        self._write(record)

    def log_mcp_error(
        self,
        method: str,
        error: str,
        error_type: str | None = None,
        duration_ms: float = 0.0,
        request_id: str | None = None,
        correlation_id: str | None = None,
        user_id: str | None = None,
        extra: dict | None = None,
    ) -> None:
        record = self._base_record(
            event_type="mcp_error",
            method=method,
            direction="incoming",
            duration_ms=duration_ms,
            error=error,
            error_type=error_type,
            request_id=request_id,
            correlation_id=correlation_id,
            user_id=user_id,
        )
        if extra:
            record["extra"].update(extra)
        self._write(record)

    def _prepare_body(self, body: Any) -> tuple:
        if body is None:
            return None, False, None
        sanitized = sanitize(body, self.sensitive_fields)
        try:
            serialized = json.dumps(sanitized, ensure_ascii=False)
        except (TypeError, ValueError):
            serialized = str(sanitized)
            sanitized = serialized
        size = len(serialized.encode("utf-8"))
        if size > self.max_body_size:
            truncated_str = serialized[: self.max_body_size]
            try:
                sanitized = json.loads(truncated_str)
            except json.JSONDecodeError:
                sanitized = truncated_str
            return sanitized, True, size
        return sanitized, False, None

    def _base_record(self, **kwargs) -> dict:
        record: dict[str, Any] = {
            "timestamp": now_utc(),
            "service": self.service_name,
            "event_type": kwargs.get("event_type"),
            "method": kwargs.get("method"),
            "direction": kwargs.get("direction"),
            "url": kwargs.get("url"),
            "http_method": kwargs.get("http_method"),
            "status_code": kwargs.get("status_code"),
            "duration_ms": kwargs.get("duration_ms"),
            "request_body": kwargs.get("request_body"),
            "response_body": kwargs.get("response_body"),
            "body_truncated": kwargs.get("body_truncated", False),
            "error": kwargs.get("error"),
            "error_type": kwargs.get("error_type"),
            "rate_limit_remaining": kwargs.get("rate_limit_remaining"),
            "rate_limit_reset": kwargs.get("rate_limit_reset"),
            "request_id": kwargs.get("request_id"),
            "correlation_id": kwargs.get("correlation_id"),
            "user_id": kwargs.get("user_id"),
            "account_id": kwargs.get("account_id"),
            "extra": {},
        }
        return record

    # ------------------------------------------------------------------
    # Async writer lifecycle
    # ------------------------------------------------------------------

    async def start_writer(self) -> None:
        """Start the background writer task bound to the current loop.

        Safe to call multiple times; a second call is a no-op while a
        writer is already running.
        """
        if self._writer_task is not None and not self._writer_task.done():
            return
        loop = asyncio.get_running_loop()
        self._writer_loop = loop
        self._queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._writer_task = loop.create_task(self._writer_loop_fn())

    async def stop_writer(self) -> None:
        """Flush queued records and stop the writer task."""
        if self._writer_task is None:
            return
        # Sentinel ``None`` tells the worker to drain and exit.
        if self._queue is not None:
            await self._queue.put(None)
        try:
            await self._writer_task
        except asyncio.CancelledError:
            pass
        self._writer_task = None
        self._writer_loop = None
        self._queue = None

    async def _writer_loop_fn(self) -> None:
        assert self._queue is not None
        while True:
            item = await self._queue.get()
            if item is None:
                # Drain anything still queued, then exit.
                pending: list[tuple[str, str]] = []
                while not self._queue.empty():
                    nxt = self._queue.get_nowait()
                    if nxt is None:
                        continue
                    pending.append(nxt)
                for path, line in pending:
                    await asyncio.to_thread(self._blocking_write, path, line)
                return
            path, line = item
            await asyncio.to_thread(self._blocking_write, path, line)

    @staticmethod
    def _blocking_write(path: str, line: str) -> None:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            print(f"MCPLogger: failed to write log: {e}", file=sys.stderr)

    def _write(self, record: dict) -> None:
        """Enqueue a record for the async writer.

        Falls back to a synchronous write when no writer is running (unit
        tests, CLI scripts). In production the server starts the writer in
        its FastAPI lifespan, so the fallback path never executes.
        """
        log_path = str(self._rotator.current_log_path())
        line = to_jsonl(record)

        queue = self._queue
        loop = self._writer_loop
        if queue is not None and loop is not None and loop.is_running():
            try:
                # Thread-safe: callers are coroutines on ``loop`` OR other
                # threads invoking logging from sync code. ``call_soon_threadsafe``
                # dispatches the put onto the writer loop.
                loop.call_soon_threadsafe(self._enqueue_nowait, queue, log_path, line)
                return
            except RuntimeError:
                # Loop died between the check and the call — fall through
                # to the sync path.
                pass

        with self._sync_lock:
            self._blocking_write(log_path, line)

    def _enqueue_nowait(
        self, queue: asyncio.Queue, path: str, line: str
    ) -> None:
        try:
            queue.put_nowait((path, line))
        except asyncio.QueueFull:
            # Drop rather than block the request path. Surface the count so
            # ops can see under-provisioned logging.
            self._dropped += 1
            if self._dropped % 1000 == 1:
                print(
                    f"MCPLogger: log queue full — dropped {self._dropped} records",
                    file=sys.stderr,
                )
