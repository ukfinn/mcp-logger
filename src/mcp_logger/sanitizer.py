"""Masking of tokens, API keys, and other secrets before logging."""
import copy
import re
from typing import Any

_BEARER_RE = re.compile(r"(Bearer\s+|OAuth\s+)([a-zA-Z0-9_\-\.]{4})[a-zA-Z0-9_\-\.]{13,}([a-zA-Z0-9_\-\.]{3})")
_B24_WEBHOOK_RE = re.compile(r"(/rest/\d+/)([a-zA-Z0-9]{4})[a-zA-Z0-9]{8,}([a-zA-Z0-9]{3})(/)")


def _mask_string(value: str) -> str:
    """Mask a token-like string: keep first 4 and last 3 chars."""
    if len(value) <= 10:
        return "****"
    return value[:4] + "****" + value[-3:]


def _mask_value(value: str) -> str:
    """Apply all masking regexes to a string value."""
    value = _BEARER_RE.sub(lambda m: m.group(1) + m.group(2) + "****" + m.group(3), value)
    value = _B24_WEBHOOK_RE.sub(
        lambda m: m.group(1) + m.group(2) + "****" + m.group(3) + m.group(4), value
    )
    return value


def sanitize(data: Any, sensitive_fields: list[str] | None = None) -> Any:
    """
    Recursively sanitize data, masking sensitive fields.
    Does NOT mutate the original — works on a deep copy.
    """
    if sensitive_fields is None:
        sensitive_fields = ["token", "key", "secret", "password", "webhook", "authorization"]

    data = copy.deepcopy(data)
    return _sanitize_recursive(data, [f.lower() for f in sensitive_fields])


def _sanitize_recursive(data: Any, sensitive_fields: list[str]) -> Any:
    if isinstance(data, dict):
        for k, v in data.items():
            if k.lower() in sensitive_fields:
                if isinstance(v, str) and v:
                    data[k] = _mask_string(v)
                elif isinstance(v, str):
                    pass  # keep empty string as-is
                elif v is not None:
                    data[k] = "****"
            else:
                data[k] = _sanitize_recursive(v, sensitive_fields)
    elif isinstance(data, list):
        data = [_sanitize_recursive(item, sensitive_fields) for item in data]
    elif isinstance(data, str):
        data = _mask_value(data)
    return data
