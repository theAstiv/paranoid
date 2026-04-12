"""Config read endpoint — returns safe subset of application settings."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.config import VERSION, settings

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/")
async def get_config() -> JSONResponse:
    """Return current application configuration.

    API keys are never included in the response.
    """
    return JSONResponse(
        content={
            "version": VERSION,
            "provider": settings.default_provider,
            "model": settings.default_model,
            "default_iterations": settings.default_iterations,
            "max_iteration_count": settings.max_iteration_count,
            "min_iteration_count": settings.min_iteration_count,
            "ollama_base_url": settings.ollama_base_url,
            "log_level": settings.log_level,
            "similarity_threshold": settings.similarity_threshold,
        }
    )
