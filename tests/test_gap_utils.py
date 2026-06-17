"""Tests for backend/db/gap_utils.py.

Covers all meaningful branches of decode_gap_summaries:
- None / empty input returns []
- Valid JSON list is decoded correctly
- Non-list JSON returns []
- Malformed JSON returns []
- Items are coerced to str
"""

import json

from backend.db.gap_utils import decode_gap_summaries


def test_none_returns_empty_list():
    assert decode_gap_summaries(None) == []


def test_empty_string_returns_empty_list():
    assert decode_gap_summaries("") == []


def test_valid_json_list_is_decoded():
    raw = json.dumps(["gap A", "gap B", "gap C"])
    result = decode_gap_summaries(raw)
    assert result == ["gap A", "gap B", "gap C"]


def test_single_item_list():
    raw = json.dumps(["only one gap"])
    assert decode_gap_summaries(raw) == ["only one gap"]


def test_non_list_json_returns_empty():
    """A JSON object at the top level is not a valid gap list."""
    raw = json.dumps({"key": "value"})
    assert decode_gap_summaries(raw) == []


def test_json_string_scalar_returns_empty():
    """A bare JSON string is not a list."""
    raw = json.dumps("just a string")
    assert decode_gap_summaries(raw) == []


def test_malformed_json_returns_empty():
    assert decode_gap_summaries("{not valid json}") == []


def test_items_are_coerced_to_str():
    """Integer items in the JSON list must be coerced to str."""
    raw = json.dumps([1, 2, 3])
    result = decode_gap_summaries(raw)
    assert result == ["1", "2", "3"]


def test_empty_json_list():
    assert decode_gap_summaries("[]") == []
