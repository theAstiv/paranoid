"""Serialization utilities for converting Pydantic models to JSON-safe dicts.

Used by SSE event streaming (runner), console rendering, and FastAPI routes.
"""

from typing import Any

from pydantic import BaseModel


def serialize_event_data(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Recursively convert Pydantic models in event data to JSON-safe dicts.

    Handles:
    - Top-level BaseModel values
    - Lists containing BaseModel items
    - Nested dicts containing BaseModel values
    - None values (passed through safely)
    """
    if data is None:
        return None
    return {key: _serialize_value(value) for key, value in data.items()}


def _serialize_value(value: Any) -> Any:
    """Convert a single value, recursing into containers."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    return value
