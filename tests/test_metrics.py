"""Tests for metrics module."""
import json
import asyncio

import pytest
from mcp_logger.metrics import MetricsCollector


@pytest.fixture
def collector(tmp_path):
    return MetricsCollector(
        service_name="test-svc",
        log_dir=str(tmp_path),
        dump_interval=3600,
    )


def test_record_request_increments_total(collector):
    collector.record_request("Campaigns.get", 200, 150.0)
    snap = collector.snapshot()
    assert snap["total_requests"] == 1


def test_record_error_increments_errors(collector):
    collector.record_request("Campaigns.get", "error", 500.0, is_error=True, error_type="TimeoutError")
    snap = collector.snapshot()
    assert snap["errors"] == 1
    assert snap["total_requests"] == 1


def test_error_rate_calculation(collector):
    collector.record_request("m1", 200, 100.0)
    collector.record_request("m1", "error", 200.0, is_error=True)
    snap = collector.snapshot()
    assert snap["error_rate"] == 0.5


def test_by_method_counter(collector):
    collector.record_request("Campaigns.get", 200, 100.0)
    collector.record_request("Campaigns.get", 200, 150.0)
    collector.record_request("Ads.get", 200, 80.0)
    snap = collector.snapshot()
    assert snap["by_method"]["Campaigns.get"] == 2
    assert snap["by_method"]["Ads.get"] == 1


def test_by_status_counter(collector):
    collector.record_request("m", 200, 100.0)
    collector.record_request("m", 400, 50.0)
    collector.record_request("m", 200, 120.0)
    snap = collector.snapshot()
    assert snap["by_status"]["200"] == 2
    assert snap["by_status"]["400"] == 1


def test_avg_duration(collector):
    collector.record_request("m", 200, 100.0)
    collector.record_request("m", 200, 200.0)
    snap = collector.snapshot()
    assert snap["avg_duration_ms"] == 150.0


def test_p95_p99(collector):
    for i in range(100):
        collector.record_request("m", 200, float(i + 1))
    snap = collector.snapshot()
    assert snap["p95_duration_ms"] >= 95.0
    assert snap["p99_duration_ms"] >= 99.0


def test_rate_limit_tracking(collector):
    collector.record_request("m", 200, 100.0, rate_limit_remaining=4850, rate_limit_reset="2026-03-20T15:00:00Z")
    snap = collector.snapshot()
    assert snap["rate_limit_remaining"] == 4850
    assert snap["rate_limit_reset"] == "2026-03-20T15:00:00Z"


def test_dump_to_file(collector, tmp_path):
    collector.record_request("Campaigns.get", 200, 250.0)
    collector.dump_to_file()
    from datetime import datetime, timezone
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    metrics_file = tmp_path / "test-svc" / f"metrics-{date_str}.jsonl"
    assert metrics_file.exists()
    data = json.loads(metrics_file.read_text().strip().splitlines()[-1])
    assert data["service"] == "test-svc"
    assert data["total_requests"] == 1


def test_reset_counters(collector):
    collector.record_request("m", 200, 100.0)
    collector.reset_counters()
    snap = collector.snapshot()
    assert snap["total_requests"] == 0
    assert snap["errors"] == 0


def test_snapshot_has_required_fields(collector):
    snap = collector.snapshot()
    required = ["timestamp", "service", "period", "total_requests", "errors",
                "error_rate", "avg_duration_ms", "p95_duration_ms", "p99_duration_ms",
                "by_method", "by_status", "rate_limit_remaining", "rate_limit_reset"]
    for field in required:
        assert field in snap, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_periodic_dump_runs(collector, tmp_path):
    collector.dump_interval = 0.05  # 50ms for test
    collector.record_request("m", 200, 100.0)
    await collector.start_periodic_dump()
    await asyncio.sleep(0.15)
    await collector.stop()
    from datetime import datetime, timezone
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    metrics_file = tmp_path / "test-svc" / f"metrics-{date_str}.jsonl"
    assert metrics_file.exists()
