"""Tests for backend/providers/_recovery.py (shape recovery shared by the
Bedrock and direct Anthropic providers)."""

import json

import pytest
from pydantic import BaseModel, ValidationError

from backend.providers._recovery import coerce_tool_input, describe_validation_errors


class _Flows(BaseModel):
    data_flows: list[str]
    trust_boundaries: list[str]


SCHEMA = _Flows.model_json_schema()


def test_envelope_as_dict_is_unwrapped():
    data = {"input": {"data_flows": ["a"], "trust_boundaries": []}}
    assert coerce_tool_input(data, SCHEMA, model="m") == data["input"]


def test_envelope_as_json_string_is_unwrapped():
    """DeepSeek (10-11 bench): {'data': '{"data_flows": ...}'}."""
    inner = {"data_flows": ["a"], "trust_boundaries": ["b"]}
    assert coerce_tool_input({"data": json.dumps(inner)}, SCHEMA, model="m") == inner


def test_envelope_missing_a_required_field_is_left_alone():
    data = {"data": {"data_flows": ["a"]}}
    assert coerce_tool_input(data, SCHEMA, model="m") == data


def test_single_known_property_is_not_treated_as_an_envelope():
    class _One(BaseModel):
        payload: dict

    schema = _One.model_json_schema()
    data = {"payload": {"payload": {}}}
    assert coerce_tool_input(data, schema, model="m") == data


def test_envelope_then_string_fields_are_both_recovered():
    data = {"input": {"data_flows": '["a"]', "trust_boundaries": "[]"}}
    assert coerce_tool_input(data, SCHEMA, model="m") == {
        "data_flows": ["a"],
        "trust_boundaries": [],
    }


def test_describe_validation_errors_uses_paths_and_schema_messages_only():
    with pytest.raises(ValidationError) as info:
        _Flows.model_validate({"data_flows": [1, "secret-value"], "trust_boundaries": 7})
    text = describe_validation_errors(info.value)
    assert "- data_flows.0: Input should be a valid string" in text
    assert "- trust_boundaries: Input should be a valid list" in text
    assert "secret-value" not in text


def test_describe_validation_errors_caps_the_list():
    class _Many(BaseModel):
        items: list[int]

    with pytest.raises(ValidationError) as info:
        _Many.model_validate({"items": ["x"] * 12})
    text = describe_validation_errors(info.value)
    assert text.count("\n- items.") == 4
    assert "...and 7 more" in text
