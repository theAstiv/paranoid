"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings


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

    yield

    logger.info("Shutting down Paranoid application")


# Create FastAPI application
app = FastAPI(
    title="Paranoid",
    description="Open-source, self-hosted, iterative threat modeling powered by LLMs",
    version="1.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
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
            "version": "1.1.0",
            "provider": settings.default_provider,
            "model": settings.default_model,
        }
    )


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
