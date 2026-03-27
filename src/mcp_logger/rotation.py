"""Daily log rotation, gzip compression, and cleanup of old logs."""
import gzip
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path


class LogRotator:
    def __init__(
        self,
        log_dir: str,
        service_name: str,
        retention_days: int = 7,
        compress_after_days: int = 1,
    ):
        self.log_dir = Path(log_dir) / service_name
        self.service_name = service_name
        self.retention_days = retention_days
        self.compress_after_days = compress_after_days
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def current_log_path(self, prefix: str = "") -> Path:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        name = prefix if prefix else self.service_name
        return self.log_dir / f"{name}-{date_str}.jsonl"

    def run_maintenance(self) -> None:
        """Compress old files, delete expired ones."""
        now = datetime.now(timezone.utc)
        compress_threshold = now - timedelta(days=self.compress_after_days)
        delete_threshold = now - timedelta(days=self.retention_days)

        for path in self.log_dir.iterdir():
            if path.suffix == ".jsonl":
                file_date = _parse_date_from_path(path)
                if file_date is None:
                    continue
                if file_date < delete_threshold:
                    path.unlink(missing_ok=True)
                elif file_date < compress_threshold:
                    _compress_file(path)
            elif path.name.endswith(".jsonl.gz"):
                file_date = _parse_date_from_path(path)
                if file_date is None:
                    continue
                if file_date < delete_threshold:
                    path.unlink(missing_ok=True)


def _parse_date_from_path(path: Path) -> datetime | None:
    """Extract date from filename like service-2026-03-20.jsonl[.gz]."""
    name = path.name.replace(".jsonl.gz", "").replace(".jsonl", "")
    parts = name.rsplit("-", 3)
    if len(parts) < 4:
        return None
    try:
        date_str = f"{parts[-3]}-{parts[-2]}-{parts[-1]}"
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return None


def _compress_file(path: Path) -> None:
    """Compress a .jsonl file to .jsonl.gz in place."""
    gz_path = Path(str(path) + ".gz")
    if gz_path.exists():
        return
    try:
        with open(path, "rb") as f_in:
            with gzip.open(gz_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        path.unlink()
    except OSError:
        if gz_path.exists():
            gz_path.unlink(missing_ok=True)
