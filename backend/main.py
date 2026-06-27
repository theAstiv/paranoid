"""FastAPI application entry point."""

import asyncio
import logging
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import API_KEY_FIELDS, VERSION, settings
from backend.db.connection import db
from backend.db.crud import delete_config_value, get_config_value
from backend.db.seed import load_all_seeds
from backend.routes.analyze import router as analyze_router
from backend.routes.auth import router as auth_router
from backend.routes.config import router as config_router
from backend.routes.export import router as export_router
from backend.routes.models import router as models_router
from backend.routes.projects import router as projects_router
from backend.routes.sources import router as sources_router
from backend.routes.threats import router as threats_router
from backend.security.csrf import CSRFMiddleware, parse_allowed_origins
from backend.security.headers import SecurityHeadersMiddleware
from backend.security.source_key import PATDecryptionError


# Configure logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def _bootstrap_admin_if_needed() -> None:
    """Create the initial admin user when the users table is empty.

    Guards:
    - Runs only if user_count() == 0 (no users in DB yet).
    - If PARANOID_ADMIN_PASSWORD is set, uses that password; otherwise
      generates a random password and logs it once with a rotate reminder.
    - Never overwrites an existing user on subsequent restarts.
    """
    from backend.auth.passwords import hash_password
    from backend.db.crud_auth import create_user, user_count

    if await user_count() > 0:
        return

    password = settings.paranoid_admin_password or secrets.token_urlsafe(16)
    if not settings.paranoid_admin_password:
        logger.warning(
            f"PARANOID_ADMIN_PASSWORD not set — generated admin password: {password!r}. "
            "Rotate this via Settings UI after first login."
        )

    await create_user(
        username="admin",
        email="admin@paranoid.local",
        password_hash=hash_password(password),
        display_name="Administrator",
        is_admin=True,
    )
    logger.info("Created initial admin user (username: admin)")


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
                f"Decryption failed for DB config key {key!r} — "
                "leaving field unset. Re-enter the credential in Settings."
            )
            try:
                await delete_config_value(key)
                logger.info(f"Removed stale ciphertext for {key!r} from config table.")
            except Exception as del_exc:
                logger.warning(f"Could not remove stale ciphertext for {key!r}: {del_exc}")
            continue
        if stored:
            setattr(settings, key, stored)
            logger.info(f"Loaded {key} from DB (env unset).")

    # Load seed patterns
    await load_all_seeds()

    # Bootstrap the initial admin user (runs only when users table is empty).
    await _bootstrap_admin_if_needed()

    # Clean up expired / revoked sessions from previous runs.
    from backend.db.crud_auth import cleanup_expired_sessions

    await cleanup_expired_sessions()

    # Warn loudly when authentication is disabled so operators are aware.
    if not settings.paranoid_require_auth:
        logger.warning(
            "PARANOID_REQUIRE_AUTH is not set — authentication is DISABLED. "
            "All requests are treated as instance admin. "
            "Set PARANOID_REQUIRE_AUTH=true to enforce login."
        )

    # Background task: clean up sessions every 24 h.
    async def _session_gc_loop() -> None:
        while True:
            await asyncio.sleep(86_400)
            try:
                await cleanup_expired_sessions()
                logger.debug("Session GC completed")
            except Exception as exc:
                logger.warning(f"Session GC error: {exc}")

    _gc_task = asyncio.create_task(_session_gc_loop())

    yield

    _gc_task.cancel()
    try:
        await _gc_task
    except asyncio.CancelledError:
        pass

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
# so we add security headers first, CSRF second, and CORS last — CORS runs on
# the way out of every response (including CSRF 403s), keeping cross-origin
# errors visible as structured JSON rather than blank "CORS error" messages.

# Security headers — injected on every response regardless of status code.
app.add_middleware(SecurityHeadersMiddleware)

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
app.include_router(auth_router, prefix="/api")
app.include_router(analyze_router, prefix="/api")
app.include_router(models_router, prefix="/api")
app.include_router(threats_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(sources_router, prefix="/api")
app.include_router(projects_router, prefix="/api")


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


# Mount frontend static files.
# Two-tier strategy:
#   /app/assets/*  → content-hashed filenames, cache forever (immutable)
#   /app           → index.html with Cache-Control: no-cache so browsers always
#                    revalidate after a deploy. Without this, a stale index.html
#                    references old chunk hashes that no longer exist on the server
#                    and Vite's dynamic import fails with "Failed to fetch
#                    dynamically imported module".
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    # Serve content-hashed assets with long-lived cache
    app.mount(
        "/app/assets",
        StaticFiles(directory=str(frontend_dist / "assets")),
        name="app-assets",
    )

    # Serve index.html with no-cache for all /app and /app/* routes so the
    # browser always revalidates after a deploy.
    # Two routes are needed:
    #   /app          — bare entry point (no trailing slash, path param is "")
    #   /app/{...}    — all nested SPA routes
    # A single {full_path:path} pattern only matches when there IS a path
    # segment after /app/, so /app itself (empty suffix) falls through to a 404
    # without the explicit second route.
    _index_response_kwargs = {
        "path": str(frontend_dist / "index.html"),
        "headers": {"Cache-Control": "no-cache, no-store, must-revalidate"},
    }

    @app.get("/app", include_in_schema=False)
    async def serve_spa_root(request: Request) -> FileResponse:
        return FileResponse(**_index_response_kwargs)

    @app.get("/app/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str, request: Request) -> FileResponse:
        return FileResponse(**_index_response_kwargs)

    logger.info(f"Serving frontend from {frontend_dist}")
else:
    logger.warning(f"Frontend dist not found at {frontend_dist}")
