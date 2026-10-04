"""Shared utilities for route handlers."""

import logging

from fastapi import HTTPException

from backend.config import Settings, settings
from backend.db import crud_comments
from backend.providers.base import LLMProvider, create_provider


logger = logging.getLogger(__name__)


def get_api_key(provider_type: str, settings_obj: Settings | None = None) -> str | None:
    """Return the API key for the given provider, or None if not needed."""
    s = settings_obj or settings
    if provider_type == "anthropic":
        return s.anthropic_api_key or None
    if provider_type == "openai":
        return s.openai_api_key or None
    return None  # ollama / bedrock need no key


def bedrock_kwargs(provider_type: str, settings_obj: Settings | None = None) -> dict:
    """Return region/profile kwargs for create_provider when provider is bedrock.

    Non-bedrock callers spread an empty dict, so this is always safe to pass through.
    """
    s = settings_obj or settings
    if provider_type != "bedrock":
        return {}
    return {"region": s.aws_region, "profile": s.aws_profile}


def anthropic_kwargs(provider_type: str) -> dict:
    """Return the opt-in effort kwarg for create_provider when provider is anthropic.

    Only for the main provider: the fast (Haiku) provider must not get it.
    """
    if provider_type != "anthropic" or not settings.anthropic_effort:
        return {}
    return {"effort": settings.anthropic_effort}


def resolve_provider(
    provider_name: str | None,
    model_name: str | None = None,
    project: dict | None = None,
) -> tuple[str, str]:
    """Return (provider_type, model), resolving explicit > project default > global settings."""
    project = project or {}
    ptype = provider_name or project.get("default_provider") or settings.default_provider
    model = model_name or project.get("default_model") or settings.default_model
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
            **bedrock_kwargs(provider_type),
            **anthropic_kwargs(provider_type),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


FAST_MODEL_FIELDS: dict[str, str] = {
    "anthropic": "fast_model",
    "openai": "fast_model_openai",
    "bedrock": "fast_model_bedrock",
    "ollama": "fast_model_ollama",
}


def _fast_model_for(provider_type: str, settings_obj: Settings | None = None) -> str:
    """Return the configured fast model for a provider type, or "" if none."""
    s = settings_obj or settings
    field = FAST_MODEL_FIELDS.get(provider_type)
    return getattr(s, field) if field else ""


def build_fast_provider(record: dict, settings_obj: Settings | None = None) -> LLMProvider | None:
    """Build an optional fast (cheap) provider for extraction and enrichment steps.

    The single shared builder for both the web routes (default ``settings_obj``,
    the global singleton) and the CLI (passes its own merged ``Settings``
    instance — env + .env + CLI config file) — previously duplicated between
    this module and ``cli/commands/run.py``.

    Returns a provider of the same type as the resolved main provider, built
    from that provider's configured fast model (``FAST_MODEL`` /
    ``FAST_MODEL_OPENAI`` / ``FAST_MODEL_BEDROCK`` / ``FAST_MODEL_OLLAMA``),
    when:
    - A fast model is configured for the resolved provider type
    - The fast model differs from the main model (so we don't create a duplicate)

    Never forwards ``anthropic_kwargs()`` (the opt-in ``effort`` setting) —
    that applies to the main model only, never the fast model.

    Returns None in all other cases — callers pass None directly to
    ``run_pipeline_for_model(fast_provider=...)`` which then falls back to the
    main provider transparently.
    """
    s = settings_obj or settings
    provider_type = record.get("provider") or s.default_provider
    fast_model = _fast_model_for(provider_type, s)
    if not fast_model:
        return None

    main_model = record.get("model") or s.default_model
    if fast_model == main_model:
        return None  # identical — no benefit in creating a second instance

    api_key = get_api_key(provider_type, s)
    base_url = s.ollama_base_url if provider_type == "ollama" else None
    try:
        return create_provider(
            provider_type=provider_type,
            model=fast_model,
            api_key=api_key,
            base_url=base_url,
            **bedrock_kwargs(provider_type, s),
        )
    except Exception:
        # Broad on purpose: this path is always optional (callers fall back
        # to the main provider on None), so any construction failure here —
        # not just create_provider's own ValueError, but e.g. a Bedrock
        # client error that isn't wrapped as one — must never take down the
        # run. Mirrors the old CLI-only builder's bare `except Exception`.
        logger.warning(
            "Could not create fast provider for model %s — falling back", fast_model, exc_info=True
        )
        return None


async def model_assignee_ids(model_id: str, exclude: str | None = None) -> set[str]:
    """Return assignee user ids for a model, minus the actor who triggered the event.

    Used by the Phase 5 notification instrumentation in routes/models.py and
    routes/threats.py — best-effort, never raises, so a lookup failure just
    means no notifications go out rather than breaking the caller's response.
    """
    try:
        assignees = await crud_comments.list_assignees(model_id)
    except Exception as exc:
        logger.warning(f"Failed to list assignees for model {model_id}: {exc}")
        return set()
    return {a["user_id"] for a in assignees if a["user_id"] != exclude}
