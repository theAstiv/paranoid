"""Config read/write endpoint — returns and optionally updates a safe subset of settings."""

from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.config import VERSION, settings


router = APIRouter(prefix="/config", tags=["config"])


def _config_payload() -> dict:
    """Serialise the current settings into the public config shape."""
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
        # Indicates whether callers need X-Config-Secret to use PATCH /config.
        # Never exposes the secret value itself.
        "config_secret_required": bool(settings.config_secret),
    }


@router.get("/")
async def get_config() -> JSONResponse:
    """Return current application configuration.

    API keys are never included in the response.
    """
    return JSONResponse(content=_config_payload())


class UpdateConfigRequest(BaseModel):
    """Mutable runtime settings.  Changes are applied immediately but NOT persisted
    to disk — they reset to env-var / .env values on backend restart."""

    default_provider: Literal["anthropic", "openai", "ollama"] | None = None
    model: str | None = Field(None, description="Main model identifier")
    fast_model: str | None = Field(None, description="Fast model for extraction and enrichment")
    default_iterations: int | None = Field(None, ge=1, le=15)
    similarity_threshold: float | None = Field(None, ge=0.0, le=1.0)
    ollama_base_url: str | None = None


@router.patch("/")
async def update_config(
    body: UpdateConfigRequest,
    x_config_secret: str | None = Header(default=None),
) -> JSONResponse:
    """Mutate a subset of runtime settings without restarting the backend.

    Changes are in-memory only — they reset on next restart.  API keys cannot
    be changed through this endpoint.

    Security: This endpoint is unauthenticated by default, suitable for
    local and single-user Docker deployments.  To restrict access, set the
    CONFIG_SECRET environment variable.  Callers must then supply a matching
    X-Config-Secret header; requests without it receive 403.  This is a
    lightweight guard until v2 introduces proper JWT auth.
    """
    if settings.config_secret and x_config_secret != settings.config_secret:
        raise HTTPException(
            status_code=403,
            detail="X-Config-Secret header is missing or incorrect.",
        )
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

    return JSONResponse(content=_config_payload())
