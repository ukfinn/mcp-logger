"""Tests for mcp_logger.decorators."""
import pytest
from unittest.mock import MagicMock

import httpx

from mcp_logger.decorators import (
    wrap_async_method,
    log_mcp_tool,
    _infer_method,
    get_correlation_id,
    _correlation_id,
)


def _make_mock_logger():
    logger = MagicMock()
    logger.log_api_request = MagicMock()
    logger.log_api_response = MagicMock()
    logger.log_api_error = MagicMock()
    logger.log_mcp_request = MagicMock()
    logger.log_mcp_response = MagicMock()
    logger.log_mcp_error = MagicMock()
    return logger


# ---------------------------------------------------------------------------
# wrap_async_method tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wrap_async_method_logs_request_and_response():
    logger = _make_mock_logger()

    @wrap_async_method(logger, "test_method")
    async def my_func(**kwargs):
        return {"ok": True}

    await my_func(param="value")

    assert logger.log_api_request.called
    assert logger.log_api_response.called


@pytest.mark.asyncio
async def test_wrap_async_method_logs_error_on_exception():
    logger = _make_mock_logger()

    @wrap_async_method(logger, "test_method")
    async def my_func(**kwargs):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await my_func()

    assert logger.log_api_error.called
    assert not logger.log_api_response.called


@pytest.mark.asyncio
async def test_wrap_async_method_preserves_return_value():
    logger = _make_mock_logger()

    @wrap_async_method(logger, "test_method")
    async def my_func():
        return 42

    result = await my_func()
    assert result == 42


@pytest.mark.asyncio
async def test_wrap_async_method_reraises_exception():
    logger = _make_mock_logger()

    @wrap_async_method(logger, "test_method")
    async def my_func():
        raise RuntimeError("re-raise me")

    with pytest.raises(RuntimeError, match="re-raise me"):
        await my_func()


# ---------------------------------------------------------------------------
# log_mcp_tool tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_mcp_tool_sets_correlation_id():
    logger = _make_mock_logger()
    captured = {}

    @log_mcp_tool(logger)
    async def my_tool(**kwargs):
        captured["cid"] = get_correlation_id()
        return "done"

    await my_tool()
    assert captured["cid"] is not None


@pytest.mark.asyncio
async def test_log_mcp_tool_resets_correlation_id():
    logger = _make_mock_logger()

    token = _correlation_id.set(None)
    try:
        @log_mcp_tool(logger)
        async def my_tool(**kwargs):
            return "done"

        await my_tool()
        assert get_correlation_id() is None
    finally:
        _correlation_id.reset(token)


# ---------------------------------------------------------------------------
# _infer_method tests
# ---------------------------------------------------------------------------

def test_infer_method_from_url():
    request = MagicMock(spec=httpx.Request)
    request.url = MagicMock()
    request.url.path = "/json/v5/campaigns"
    result = _infer_method(request)
    assert result == "campaigns"


def test_infer_method_from_root():
    request = MagicMock(spec=httpx.Request)
    request.url = MagicMock()
    request.url.path = "/"
    result = _infer_method(request)
    assert result == "/"
