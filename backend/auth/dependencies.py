"""FastAPI authentication dependencies.

Phase 0: get_current_user, get_optional_user, _authenticate_token.
Phase 2: resolve_project_id, require_role factory (added when projects exist).

When PARANOID_REQUIRE_AUTH is false (default) every request is treated as a
synthetic instance-admin user — exactly the existing single-user behaviour.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

# Synthetic admin used when auth is disabled (PARANOID_REQUIRE_AUTH=false).
_ANON_ADMIN: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000001",
    "username": "admin",
    "display_name": "Administrator",
    "is_admin": True,
    "is_active": True,
}


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> dict[str, Any]:
    """Resolve the authenticated user from a Bearer JWT or PAT.

    When PARANOID_REQUIRE_AUTH is false, returns _ANON_ADMIN without
    checking credentials (backwards-compatible single-user mode).

    Raises HTTP 401 when auth is enabled and no valid credential is supplied.
    """
    from backend.config import settings

    if not settings.paranoid_require_auth:
        return _ANON_ADMIN

    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    return await _authenticate_token(credentials.credentials)


async def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> dict[str, Any] | None:
    """Like get_current_user but returns None instead of raising 401.

    Use on routes that behave differently for authenticated vs. anonymous
    callers (e.g. showing owned-only resources).
    """
    from backend.config import settings

    if not settings.paranoid_require_auth:
        return _ANON_ADMIN

    if credentials is None:
        return None

    try:
        return await _authenticate_token(credentials.credentials)
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _authenticate_token(token: str) -> dict[str, Any]:
    """Dispatch to JWT or PAT validation based on token prefix."""
    from backend.auth.tokens import is_pat

    if is_pat(token):
        return await _authenticate_pat(token)
    return await _authenticate_jwt(token)


async def _authenticate_jwt(token: str) -> dict[str, Any]:
    """Validate a JWT and return the user dict from the DB."""
    try:
        from backend.auth.tokens import decode_access_token

        payload = decode_access_token(token)
    except Exception as exc:
        logger.debug(f"JWT validation failed: {exc}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: missing sub")

    from backend.db.crud_auth import get_user_by_id

    user = await get_user_by_id(user_id)
    if user is None or not user["is_active"]:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    return user


async def _authenticate_pat(token: str) -> dict[str, Any]:
    """Validate a PAT via O(1) PK lookup + sha256 comparison."""
    from backend.auth.tokens import hash_pat, parse_pat_token_id

    token_id = parse_pat_token_id(token)
    if not token_id:
        raise HTTPException(status_code=401, detail="Malformed PAT")

    from backend.db.crud_auth import get_pat_by_id, update_pat_last_used

    pat = await get_pat_by_id(token_id)
    if pat is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    if pat["token_hash"] != hash_pat(token):
        raise HTTPException(status_code=401, detail="Invalid token")

    if pat["expires_at"]:
        exp = datetime.fromisoformat(pat["expires_at"])
        if datetime.now(UTC) > exp:
            raise HTTPException(status_code=401, detail="Token expired")

    from backend.db.crud_auth import get_user_by_id

    user = await get_user_by_id(pat["user_id"])
    if user is None or not user["is_active"]:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    try:
        await update_pat_last_used(token_id)
    except Exception:
        pass

    return {**user, "pat_id": token_id, "pat_project_id": pat.get("project_id")}


# ---------------------------------------------------------------------------
# Phase 2: RBAC helpers
# ---------------------------------------------------------------------------

_ROLE_ORDER = {"owner": 3, "editor": 2, "viewer": 1}


async def resolve_project_id(entity_type: str, entity_id: str) -> str:
    """Resolve project_id from any entity type. Raises 404 if not found.

    entity_type: 'model' | 'threat' | 'source'
    """
    from backend.db.crud_projects import (
        resolve_project_id_from_model,
        resolve_project_id_from_source,
        resolve_project_id_from_threat,
    )

    if entity_type == "model":
        project_id = await resolve_project_id_from_model(entity_id)
    elif entity_type == "threat":
        project_id = await resolve_project_id_from_threat(entity_id)
    elif entity_type == "source":
        project_id = await resolve_project_id_from_source(entity_id)
    else:
        raise HTTPException(status_code=500, detail=f"Unknown entity_type: {entity_type}")

    if project_id is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return project_id


def require_role(min_role: str, entity_param: str, entity_type: str):
    """Factory: returns a FastAPI dependency that checks project membership.

    When PARANOID_REQUIRE_AUTH is false, passes through (anon admin has all access).
    When the entity's project_id is the Default Project sentinel, allows any
    authenticated user with at least min_role (or any user if anon mode).

    Usage:
        @router.patch("/{threat_id}")
        async def update_threat(
            threat_id: str,
            _: None = Depends(require_role("editor", "threat_id", "threat")),
        ): ...
    """

    async def _dep(
        request: Request,
        user: Annotated[dict, Depends(get_current_user)],
    ) -> None:
        from backend.config import settings

        if not settings.paranoid_require_auth:
            return  # anon admin — full access

        entity_id = request.path_params.get(entity_param)
        if not entity_id:
            raise HTTPException(status_code=400, detail=f"Missing path param: {entity_param}")

        project_id = await resolve_project_id(entity_type, entity_id)

        # Instance admins bypass project membership check
        if user.get("is_admin"):
            return

        from backend.db.crud_projects import get_user_role_in_project

        role = await get_user_role_in_project(project_id, user["id"])
        if role is None:
            raise HTTPException(status_code=403, detail="Not a member of this project")

        if _ROLE_ORDER.get(role, 0) < _ROLE_ORDER.get(min_role, 0):
            raise HTTPException(
                status_code=403,
                detail=f"Requires {min_role} role (you have {role})",
            )

    return _dep


def require_admin(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    """Dependency: require is_admin=True. Returns the user dict."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
