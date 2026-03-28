"""Tests for sanitizer module."""
from mcp_logger.sanitizer import sanitize, _mask_string


def test_mask_sensitive_field():
    data = {"token": "abcdefghijklmnopqrstuvwxyz"}
    result = sanitize(data)
    assert result["token"] == "abcd****xyz"


def test_original_not_mutated():
    data = {"token": "abcdefghijklmnopqrstuvwxyz"}
    original = data.copy()
    sanitize(data)
    assert data == original


def test_none_value_not_masked():
    data = {"token": None}
    result = sanitize(data)
    assert result["token"] is None


def test_empty_string_not_masked():
    data = {"token": ""}
    result = sanitize(data)
    assert result["token"] == ""


def test_non_sensitive_field_not_masked():
    data = {"method": "Campaigns.get", "id": 123}
    result = sanitize(data)
    assert result["method"] == "Campaigns.get"
    assert result["id"] == 123


def test_nested_dict_recursion():
    data = {"params": {"authorization": "Bearer supersecrettoken123456"}}
    result = sanitize(data)
    assert "****" in result["params"]["authorization"]
    assert result["params"]["authorization"] != "Bearer supersecrettoken123456"


def test_list_recursion():
    data = [{"token": "abcdefghijklmnopqrstuvwxyz"}, {"other": "value"}]
    result = sanitize(data)
    assert "****" in result[0]["token"]
    assert result[1]["other"] == "value"


def test_bearer_in_string_masked():
    data = {"headers": "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc"}
    result = sanitize(data)
    assert "****" in result["headers"]
    assert "eyJh" in result["headers"]


def test_short_token_fully_masked():
    assert _mask_string("short") == "****"


def test_custom_sensitive_fields():
    data = {"mytoken": "supersecret12345678", "name": "Alice"}
    result = sanitize(data, sensitive_fields=["mytoken"])
    assert "****" in result["mytoken"]
    assert result["name"] == "Alice"


def test_case_insensitive_field_matching():
    data = {"Authorization": "Bearer supersecret123456789"}
    result = sanitize(data)
    assert "****" in result["Authorization"]
