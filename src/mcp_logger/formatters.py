"""JSONL formatting for log records."""
import json
from datetime import datetime, timezone
from typing import Any


def to_jsonl(record: dict) -> str:
    """Serialize a log record to a JSONL line."""
    return json.dumps(record, ensure_ascii=False, default=_default_serializer) + "\n"


def _default_serializer(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return str(obj)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
