"""Recovery for structured output that arrives in a shape the schema rejects.

Shared by the Bedrock (Converse tool use) and direct Anthropic (JSON text)
providers, whose output isn't schema-constrained at decode time. OpenAI
Structured Outputs constrains decoding to the schema, so it doesn't need this.
Ollama's `format="json"` only guarantees valid JSON, not the schema; it has its
own single repair pass instead. Every fix here is deterministic and conservative: a value is only
reshaped when the result provably matches the schema's required fields, and
anything else is left for normal validation (and the provider's
restate-retry, which uses `describe_validation_errors`).
"""

import json
import logging
from typing import Any

from pydantic import ValidationError


logger = logging.getLogger(__name__)

# Sent as an extra system message when the response fails schema validation
# for a reason more tokens can't fix (a malformed JSON string, a value outside
# an enum, a missing required field). `{problems}` lists field paths and the
# schema's own expectation ("Input should be 'L' or 'H'") — never the model's
# values, so no model output is echoed back into the prompt.
VALIDATION_RESTATE_INSTRUCTION = (
    "Your previous response did not match the schema:\n{problems}\n"
    "Respond again with every required field present, each value one of the allowed "
    "options, and each list or object given as a JSON value, not as a string containing JSON."
)

_MAX_REPORTED_PROBLEMS = 5
_MAX_MESSAGE_CHARS = 120


def coerce_tool_input(data: Any, schema: dict, *, model: str) -> Any:
    """Undo the known malformed-but-recoverable shapes, in order:

    1. an envelope: the whole response nested under one unknown key, as a
       dict or a JSON string (Sonnet 5: `{"input": {"threats": [...]}}`;
       DeepSeek: `{"data": "{\\"data_flows\\": ...}"}`);
    2. the whole response JSON-encoded into one of its own fields (Sonnet 5:
       `gaps` = '{"gaps": [...], "is_sufficient": false}');
    3. top-level list/object fields sent as JSON strings (Claude 5.x).
    """
    if not isinstance(data, dict):
        return data
    result = _unwrap_envelope(data, schema, model=model)
    result = _unwrap_buried_response(result, schema, model=model)
    return _coerce_json_string_fields(result, schema, model=model)


def describe_validation_errors(exc: ValidationError) -> str:
    """One line per problem: dotted field path and the schema's expectation,
    capped so a response with many bad items doesn't blow up the retry prompt."""
    lines = []
    for err in exc.errors()[:_MAX_REPORTED_PROBLEMS]:
        path = ".".join(str(part) for part in err.get("loc", ())) or "(response)"
        message = str(err.get("msg", "invalid"))[:_MAX_MESSAGE_CHARS]
        lines.append(f"- {path}: {message}")
    extra = len(exc.errors()) - _MAX_REPORTED_PROBLEMS
    if extra > 0:
        lines.append(f"- ...and {extra} more")
    return "\n".join(lines) or "- (response): invalid"


def _parse_dict(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _unwrap_envelope(data: dict, schema: dict, *, model: str) -> dict:
    """A single key the schema doesn't define, wrapping (as a dict or a JSON
    string) an object with every required property: the model nested its
    whole answer one level down. Anything less specific is left alone."""
    required = set(schema.get("required", []))
    if not required or len(data) != 1:
        return data
    ((key, value),) = data.items()
    if key in schema.get("properties", {}):
        return data
    inner = _parse_dict(value)
    if inner is not None and required <= inner.keys():
        logger.warning(
            "Model %s wrapped its whole response in an extra %r key - unwrapped before validation",
            model,
            key,
        )
        return dict(inner)
    return data


def _unwrap_buried_response(data: dict, schema: dict, *, model: str) -> dict:
    """Recover a response that was JSON-encoded whole into one of its own fields.

    Seen on Sonnet 5 for the pre-flight description check: `gaps` (schema
    type array) arrived as the string '{"gaps": [...], "is_sufficient":
    false}' - the entire response, not the list. Coercing that field alone
    gets a dict where a list belongs, so it's skipped and validation fails.

    Only unwrapped when the string parses to a dict that contains that same
    field *and* every required property of the schema, so an object field
    that merely looks like JSON is never mistaken for a buried response. The
    decoded keys are merged over the outer ones (the buried copy is the
    complete one); the caller still coerces any remaining string fields.
    """
    required = set(schema.get("required", []))
    if not required:
        return dict(data)
    for field, value in data.items():
        if not isinstance(value, str):
            continue
        parsed = _parse_dict(value)
        if parsed is not None and field in parsed and required <= parsed.keys():
            logger.warning(
                "Model %s returned its whole response JSON-encoded in field %r - unwrapped "
                "before validation",
                model,
                field,
            )
            return {**data, **parsed}
    return dict(data)


def _coerce_json_string_fields(data: dict, schema: dict, *, model: str) -> dict:
    """Parse top-level fields that arrived as a JSON-encoded string instead of
    the list/object the schema asked for.

    Reported on Claude 5.x in the 10-09 Bedrock session: a field like
    "threats" (schema type "array") came back as the string
    '[{"name": ...}, ...]' rather than the decoded list, which fails
    Pydantic validation with "Input should be a valid list". Only top-level
    fields are checked (a nested model's own fields, under a `$ref` or
    `anyOf` with no top-level "type", aren't — today's schemas don't need
    it), and only coerced when the parsed value actually matches the
    expected array/object shape — a field that legitimately holds a
    JSON-looking string is left alone.
    """
    coerced_fields: list[str] = []
    result = dict(data)
    for field, prop_schema in schema.get("properties", {}).items():
        prop_type = prop_schema.get("type")
        if prop_type not in ("array", "object"):
            continue
        value = result.get(field)
        if not isinstance(value, str):
            continue
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            continue
        if prop_type == "array" and not isinstance(parsed, list):
            continue
        if prop_type == "object" and not isinstance(parsed, dict):
            continue
        result[field] = parsed
        coerced_fields.append(field)

    if coerced_fields:
        logger.warning(
            "Model %s returned field(s) %s as a JSON string instead of the schema's "
            "list/object type — coerced before validation",
            model,
            coerced_fields,
        )
    return result
