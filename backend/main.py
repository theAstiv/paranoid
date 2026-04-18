"""FastAPI application entry point."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import API_KEY_FIELDS, VERSION, settings
from backend.db.connection import db
from backend.db.crud import get_config_value
from backend.db.seed import load_all_seeds
from backend.routes.config import router as config_router
from backend.routes.export import router as export_router
from backend.routes.models import router as models_router
from backend.routes.threats import router as threats_router
from backend.security.csrf import CSRFMiddleware, parse_allowed_origins
from backend.security.source_key import PATDecryptionError


# Configure logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context manager."""
    logger.info("Starting Paranoid application")
    logger.info(f"Database path: {settings.db_path}")
    logger.info(f"Default provider: {settings.default_provider}")
    logger.info(f"Default model: {settings.default_model}")

    # Ensure data directory exists
    data_dir = Path(settings.db_path).parent
    data_dir.mkdir(parents=True, exist_ok=True)

    # Initialize database connection and schema
    await db.initialize(settings.db_path)

    # Hydrate API keys from the config table into settings, but only for
    # fields NOT already sourced from the environment — env wins. A
    # decryption failure (rotated CONFIG_SECRET, corrupt row) is logged and
    # the field is left empty so the user sees the first-run banner rather
    # than a silent half-broken state.
    for env_name, key in API_KEY_FIELDS.values():
        if os.environ.get(env_name, "").strip():
            continue
        try:
            stored = await get_config_value(key)
        except PATDecryptionError:
            logger.warning(
                f"Decryption failed for DB config key {key!r} — leaving "
                "field unset. Re-enter the credential in Settings; the "
                "stale ciphertext will be overwritten on save."
            )
            continue
        if stored:
            setattr(settings, key, stored)
            logger.info(f"Loaded {key} from DB (env unset).")

    # Load seed patterns
    await load_all_seeds()

    yield

    # Close database connection
    await db.close()
    logger.info("Shutting down Paranoid application")


# Create FastAPI application
app = FastAPI(
    title="Paranoid",
    description="Open-source, self-hosted, iterative threat modeling powered by LLMs",
    version=VERSION,
    lifespan=lifespan,
)

# Middleware stack. FastAPI/Starlette runs the LAST-added middleware outermost,
# so we add CSRF first and CORS second — CORS runs on the way out of every
# response, including a CSRF 403, which keeps cross-origin errors visible as
# structured JSON (not a blank "CORS error") in the browser console.

# CSRF — rejects mutating requests whose Origin/Referer is not in
# ALLOWED_ORIGINS. Pure ASGI so it doesn't buffer SSE bodies. Validation
# errors surface at startup rather than on the first blocked request.
_allowed_origins = parse_allowed_origins(settings.allowed_origins)
app.add_middleware(CSRFMiddleware, allowed_origins=_allowed_origins)
if not _allowed_origins:
    logger.warning(
        "ALLOWED_ORIGINS is empty — CSRF protection is DISABLED. "
        "Safe only for CLI-only / non-browser deployments."
    )

# CORS — configure via CORS_ORIGINS env var: "*" (default) or comma-separated
# origins, e.g. CORS_ORIGINS="https://app.example.com,https://staging.example.com"
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse(
        content={
            "status": "healthy",
            "version": VERSION,
            "provider": settings.default_provider,
            "model": settings.default_model,
        }
    )


# API routers
app.include_router(models_router, prefix="/api")
app.include_router(threats_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(config_router, prefix="/api")


@app.get("/")
async def root() -> JSONResponse:
    """Root endpoint."""
    return JSONResponse(
        content={
            "message": "Paranoid - Open-source iterative threat modeling",
            "docs": "/docs",
            "health": "/health",
        }
    )


# Mount frontend static files (will be added in Phase 1.6)
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/app", StaticFiles(directory=str(frontend_dist), html=True), name="app")
    logger.info(f"Serving frontend from {frontend_dist}")
else:
    logger.warning(f"Frontend dist not found at {frontend_dist}")
