"""CLI utility for viewing and filtering MCP logs."""
import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ANSI color codes
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def _color(text: str, code: str) -> str:
    if sys.stdout.isatty():
        return f"{code}{text}{RESET}"
    return text


def _get_log_dir() -> Path:
    return Path(os.environ.get("MCP_LOG_DIR", "/var/log/mcp"))


def _iter_log_files(log_dir: Path, service: str | None, since_date: datetime | None = None) -> list[Path]:
    """Return sorted list of log files (jsonl + jsonl.gz)."""
    files = []
    if service and service != "all":
        services = [service]
    else:
        if log_dir.exists():
            services = [d.name for d in log_dir.iterdir() if d.is_dir()]
        else:
            services = []

    for svc in services:
        svc_dir = log_dir / svc
        if not svc_dir.exists():
            continue
        for f in svc_dir.iterdir():
            if f.name.endswith(".jsonl") or f.name.endswith(".jsonl.gz"):
                if since_date:
                    from .rotation import _parse_date_from_path
                    fdate = _parse_date_from_path(f)
                    if fdate and fdate < since_date:
                        continue
                files.append(f)
    return sorted(files)


def _read_jsonl(path: Path):
    """Yield parsed JSON records from a jsonl or jsonl.gz file."""
    open_fn = gzip.open if path.name.endswith(".gz") else open
    try:
        with open_fn(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _parse_since(since_str: str) -> datetime | None:
    """Parse human-readable since string: '2h ago', 'today', '2026-03-20'."""
    if not since_str:
        return None
    now = datetime.now(timezone.utc)
    s = since_str.lower().strip()
    if s == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if s.endswith(" ago"):
        part = s[: -len(" ago")].strip()
        if part.endswith("h"):
            hours = int(part[:-1])
            return now - timedelta(hours=hours)
        if part.endswith("m"):
            minutes = int(part[:-1])
            return now - timedelta(minutes=minutes)
        if part.endswith("d"):
            days = int(part[:-1])
            return now - timedelta(days=days)
    try:
        return datetime.strptime(since_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _format_record(rec: dict, verbose: bool = False) -> str:
    ts = rec.get("timestamp", "")[:19].replace("T", " ")
    event = rec.get("event_type", "")
    method = rec.get("method", "")
    dur = rec.get("duration_ms", "")
    status = rec.get("status_code", "")
    error = rec.get("error", "")

    dur_str = f" {dur}ms" if dur else ""
    status_str = f" [{status}]" if status else ""
    error_str = f" ERROR: {error}" if error else ""

    line = f"{ts}  {event:<14}  {method:<30}{status_str}{dur_str}{error_str}"

    if "error" in event:
        return _color(line, RED)
    if status and isinstance(status, int) and status >= 400:
        return _color(line, YELLOW)
    return line


def cmd_tail(args: argparse.Namespace) -> None:
    log_dir = _get_log_dir()
    files = _iter_log_files(log_dir, args.service)
    records = []
    for f in files:
        for rec in _read_jsonl(f):
            records.append(rec)
    # Show last N
    for rec in records[-args.lines:]:
        print(_format_record(rec))


def cmd_errors(args: argparse.Namespace) -> None:
    log_dir = _get_log_dir()
    since = _parse_since(args.since) if args.since else None
    files = _iter_log_files(log_dir, args.service, since)
    for f in files:
        for rec in _read_jsonl(f):
            event = rec.get("event_type", "")
            if "error" not in event:
                continue
            ts = rec.get("timestamp", "")
            if since:
                try:
                    rec_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if rec_dt < since:
                        continue
                except ValueError:
                    pass
            print(_color(_format_record(rec), RED))


def cmd_search(args: argparse.Namespace) -> None:
    log_dir = _get_log_dir()
    since = _parse_since(args.since) if args.since else None
    files = _iter_log_files(log_dir, None, since)
    for f in files:
        for rec in _read_jsonl(f):
            if args.method and rec.get("method", "") != args.method:
                continue
            ts = rec.get("timestamp", "")
            if since:
                try:
                    rec_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if rec_dt < since:
                        continue
                except ValueError:
                    pass
            print(_format_record(rec))


def cmd_stats(args: argparse.Namespace) -> None:
    log_dir = _get_log_dir()
    if args.date:
        since = _parse_since(args.date)
    else:
        since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    files = _iter_log_files(log_dir, args.service, since)
    total = 0
    errors = 0
    durations = []
    by_method: dict[str, int] = {}
    by_status: dict[str, int] = {}

    for f in files:
        for rec in _read_jsonl(f):
            event = rec.get("event_type", "")
            if event not in ("api_response", "api_error"):
                continue
            ts = rec.get("timestamp", "")
            if since:
                try:
                    rec_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if rec_dt < since:
                        continue
                except ValueError:
                    pass
            total += 1
            if "error" in event:
                errors += 1
            dur = rec.get("duration_ms")
            if dur:
                durations.append(float(dur))
            method = rec.get("method", "unknown")
            by_method[method] = by_method.get(method, 0) + 1
            status = str(rec.get("status_code", "unknown"))
            by_status[status] = by_status.get(status, 0) + 1

    durations.sort()
    avg = round(sum(durations) / len(durations), 1) if durations else 0
    p95 = durations[int(len(durations) * 0.95)] if durations else 0
    p99 = durations[int(len(durations) * 0.99)] if durations else 0

    print(_color(f"Stats for service={args.service or 'all'} date={args.date or 'today'}", BOLD))
    print(f"  Total requests : {total}")
    print(f"  Errors         : {errors} ({round(errors/total*100, 1) if total else 0}%)")
    print(f"  Avg duration   : {avg}ms")
    print(f"  P95 duration   : {p95}ms")
    print(f"  P99 duration   : {p99}ms")
    print(f"  By method      : {dict(sorted(by_method.items(), key=lambda x: -x[1])[:10])}")
    print(f"  By status      : {dict(sorted(by_status.items(), key=lambda x: -x[1]))}")


def cmd_metrics(args: argparse.Namespace) -> None:
    log_dir = _get_log_dir()
    service = args.service
    if service and service != "all":
        services = [service]
    else:
        services = [d.name for d in log_dir.iterdir() if d.is_dir()] if log_dir.exists() else []

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for svc in services:
        metrics_file = log_dir / svc / f"metrics-{today}.jsonl"
        if not metrics_file.exists():
            print(f"No metrics for {svc} today.")
            continue
        records = list(_read_jsonl(metrics_file))
        if not records:
            print(f"Empty metrics file for {svc}.")
            continue
        last = records[-1]
        print(_color(f"\n=== {svc} ===", BOLD + CYAN))
        for k, v in last.items():
            print(f"  {k}: {v}")


def cmd_slow(args: argparse.Namespace) -> None:
    log_dir = _get_log_dir()
    since = _parse_since(args.since) if args.since else None
    threshold = args.threshold
    files = _iter_log_files(log_dir, None, since)
    found = []
    for f in files:
        for rec in _read_jsonl(f):
            dur = rec.get("duration_ms")
            if dur is None:
                continue
            try:
                dur_f = float(dur)
            except (TypeError, ValueError):
                continue
            if dur_f < threshold:
                continue
            ts = rec.get("timestamp", "")
            if since:
                try:
                    rec_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if rec_dt < since:
                        continue
                except ValueError:
                    pass
            found.append((dur_f, rec))

    found.sort(key=lambda x: -x[0])
    for dur_f, rec in found:
        print(_color(f"[{dur_f}ms] {_format_record(rec)}", YELLOW))


def cmd_cleanup(args: argparse.Namespace) -> None:
    log_dir = _get_log_dir()
    # Parse "7d" -> 7 days
    older_than = args.older_than
    days = int(older_than.rstrip("d"))
    threshold = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = 0
    for svc_dir in log_dir.iterdir():
        if not svc_dir.is_dir():
            continue
        for f in svc_dir.iterdir():
            if not (f.name.endswith(".jsonl") or f.name.endswith(".jsonl.gz")):
                continue
            from .rotation import _parse_date_from_path
            fdate = _parse_date_from_path(f)
            if fdate and fdate < threshold:
                f.unlink(missing_ok=True)
                print(f"Deleted: {f}")
                deleted += 1
    print(f"Cleaned up {deleted} file(s) older than {days} days.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-logs", description="MCP log viewer and analyzer")
    sub = parser.add_subparsers(dest="command")

    # tail
    p_tail = sub.add_parser("tail", help="Show last N log records")
    p_tail.add_argument("--service", default=None)
    p_tail.add_argument("--lines", type=int, default=50)

    # errors
    p_err = sub.add_parser("errors", help="Show error records")
    p_err.add_argument("--service", default=None)
    p_err.add_argument("--since", default=None, help="e.g. '2h ago', 'today', '2026-03-20'")

    # search
    p_search = sub.add_parser("search", help="Filter by method")
    p_search.add_argument("--method", required=True)
    p_search.add_argument("--since", default=None)

    # stats
    p_stats = sub.add_parser("stats", help="Aggregated statistics")
    p_stats.add_argument("--service", default=None)
    p_stats.add_argument("--date", default=None)

    # metrics
    p_metrics = sub.add_parser("metrics", help="Show latest metrics dump")
    p_metrics.add_argument("--service", default="all")

    # slow
    p_slow = sub.add_parser("slow", help="Show slow requests")
    p_slow.add_argument("--threshold", type=float, default=1000, help="ms threshold")
    p_slow.add_argument("--since", default=None)

    # cleanup
    p_cleanup = sub.add_parser("cleanup", help="Delete old log files")
    p_cleanup.add_argument("--older-than", default="7d", help="e.g. '7d'")

    args = parser.parse_args()
    if args.command == "tail":
        cmd_tail(args)
    elif args.command == "errors":
        cmd_errors(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "metrics":
        cmd_metrics(args)
    elif args.command == "slow":
        cmd_slow(args)
    elif args.command == "cleanup":
        cmd_cleanup(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
