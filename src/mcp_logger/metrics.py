"""In-memory metrics: counters, sliding window p95/p99, periodic dump."""
import asyncio
import sys
import json
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


class MetricsCollector:
    MAX_DURATIONS = 10_000  # sliding window size

    def __init__(self, service_name: str, log_dir: str, dump_interval: int = 3600):
        self.service_name = service_name
        self._metrics_dir = Path(log_dir) / service_name
        self._metrics_dir.mkdir(parents=True, exist_ok=True)
        self.dump_interval = dump_interval

        self._total_requests: int = 0
        self._total_errors: int = 0
        self._by_method: dict[str, int] = defaultdict(int)
        self._by_status: dict[str, int] = defaultdict(int)
        self._by_error_type: dict[str, int] = defaultdict(int)

        # (timestamp, duration_ms) pairs for sliding window
        self._durations: deque[tuple[float, float]] = deque(maxlen=self.MAX_DURATIONS)

        self._rate_limit_remaining: int | None = None
        self._rate_limit_reset: str | None = None
        self._period_start = datetime.now(timezone.utc)
        self._dump_task: asyncio.Task | None = None

    def record_request(
        self,
        method: str,
        status_code: int | str | None,
        duration_ms: float,
        is_error: bool = False,
        error_type: str | None = None,
        rate_limit_remaining: int | None = None,
        rate_limit_reset: str | None = None,
    ) -> None:
        self._total_requests += 1
        self._by_method[method] += 1
        key = str(status_code) if status_code is not None else "unknown"
        self._by_status[key] += 1
        if is_error:
            self._total_errors += 1
            if error_type:
                self._by_error_type[error_type] += 1
        ts = datetime.now(timezone.utc).timestamp()
        self._durations.append((ts, duration_ms))
        if rate_limit_remaining is not None:
            self._rate_limit_remaining = rate_limit_remaining
        if rate_limit_reset is not None:
            self._rate_limit_reset = rate_limit_reset

    def _prune_old_durations(self) -> list[float]:
        """Return durations from the last hour only."""
        cutoff = datetime.now(timezone.utc).timestamp() - 3600
        return [d for ts, d in self._durations if ts >= cutoff]

    def _percentile(self, sorted_values: list[float], p: float) -> float:
        if not sorted_values:
            return 0.0
        idx = int(len(sorted_values) * p / 100)
        idx = min(idx, len(sorted_values) - 1)
        return round(sorted_values[idx], 2)

    def snapshot(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        durations = sorted(self._prune_old_durations())
        avg_d = round(sum(durations) / len(durations), 2) if durations else 0.0
        error_rate = round(self._total_errors / self._total_requests, 4) if self._total_requests else 0.0
        return {
            "timestamp": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "service": self.service_name,
            "period": (
                f"{self._period_start.isoformat(timespec='seconds').replace('+00:00', 'Z')}"
                f"/{now.isoformat(timespec='seconds').replace('+00:00', 'Z')}"
            ),
            "total_requests": self._total_requests,
            "errors": self._total_errors,
            "error_rate": error_rate,
            "avg_duration_ms": avg_d,
            "p95_duration_ms": self._percentile(durations, 95),
            "p99_duration_ms": self._percentile(durations, 99),
            "by_method": dict(self._by_method),
            "by_status": dict(self._by_status),
            "rate_limit_remaining": self._rate_limit_remaining,
            "rate_limit_reset": self._rate_limit_reset,
        }

    def dump_to_file(self) -> None:
        snap = self.snapshot()
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        metrics_file = self._metrics_dir / f"metrics-{date_str}.jsonl"
        with open(metrics_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(snap, ensure_ascii=False) + "\n")
        self._period_start = datetime.now(timezone.utc)

    def reset_counters(self) -> None:
        self._total_requests = 0
        self._total_errors = 0
        self._by_method.clear()
        self._by_status.clear()
        self._by_error_type.clear()

    async def start_periodic_dump(self) -> None:
        """Start background task that dumps metrics every dump_interval seconds."""
        self._dump_task = asyncio.create_task(self._dump_loop())

    async def _dump_loop(self) -> None:
        while True:
            await asyncio.sleep(self.dump_interval)
            try:
                self.dump_to_file()
                self.reset_counters()
            except Exception as e:
                print(f"MCPLogger: metrics dump error: {e}", file=sys.stderr)

    async def stop(self) -> None:
        if self._dump_task:
            self._dump_task.cancel()
            try:
                await self._dump_task
            except asyncio.CancelledError:
                pass
        self.dump_to_file()
