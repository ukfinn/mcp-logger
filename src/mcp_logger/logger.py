"""Core MCPLogger class — writes JSONL audit logs."""
import json
import sys
import uuid
from typing import Any

from .config import LoggerConfig
from .formatters import to_jsonl, now_utc
from .rotation import LogRotator
from .sanitizer import sanitize
from .metrics import MetricsCollector


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

    def _write(self, record: dict) -> None:
        log_path = self._rotator.current_log_path()
        line = to_jsonl(record)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            print(f"MCPLogger: failed to write log: {e}", file=sys.stderr)
