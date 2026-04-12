"""Shared utilities for route handlers."""

from backend.config import settings


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
