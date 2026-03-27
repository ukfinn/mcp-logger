"""Configuration for mcp_logger via env vars or dict."""
import os


class LoggerConfig:
    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.log_dir: str = os.environ.get("MCP_LOG_DIR", cfg.get("log_dir", "/var/log/mcp"))
        self.max_body_size: int = int(os.environ.get("MCP_LOG_MAX_BODY_SIZE", cfg.get("max_body_size", 51200)))
        self.retention_days: int = int(os.environ.get("MCP_LOG_RETENTION_DAYS", cfg.get("retention_days", 7)))
        self.compress_after_days: int = int(
            os.environ.get("MCP_LOG_COMPRESS_AFTER_DAYS", cfg.get("compress_after_days", 1))
        )
        self.metrics_dump_interval: int = int(
            os.environ.get("MCP_LOG_METRICS_DUMP_INTERVAL", cfg.get("metrics_dump_interval", 3600))
        )
        sensitive_fields_env = os.environ.get("MCP_LOG_SENSITIVE_FIELDS", "")
        default_fields = ["token", "key", "secret", "password", "webhook", "authorization"]
        if sensitive_fields_env:
            self.sensitive_fields: list[str] = [f.strip() for f in sensitive_fields_env.split(",")]
        else:
            self.sensitive_fields = cfg.get("sensitive_fields", default_fields)
