"""Unit tests for mcp_logger.config.LoggerConfig."""
import os

from mcp_logger.config import LoggerConfig


def test_default_config():
    env_keys = [
        "MCP_LOG_DIR", "MCP_LOG_MAX_BODY_SIZE", "MCP_LOG_RETENTION_DAYS",
        "MCP_LOG_COMPRESS_AFTER_DAYS", "MCP_LOG_METRICS_DUMP_INTERVAL",
        "MCP_LOG_SENSITIVE_FIELDS",
    ]
    clean = {k: os.environ.pop(k) for k in env_keys if k in os.environ}
    try:
        cfg = LoggerConfig()
        assert cfg.log_dir == "/var/log/mcp"
        assert cfg.max_body_size == 51200
        assert cfg.retention_days == 7
        assert cfg.compress_after_days == 1
        assert cfg.metrics_dump_interval == 3600
    finally:
        os.environ.update(clean)


def test_config_from_dict():
    clean = {}
    if "MCP_LOG_DIR" in os.environ:
        clean["MCP_LOG_DIR"] = os.environ.pop("MCP_LOG_DIR")
    try:
        cfg = LoggerConfig({"log_dir": "/custom"})
        assert cfg.log_dir == "/custom"
    finally:
        os.environ.update(clean)


def test_config_from_env():
    os.environ["MCP_LOG_DIR"] = "/from/env"
    try:
        cfg = LoggerConfig()
        assert cfg.log_dir == "/from/env"
    finally:
        del os.environ["MCP_LOG_DIR"]


def test_config_env_overrides_dict():
    os.environ["MCP_LOG_DIR"] = "/env/wins"
    try:
        cfg = LoggerConfig({"log_dir": "/dict/loses"})
        assert cfg.log_dir == "/env/wins"
    finally:
        del os.environ["MCP_LOG_DIR"]


def test_sensitive_fields_default():
    saved = os.environ.pop("MCP_LOG_SENSITIVE_FIELDS", None)
    try:
        cfg = LoggerConfig()
        for field in ("token", "password"):
            assert field in cfg.sensitive_fields
    finally:
        if saved is not None:
            os.environ["MCP_LOG_SENSITIVE_FIELDS"] = saved


def test_sensitive_fields_from_env():
    os.environ["MCP_LOG_SENSITIVE_FIELDS"] = "foo,bar"
    try:
        cfg = LoggerConfig()
        assert cfg.sensitive_fields == ["foo", "bar"]
    finally:
        del os.environ["MCP_LOG_SENSITIVE_FIELDS"]
