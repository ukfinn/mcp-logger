"""Decorators and wrappers for httpx clients and MCP tools."""
import contextvars
import functools
import time
import uuid
from typing import Any, Callable

import httpx

from .logger import MCPLogger

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def create_httpx_hooks(logger: MCPLogger) -> dict:
    """
    Returns dict of event_hooks for httpx.AsyncClient.
    Usage: client = httpx.AsyncClient(event_hooks=create_httpx_hooks(logger))
    """
    # Store timing info keyed by request object id
    _timings: dict[int, float] = {}

    async def log_request(request: httpx.Request) -> None:
        request_id = str(uuid.uuid4())
        request.extensions["mcp_request_id"] = request_id.encode()
        _timings[id(request)] = time.monotonic()
        try:
            body = request.content
            try:
                import json
                body_parsed = json.loads(body)
            except Exception:
                body_parsed = body.decode("utf-8", errors="replace") if body else None
        except Exception:
            body_parsed = None

        method = _infer_method(request)
        logger.log_api_request(
            method=method,
            url=str(request.url),
            http_method=request.method,
            request_body=body_parsed,
            request_id=request_id,
            correlation_id=_correlation_id.get(),
        )

    async def log_response(response: httpx.Response) -> None:
        start = _timings.pop(id(response.request), None)
        duration_ms = round((time.monotonic() - start) * 1000, 2) if start else 0.0
        request_id_bytes = response.request.extensions.get("mcp_request_id", b"")
        request_id = request_id_bytes.decode() if request_id_bytes else None

        try:
            await response.aread()
            try:
                body_parsed = response.json()
            except Exception:
                body_parsed = response.text
        except Exception:
            body_parsed = None

        rate_remaining = _parse_int_header(response, "X-RateLimit-Remaining")
        rate_reset = response.headers.get("X-RateLimit-Reset")
        method = _infer_method(response.request)

        logger.log_api_response(
            method=method,
            url=str(response.request.url),
            http_method=response.request.method,
            status_code=response.status_code,
            duration_ms=duration_ms,
            response_body=body_parsed,
            request_id=request_id,
            correlation_id=_correlation_id.get(),
            rate_limit_remaining=rate_remaining,
            rate_limit_reset=rate_reset,
        )

    return {"request": [log_request], "response": [log_response]}


def wrap_async_method(logger: MCPLogger, method_name: str) -> Callable:
    """
    Decorator for an async method that makes an HTTP call.
    Logs request, response, duration, errors.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            request_id = str(uuid.uuid4())
            correlation_id = _correlation_id.get()
            start = time.monotonic()
            logger.log_api_request(
                method=method_name,
                url="",
                request_body=kwargs,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            try:
                result = await func(*args, **kwargs)
                duration_ms = round((time.monotonic() - start) * 1000, 2)
                logger.log_api_response(
                    method=method_name,
                    url="",
                    duration_ms=duration_ms,
                    response_body=result,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                return result
            except Exception as exc:
                duration_ms = round((time.monotonic() - start) * 1000, 2)
                logger.log_api_error(
                    method=method_name,
                    url="",
                    error=str(exc),
                    error_type=type(exc).__name__,
                    duration_ms=duration_ms,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                raise

        return wrapper

    return decorator


def log_mcp_tool(logger: MCPLogger) -> Callable:
    """
    Decorator for MCP tool functions.
    Logs: tool name, input params, duration, result/error.
    Sets correlation_id via contextvars so httpx hooks can link API calls.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            correlation_id = str(uuid.uuid4())
            token = _correlation_id.set(correlation_id)
            request_id = str(uuid.uuid4())
            tool_name = func.__name__
            start = time.monotonic()

            logger.log_mcp_request(
                method=tool_name,
                request_body=kwargs if kwargs else None,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            try:
                result = await func(*args, **kwargs)
                duration_ms = round((time.monotonic() - start) * 1000, 2)
                logger.log_mcp_response(
                    method=tool_name,
                    duration_ms=duration_ms,
                    response_body=result,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                return result
            except Exception as exc:
                duration_ms = round((time.monotonic() - start) * 1000, 2)
                logger.log_mcp_error(
                    method=tool_name,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    duration_ms=duration_ms,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                raise
            finally:
                _correlation_id.reset(token)

        return wrapper

    return decorator


def _infer_method(request: httpx.Request) -> str:
    """Try to infer MCP method name from request URL or body."""
    path = request.url.path
    # e.g. /json/v5/campaigns -> "campaigns"
    parts = [p for p in path.split("/") if p]
    return parts[-1] if parts else path


def _parse_int_header(response: httpx.Response, header: str) -> int | None:
    val = response.headers.get(header)
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
