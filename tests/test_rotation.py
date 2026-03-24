"""Tests for rotation module."""
import gzip
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from mcp_logger.rotation import LogRotator, _parse_date_from_path, _compress_file


@pytest.fixture
def rotator(tmp_path):
    return LogRotator(
        log_dir=str(tmp_path),
        service_name="test-svc",
        retention_days=7,
        compress_after_days=1,
    )


def test_current_log_path_includes_date(rotator):
    path = rotator.current_log_path()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert today in path.name
    assert path.suffix == ".jsonl"


def test_directory_created(tmp_path):
    r = LogRotator(log_dir=str(tmp_path), service_name="new-svc")
    assert (tmp_path / "new-svc").exists()


def test_parse_date_from_path():
    p = Path("/var/log/mcp/yandex-direct/yandex-direct-2026-03-20.jsonl")
    dt = _parse_date_from_path(p)
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 3
    assert dt.day == 20


def test_parse_date_from_gz_path():
    p = Path("/var/log/mcp/yandex-direct/yandex-direct-2026-03-19.jsonl.gz")
    dt = _parse_date_from_path(p)
    assert dt is not None
    assert dt.day == 19


def test_parse_date_returns_none_for_unknown():
    p = Path("/some/unknown-file.txt")
    assert _parse_date_from_path(p) is None


def test_compress_file(tmp_path):
    test_file = tmp_path / "test-svc" / "test-svc-2026-03-01.jsonl"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text('{"test": 1}\n')
    _compress_file(test_file)
    gz_file = Path(str(test_file) + ".gz")
    assert gz_file.exists()
    assert not test_file.exists()
    # Verify content
    with gzip.open(gz_file, "rt") as f:
        content = f.read()
    assert '"test": 1' in content


def test_compress_file_idempotent(tmp_path):
    test_file = tmp_path / "test-svc-2026-03-01.jsonl"
    test_file.write_text('{"test": 1}\n')
    gz_file = Path(str(test_file) + ".gz")
    gz_file.write_bytes(b"existing")
    # Should not overwrite existing gz
    _compress_file(test_file)
    assert gz_file.read_bytes() == b"existing"


def test_maintenance_deletes_old_files(tmp_path):
    r = LogRotator(log_dir=str(tmp_path), service_name="test-svc", retention_days=7)
    svc_dir = tmp_path / "test-svc"
    # Create old file (10 days ago)
    old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
    old_file = svc_dir / f"test-svc-{old_date}.jsonl"
    old_file.write_text('{"old": true}\n')
    r.run_maintenance()
    assert not old_file.exists()


def test_maintenance_keeps_recent_files(tmp_path):
    r = LogRotator(log_dir=str(tmp_path), service_name="test-svc", retention_days=7)
    svc_dir = tmp_path / "test-svc"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    recent_file = svc_dir / f"test-svc-{today}.jsonl"
    recent_file.write_text('{"recent": true}\n')
    r.run_maintenance()
    # Today's file should NOT be compressed (compress_after_days=1 means yesterday and older)
    assert recent_file.exists()
