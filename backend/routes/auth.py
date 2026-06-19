"""Authentication routes.

Covers:
    POST /api/auth/register     — create a new user account
    POST /api/auth/login        — issue JWT + refresh token (rate-limited)
    POST /api/auth/refresh      — rotate refresh token + reuse detection (rate-limited)
    POST /api/auth/logout       — revoke current refresh session
    GET  /api/auth/me           — current user profile
    PATCH /api/auth/me          — update display_name / password

    POST   /api/auth/tokens     — create PAT (returns raw token once)
    GET    /api/auth/tokens     — list PATs (metadata only, no hashes)
    DELETE /api/auth/tokens/{token_id} — revoke a PAT

Refresh tokens travel as:
  - Browser: HttpOnly, SameSite=Strict, Secure cookie on Path=/api/auth/
  - CLI / body fallback: also returned in JSON body as "refresh_token"

When PARANOID_REQUIRE_AUTH=false, all routes still work — users can register and
manage tokens. The auth guard itself (dependencies.py) is what becomes a no-op.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from backend.auth.dependencies import get_current_user
from backend.auth.passwords import hash_password, verify_password
from backend.auth.tokens import (
    create_access_token,
    create_pat,
    create_refresh_token,
    parse_refresh_token_jti,
)
from backend.db.connection import db
from backend.db.crud import now_iso
from backend.db.crud_auth import create_pat as db_create_pat
from backend.db.crud_auth import (
    create_session,
    create_user,
    delete_pat,
    get_pat_by_id,
    get_session,
    get_user_by_email,
    get_user_by_id,
    get_user_by_username,
    list_pats,
    list_users,
    revoke_all_user_sessions,
    revoke_session,
    update_last_login,
)
from backend.security.rate_limit import auth_rate_limit


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Cookie name for the HttpOnly refresh token
_REFRESH_COOKIE = "paranoid_refresh"


# ---------------------------------------------------------------------------
# Request / Response models (auth-specific; api.py is for pipeline models)
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$")
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)

    @field_validator("email")
    @classmethod
    def email_must_contain_at(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Invalid email address")
        return v.lower().strip()

    @field_validator("username")
    @classmethod
    def username_strip(cls, v: str) -> str:
        return v.strip()


class LoginRequest(BaseModel):
    username: str
    password: str


class UpdateMeRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    current_password: str | None = None


class CreatePATRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


def _user_response(user: dict[str, Any]) -> dict[str, Any]:
    """Strip password_hash before returning user data to clients."""
    return {k: v for k, v in user.items() if k != "password_hash"}


def _set_refresh_cookie(response: Response, raw_token: str, expires_days: int = 7) -> None:
    """Attach the refresh token as an HttpOnly cookie."""
    max_age = expires_days * 86400
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=raw_token,
        httponly=True,
        samesite="strict",
        secure=True,  # Browsers special-case localhost; non-TLS prod must document this
        path="/api/auth/",
        max_age=max_age,
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Remove the refresh cookie."""
    response.delete_cookie(key=_REFRESH_COOKIE, path="/api/auth/")


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


@router.post("/register", status_code=201)
async def register(body: RegisterRequest) -> JSONResponse:
    """Create a new user account.

    Open registration — any caller can create an account.  The first user
    bootstrapped by main.py is admin; subsequent users are non-admin by default.
    """
    if await get_user_by_username(body.username):
        raise HTTPException(status_code=409, detail="Username already taken")
    if await get_user_by_email(body.email):
        raise HTTPException(status_code=409, detail="Email already registered")

    try:
        user = await create_user(
            username=body.username,
            email=body.email,
            password_hash=hash_password(body.password),
            display_name=body.display_name,
            is_admin=False,
        )
    except aiosqlite.IntegrityError as exc:
        logger.warning(f"Duplicate key during registration for {body.username!r}: {exc}")
        raise HTTPException(status_code=409, detail="Username or email already registered")
    except Exception as exc:
        logger.error(f"Failed to create user {body.username!r}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to create user")

    return JSONResponse(status_code=201, content=_user_response(user))


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    _rl: None = Depends(auth_rate_limit),
) -> dict[str, Any]:
    """Authenticate with username + password.

    Returns access_token (15 min JWT) and refresh_token (7-day).
    Refresh token also set as HttpOnly cookie for browser clients.
    """
    user = await get_user_by_username(body.username)
    # Constant-time: always verify even if user not found to prevent user enumeration.
    # We use a dummy hash when user is None.
    _dummy_hash = "$argon2id$v=19$m=65536,t=3,p=4$dGVzdA$dGVzdA"
    stored_hash = user["password_hash"] if user else _dummy_hash
    valid = verify_password(body.password, stored_hash)

    if not user or not valid or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(
        user_id=user["id"],
        username=user["username"],
        is_admin=bool(user["is_admin"]),
    )
    jti, raw_refresh = create_refresh_token()
    expires_at = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    await create_session(jti=jti, user_id=user["id"], expires_days=7)
    await update_last_login(user["id"])

    _set_refresh_cookie(response, raw_refresh)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": raw_refresh,  # also in body for CLI
        "expires_at": expires_at,
        "user": _user_response(user),
    }


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


@router.post("/refresh")
async def refresh_token(
    request: Request,
    response: Response,
    _rl: None = Depends(auth_rate_limit),
) -> dict[str, Any]:
    """Rotate the refresh token and issue a new access token.

    Accepts the refresh token from:
    1. The HttpOnly cookie ``paranoid_refresh`` (browser clients)
    2. JSON body ``{ "refresh_token": "..." }`` (CLI / non-browser)

    Reuse detection: if a revoked refresh token is presented, ALL sessions for
    that user are immediately killed (stolen-token family kill).
    """
    # Extract raw refresh token from cookie → body
    raw_token = request.cookies.get(_REFRESH_COOKIE)
    if not raw_token:
        try:
            body = await request.json()
            raw_token = body.get("refresh_token")
        except Exception:
            raw_token = None

    if not raw_token:
        raise HTTPException(status_code=401, detail="Refresh token required")

    jti = parse_refresh_token_jti(raw_token)
    if not jti:
        raise HTTPException(status_code=401, detail="Malformed refresh token")

    session = await get_session(jti)
    if session is None:
        # Unknown jti — could be a forged or very stale token; reject silently.
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if session["revoked_at"] is not None:
        # Reuse detected: revoke the whole user session family.
        logger.warning(
            f"Refresh token reuse detected for user {session['user_id']!r} — revoking all sessions."
        )
        await revoke_all_user_sessions(session["user_id"])
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Token reuse detected — please log in again")

    # Check expiry
    exp = datetime.fromisoformat(session["expires_at"])
    if datetime.now(UTC) > exp:
        await revoke_session(jti)
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = await get_user_by_id(session["user_id"])
    if user is None or not user["is_active"]:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Rotate: revoke old, issue new
    await revoke_session(jti)
    new_jti, new_raw_refresh = create_refresh_token()
    await create_session(jti=new_jti, user_id=user["id"], expires_days=7)

    new_access = create_access_token(
        user_id=user["id"],
        username=user["username"],
        is_admin=bool(user["is_admin"]),
    )

    _set_refresh_cookie(response, new_raw_refresh)

    return {
        "access_token": new_access,
        "token_type": "bearer",
        "refresh_token": new_raw_refresh,
    }


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, str]:
    """Revoke the current refresh session and clear the cookie."""
    raw_token = request.cookies.get(_REFRESH_COOKIE)
    if not raw_token:
        try:
            body = await request.json()
            raw_token = body.get("refresh_token")
        except Exception:
            raw_token = None

    if raw_token:
        jti = parse_refresh_token_jti(raw_token)
        if jti:
            try:
                await revoke_session(jti)
            except Exception as exc:
                logger.warning(f"Session revoke error during logout: {exc}")

    _clear_refresh_cookie(response)
    return {"detail": "Logged out"}


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------


@router.get("/me")
async def get_me(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Return the authenticated user's profile."""
    return _user_response(user)


@router.patch("/me")
async def update_me(
    body: UpdateMeRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Update display_name and/or password for the current user."""
    if body.password is not None:
        # Require current_password when changing password
        if not body.current_password:
            raise HTTPException(
                status_code=400, detail="current_password is required to set a new password"
            )
        if not verify_password(body.current_password, user.get("password_hash", "")):
            raise HTTPException(status_code=401, detail="Current password is incorrect")

    new_display_name = (
        body.display_name if body.display_name is not None else user.get("display_name")
    )
    new_password_hash = (
        hash_password(body.password) if body.password is not None else user.get("password_hash")
    )

    if body.display_name is None and body.password is None:
        return _user_response(user)

    now = now_iso()
    conn = await db.get()
    await conn.execute(
        "UPDATE users SET display_name = ?, password_hash = ?, updated_at = ? WHERE id = ?",
        (new_display_name, new_password_hash, now, user["id"]),
    )
    await conn.commit()

    refreshed = await get_user_by_id(user["id"])
    return _user_response(refreshed or user)


# ---------------------------------------------------------------------------
# Personal Access Tokens
# ---------------------------------------------------------------------------


@router.post("/tokens", status_code=201)
async def create_pat_token(
    body: CreatePATRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Create a new PAT.  Returns the raw token exactly once — store it safely."""
    token_id, raw_token, token_hash = create_pat()

    expires_at: str | None = None
    if body.expires_in_days is not None:
        expires_at = (datetime.now(UTC) + timedelta(days=body.expires_in_days)).isoformat()

    pat = await db_create_pat(
        token_id=token_id,
        user_id=user["id"],
        name=body.name,
        token_hash=token_hash,
        expires_at=expires_at,
    )

    return {**pat, "token": raw_token}


@router.get("/tokens")
async def list_pat_tokens(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[dict[str, Any]]:
    """List PAT metadata for the current user.  token_hash is never returned."""
    return await list_pats(user["id"])


@router.delete("/tokens/{token_id}", status_code=204)
async def delete_pat_token(
    token_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> None:
    """Revoke a PAT owned by the current user."""
    pat = await get_pat_by_id(token_id)
    if pat is None or pat["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Token not found")

    await delete_pat(token_id, user["id"])


# ---------------------------------------------------------------------------
# Admin: list users
# ---------------------------------------------------------------------------


@router.get("/users")
async def list_all_users(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[dict[str, Any]]:
    """List all users.  Admin only."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    return await list_users()
