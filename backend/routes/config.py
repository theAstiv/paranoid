"""Config read/write endpoint — returns and optionally updates a safe subset of settings."""

import logging
import os
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr

from backend.config import API_KEY_FIELDS, VERSION, settings
from backend.db.crud import (
    delete_config_value,
    get_config_value,
    set_config_value,
)
from backend.providers.healthcheck import (
    ProbeResult,
    ping_anthropic,
    ping_ollama,
    ping_openai,
    rate_limit_check,
)
from backend.routes._helpers import get_api_key
from backend.security.source_key import PATDecryptionError


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])


# Shared across UpdateConfigRequest.default_provider and
# TestProviderRequest.provider — keep as one source of truth so a new
# provider lands in both places at once.
ProviderName = Literal["anthropic", "openai", "ollama"]


async def _api_key_source(provider: str) -> str | None:
    """Return ``"env"``, ``"db"``, or ``None`` for a provider's current key source."""
    env_name, db_key = API_KEY_FIELDS[provider]
    if os.environ.get(env_name, "").strip():
        return "env"
    try:
        value = await get_config_value(db_key)
    except PATDecryptionError:
        # Stored ciphertext cannot be decrypted under the active key. Treat
        # as unset so the UI surfaces the first-run state rather than a
        # silent half-broken config.
        logger.warning(f"Decryption failed for config key {db_key!r} — returning unset.")
        return None
    return "db" if value else None


async def _is_first_run() -> bool:
    """True when the default provider has no usable API key (live-read).

    Ollama is exempt — it has no API key concept and its base URL may point
    at a server not yet running. Users can verify via test-connection.
    """
    if settings.default_provider == "ollama":
        return False
    env_name, db_key = API_KEY_FIELDS[settings.default_provider]
    if os.environ.get(env_name, "").strip():
        return False
    try:
        value = await get_config_value(db_key)
    except PATDecryptionError:
        return True
    return not value


async def _config_payload() -> dict:
    """Serialise the current settings into the public config shape."""
    anthropic_source = await _api_key_source("anthropic")
    openai_source = await _api_key_source("openai")
    return {
        "version": VERSION,
        "default_provider": settings.default_provider,
        # Kept for backwards-compat with older frontend code that reads `provider`
        "provider": settings.default_provider,
        "model": settings.default_model,
        "fast_model": settings.fast_model,
        "default_iterations": settings.default_iterations,
        "max_iteration_count": settings.max_iteration_count,
        "min_iteration_count": settings.min_iteration_count,
        "ollama_base_url": settings.ollama_base_url,
        "log_level": settings.log_level,
        "similarity_threshold": settings.similarity_threshold,
        # Presence + source of each provider key (never the value itself).
        "anthropic_api_key_set": anthropic_source is not None,
        "anthropic_api_key_source": anthropic_source,
        "openai_api_key_set": openai_source is not None,
        "openai_api_key_source": openai_source,
        "first_run": await _is_first_run(),
        # Indicates whether callers need X-Config-Secret to use PATCH /config.
        # Never exposes the secret value itself.
        "config_secret_required": bool(settings.config_secret),
    }


@router.get("/")
async def get_config() -> JSONResponse:
    """Return current application configuration.

    API keys are never included in the response.
    """
    return JSONResponse(content=await _config_payload())


class UpdateConfigRequest(BaseModel):
    """Mutable runtime settings. Non-key fields are in-memory only (reset on
    restart). API keys are persisted to the ``config`` DB table (encrypted)
    and survive restarts.

    Field semantics for key fields (``anthropic_api_key`` / ``openai_api_key``):
    - Omitted from body → no change.
    - Explicit ``null`` → clear the stored value.
    - Non-empty string → upsert.
    - Empty string ``""`` → rejected with 400.
    """

    default_provider: ProviderName | None = None
    model: str | None = Field(None, description="Main model identifier")
    fast_model: str | None = Field(None, description="Fast model for extraction and enrichment")
    default_iterations: int | None = Field(None, ge=1, le=15)
    similarity_threshold: float | None = Field(None, ge=0.0, le=1.0)
    ollama_base_url: str | None = None
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None


async def _apply_key_update(provider: str, secret: SecretStr | None) -> None:
    """Apply a PATCH to one API-key field. Assumes caller already verified the
    field was explicitly present in the request body."""
    env_name, key = API_KEY_FIELDS[provider]
    if os.environ.get(env_name, "").strip():
        raise HTTPException(
            status_code=400,
            detail=f"{key} is managed by environment variable {env_name}",
        )
    if secret is None:
        await delete_config_value(key)
        setattr(settings, key, "")
        return
    # Strip so a user who pastes "sk-ant-xyz\n" (or pure whitespace) gets
    # a clean stored value; whitespace-only is semantically empty.
    raw = secret.get_secret_value().strip()
    if raw == "":
        raise HTTPException(
            status_code=400,
            detail=f"Use null to clear {key}, or omit the field for no change.",
        )
    await set_config_value(key, raw, encrypted=True)
    setattr(settings, key, raw)


@router.patch("/")
async def update_config(
    body: UpdateConfigRequest,
    x_config_secret: str | None = Header(default=None),
) -> JSONResponse:
    """Mutate a subset of runtime settings without restarting the backend.

    Non-key fields are in-memory only (they reset on next restart). API keys
    are persisted to the ``config`` table (encrypted) and survive restarts.

    Security: This endpoint is unauthenticated by default, suitable for local
    and single-user Docker deployments. To restrict access, set the
    CONFIG_SECRET environment variable. Callers must then supply a matching
    X-Config-Secret header; requests without it receive 403.

    Cross-origin write protection is enforced by the CSRFMiddleware — see
    ``ALLOWED_ORIGINS``.
    """
    if settings.config_secret and x_config_secret != settings.config_secret:
        raise HTTPException(
            status_code=403,
            detail="X-Config-Secret header is missing or incorrect.",
        )
    # model_fields_set — not `is not None` — because key fields need three
    # distinct outcomes: omitted (no change), explicit null (clear), and
    # non-empty string (upsert). The is-not-None pattern used for other
    # fields collapses omitted and null into one branch.
    fields_set = body.model_fields_set

    if body.default_provider is not None:
        settings.default_provider = body.default_provider  # type: ignore[assignment]
    if body.model is not None:
        settings.default_model = body.model
    if body.fast_model is not None:
        settings.fast_model = body.fast_model
    if body.default_iterations is not None:
        settings.default_iterations = body.default_iterations
    if body.similarity_threshold is not None:
        settings.similarity_threshold = body.similarity_threshold
    if body.ollama_base_url is not None:
        settings.ollama_base_url = body.ollama_base_url

    if "anthropic_api_key" in fields_set:
        await _apply_key_update("anthropic", body.anthropic_api_key)
    if "openai_api_key" in fields_set:
        await _apply_key_update("openai", body.openai_api_key)

    return JSONResponse(content=await _config_payload())


class TestProviderRequest(BaseModel):
    """One-shot provider liveness probe. Body key overrides stored key."""

    provider: ProviderName
    api_key: SecretStr | None = None
    model: str | None = None
    # Only used when provider == "ollama"; falls back to settings if absent.
    ollama_base_url: str | None = None


def _resolve_probe_key(provider: str, body_key: SecretStr | None) -> str:
    """Body > settings (env → DB hydrated at boot + kept live by PATCH).

    Returns an empty string when no key is available so callers can do a
    single ``if not key`` check. Ollama is exempt and never reaches here.
    """
    if body_key is not None:
        return body_key.get_secret_value().strip()
    return (get_api_key(provider) or "").strip()


@router.post("/test-provider")
async def test_provider(body: TestProviderRequest) -> JSONResponse:
    """Liveness probe for a provider. Always returns 200 with ``ok`` bool
    (unless rate-limited → 429). Never logs or echoes the supplied key.
    """
    retry_after = await rate_limit_check()
    if retry_after is not None:
        retry_s = max(1, int(retry_after))
        raise HTTPException(
            status_code=429,
            detail=f"Too many test-connection requests. Try again in {retry_s}s.",
        )

    if body.provider == "ollama":
        base_url = body.ollama_base_url or settings.ollama_base_url
        result = await ping_ollama(base_url)
    else:
        key = _resolve_probe_key(body.provider, body.api_key)
        if not key:
            result = ProbeResult(
                ok=False,
                latency_ms=0,
                error="config_error",
                message=f"No {body.provider.title()} API key available (body, env, or DB).",
            )
        elif body.provider == "anthropic":
            model = body.model or settings.default_model
            result = await ping_anthropic(key, model)
        else:  # openai
            result = await ping_openai(key, body.model)

    return JSONResponse(
        content={
            "ok": result.ok,
            "latency_ms": result.latency_ms,
            "provider": body.provider,
            "error": result.error,
            "message": result.message,
        }
    )
