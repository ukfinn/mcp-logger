"""Tests for MCPLogger core."""
import json
import tempfile
from pathlib import Path

import pytest
from mcp_logger import MCPLogger


@pytest.fixture
def tmp_logger(tmp_path):
    return MCPLogger(
        service_name="test-svc",
        log_dir=str(tmp_path),
        max_body_size=100,
        retention_days=7,
    )


def _read_last_record(logger: MCPLogger) -> dict:
    log_file = logger._rotator.current_log_path()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    return json.loads(lines[-1])


def test_log_api_request_creates_file(tmp_logger):
    tmp_logger.log_api_request(
        method="Campaigns.get",
        url="https://api.direct.yandex.com/json/v5/campaigns",
        http_method="POST",
        request_body={"method": "get", "params": {}},
    )
    log_file = tmp_logger._rotator.current_log_path()
    assert log_file.exists()


def test_log_api_request_fields(tmp_logger):
    rid = tmp_logger.log_api_request(
        method="Campaigns.get",
        url="https://example.com",
        request_body={"key": "value"},
    )
    rec = _read_last_record(tmp_logger)
    assert rec["event_type"] == "api_request"
    assert rec["method"] == "Campaigns.get"
    assert rec["url"] == "https://example.com"
    assert rec["service"] == "test-svc"
    assert rec["request_id"] == rid
    assert "timestamp" in rec


def test_log_api_response_fields(tmp_logger):
    tmp_logger.log_api_response(
        method="Campaigns.get",
        url="https://example.com",
        status_code=200,
        duration_ms=123.4,
        response_body={"result": "ok"},
    )
    rec = _read_last_record(tmp_logger)
    assert rec["event_type"] == "api_response"
    assert rec["status_code"] == 200
    assert rec["duration_ms"] == 123.4


def test_body_truncation(tmp_logger):
    big_body = {"data": "x" * 200}
    tmp_logger.log_api_request(
        method="Test",
        url="https://example.com",
        request_body=big_body,
    )
    rec = _read_last_record(tmp_logger)
    assert rec["body_truncated"] is True
    assert rec["extra"].get("original_request_body_size", 0) > 100


def test_body_not_truncated_when_small(tmp_logger):
    small_body = {"key": "val"}
    tmp_logger.log_api_request(
        method="Test",
        url="https://example.com",
        request_body=small_body,
    )
    rec = _read_last_record(tmp_logger)
    assert rec["body_truncated"] is False


def test_log_mcp_request_and_response(tmp_logger):
    rid = tmp_logger.log_mcp_request(method="get_campaigns", request_body={"client": "test"})
    tmp_logger.log_mcp_response(method="get_campaigns", duration_ms=55.0, request_id=rid)
    # Read second-to-last and last
    log_file = tmp_logger._rotator.current_log_path()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    req_rec = json.loads(lines[-2])
    resp_rec = json.loads(lines[-1])
    assert req_rec["event_type"] == "mcp_request"
    assert resp_rec["event_type"] == "mcp_response"
    assert resp_rec["duration_ms"] == 55.0


def test_log_api_error(tmp_logger):
    tmp_logger.log_api_error(
        method="Campaigns.get",
        url="https://example.com",
        error="Connection timeout",
        error_type="TimeoutError",
        duration_ms=5000.0,
    )
    rec = _read_last_record(tmp_logger)
    assert rec["event_type"] == "api_error"
    assert rec["error"] == "Connection timeout"
    assert rec["error_type"] == "TimeoutError"


def test_jsonl_format_valid(tmp_logger):
    tmp_logger.log_api_request(method="Test", url="https://example.com")
    log_file = tmp_logger._rotator.current_log_path()
    for line in log_file.read_text(encoding="utf-8").strip().splitlines():
        obj = json.loads(line)
        assert isinstance(obj, dict)


def test_token_masked_in_log(tmp_logger):
    tmp_logger.log_api_request(
        method="Test",
        url="https://example.com",
        request_body={"token": "verysecrettoken12345"},
    )
    rec = _read_last_record(tmp_logger)
    token_val = rec["request_body"]["token"]
    assert "****" in token_val
    assert token_val != "verysecrettoken12345"
