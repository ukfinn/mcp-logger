"""Unit tests for mcp_logger.formatters."""
import json
from datetime import datetime, timezone

import pytest

from mcp_logger.formatters import to_jsonl, now_utc


def test_to_jsonl_simple_dict():
    line = to_jsonl({"a": 1})
    assert line[-1] == chr(10)
    parsed = json.loads(line)
    assert parsed == {"a": 1}


def test_to_jsonl_datetime():
    dt = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    line = to_jsonl({"ts": dt})
    parsed = json.loads(line)
    assert isinstance(parsed["ts"], str)
    assert "2024" in parsed["ts"]


def test_to_jsonl_bytes():
    line = to_jsonl({"data": b"hello"})
    parsed = json.loads(line)
    assert parsed["data"] == "hello"


def test_now_utc_format():
    ts = now_utc()
    assert isinstance(ts, str)
    assert ts.endswith("Z")


def test_now_utc_is_recent():
    ts = now_utc()
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    diff = abs((now - parsed).total_seconds())
    assert diff < 2
