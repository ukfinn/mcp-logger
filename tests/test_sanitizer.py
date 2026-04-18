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


# ── P3-001: bare Yandex y0_ tokens in arbitrary string values ──


def test_yandex_y0_token_in_nonsensitive_field_masked():
    """Regression guard: a raw y0_ token pasted into a free-text field
    (no Bearer/OAuth prefix, no sensitive key name) must still be
    scrubbed before the line reaches disk.

    NB: all y0_ strings in this file are synthetic fixtures shaped like
    real Yandex tokens but known not to resolve to a valid account.
    """
    tok = "y0_FAKE" + "X" * 50
    data = {"comment": f"please paste it here: {tok} thanks"}
    result = sanitize(data)
    assert tok not in result["comment"]
    assert "y0_F" in result["comment"]          # prefix preserved for debuggability
    assert "****" in result["comment"]


def test_yandex_y0_token_in_list():
    tok = "y0_" + "A" * 50
    data = {"notes": [f"token is {tok}", "no token here"]}
    result = sanitize(data)
    joined = " ".join(result["notes"])
    assert "A" * 50 not in joined


def test_yandex_y0_short_value_left_alone():
    """y0_ with fewer than 20 chars is almost certainly not a real token;
    leave it to avoid false positives on unrelated strings that happen
    to start with 'y0_'.
    """
    data = {"comment": "y0_short"}
    result = sanitize(data)
    assert result["comment"] == "y0_short"


def test_yandex_y0_keeps_first_four_last_three():
    tok = "y0_AgAAAABpg4OLsomeuniquetail456"
    data = {"headers": f"X-Custom: {tok}"}
    result = sanitize(data)
    assert "y0_A" in result["headers"]
    assert "456" in result["headers"]
    assert tok not in result["headers"]
