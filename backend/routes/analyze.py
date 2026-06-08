"""Pre-flight analysis route — POST /api/analyze/

Runs description + assumptions gap analysis without requiring a threat model to
exist. Designed for the wizard, which needs to give feedback before the user
commits to a full pipeline run.
"""

import logging

from fastapi import APIRouter, Depends

from backend.config import settings
from backend.models.api import AnalyzeBundleRequest, AnalyzeBundleResponse
from backend.pipeline.pre_flight import analyze_bundle
from backend.providers import create_provider
from backend.security.rate_limit import analyze_rate_limit


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analyze", tags=["analyze"])


@router.post("/", response_model=AnalyzeBundleResponse)
async def analyze_description_and_assumptions(
    req: AnalyzeBundleRequest,
    _rate: None = Depends(analyze_rate_limit),
) -> AnalyzeBundleResponse:
    """Run pre-flight gap analysis on a description + assumptions bundle.

    Uses the system's configured default provider. Does NOT require a threat
    model to exist — intended for the wizard so users can improve their input
    before committing to a full pipeline run.

    Returns gap lists and is_sufficient flags for both description and
    assumptions independently so the frontend can display them on separate
    wizard steps.
    """
    provider = create_provider(
        provider_type=settings.default_provider,
        model=settings.default_model,
        api_key=(
            settings.anthropic_api_key
            if settings.default_provider == "anthropic"
            else settings.openai_api_key
            if settings.default_provider == "openai"
            else None
        ),
        base_url=(settings.ollama_base_url if settings.default_provider == "ollama" else None),
    )

    async with provider:
        return await analyze_bundle(
            description=req.description,
            assumptions=req.assumptions,
            provider=provider,
        )
