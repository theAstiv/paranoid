"""Shared utilities for route handlers."""

from fastapi import HTTPException

from backend.config import settings
from backend.providers.base import LLMProvider, create_provider


def get_api_key(provider_type: str) -> str | None:
    """Return the API key for the given provider, or None if not needed."""
    if provider_type == "anthropic":
        return settings.anthropic_api_key or None
    if provider_type == "openai":
        return settings.openai_api_key or None
    return None  # ollama needs no key


def resolve_provider(provider_name: str | None) -> tuple[str, str]:
    """Return (provider_type, model) resolving None to settings defaults."""
    ptype = provider_name or settings.default_provider
    model = settings.default_model
    return ptype, model


def build_provider_from_record(record: dict) -> LLMProvider:
    """Construct an LLMProvider from a threat-model DB record.

    Raises HTTPException(422) if the provider cannot be created (invalid type or
    missing credentials). Centralizes the provider-resolution boilerplate used by
    every pipeline-triggering route.
    """
    provider_type = record.get("provider") or settings.default_provider
    model_str = record.get("model") or settings.default_model
    api_key = get_api_key(provider_type)
    base_url = settings.ollama_base_url if provider_type == "ollama" else None

    try:
        return create_provider(
            provider_type=provider_type,
            model=model_str,
            api_key=api_key,
            base_url=base_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
