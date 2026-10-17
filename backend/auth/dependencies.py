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


async def _resolve_anon_admin() -> dict[str, Any]:
    """Return the real 'admin' user from the DB for anon mode.

    Avoids FK violations: the projects table has created_by REFERENCES users(id),
    so we must use the id the DB actually assigned at bootstrap time, not a
    hardcoded phantom.

    Falls back to a synthetic identity only during the brief window before the
    admin user is seeded (initial app startup). Logs a warning in that case.
    """
    try:
        from backend.db.crud_auth import get_user_by_username

        user = await get_user_by_username("admin")
        if user is not None:
            return user
    except Exception as exc:
        logger.warning("Could not resolve anon admin from DB: %s", exc)

    # Should only be reached before _bootstrap_admin_if_needed completes.
    logger.warning(
        "Admin user not found in DB — using synthetic identity. "
        "This is expected only during initial startup before bootstrap completes."
    )
    return {
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

    When PARANOID_REQUIRE_AUTH is false, resolves the real admin user from the
    DB (backwards-compatible single-user mode).

    Raises HTTP 401 when auth is enabled and no valid credential is supplied.
    """
    from backend.config import settings

    if not settings.paranoid_require_auth:
        return await _resolve_anon_admin()

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
        return await _resolve_anon_admin()

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

ROLE_ORDER: dict[str, int] = {"owner": 3, "editor": 2, "viewer": 1}


async def resolve_project_id(entity_type: str, entity_id: str) -> str:
    """Resolve project_id from any entity type. Raises 404 if not found.

    entity_type: 'model' | 'threat' | 'source' | 'comment'
    """
    from backend.db.crud_projects import (
        resolve_project_id_from_asset,
        resolve_project_id_from_comment,
        resolve_project_id_from_flow,
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
    elif entity_type == "comment":
        project_id = await resolve_project_id_from_comment(entity_id)
    elif entity_type == "asset":
        project_id = await resolve_project_id_from_asset(entity_id)
    elif entity_type == "flow":
        project_id = await resolve_project_id_from_flow(entity_id)
    else:
        raise HTTPException(status_code=500, detail=f"Unknown entity_type: {entity_type}")

    if project_id is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return project_id


def check_pat_scope(user: dict[str, Any], project_id: str) -> None:
    """Raise 403 if `user` authenticated with a PAT scoped to a different project.

    Runs before any admin bypass: the scope is what the token's creator asked for,
    and the owner's admin rights must not widen it. An unscoped PAT, a JWT session
    and the anonymous auth-off user have no scope, so this is a no-op for them.
    """
    scope = user.get("pat_project_id")
    if scope and scope != project_id:
        raise HTTPException(status_code=403, detail="Token is scoped to a different project")


def require_unscoped(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    """Dependency: reject project-scoped PATs. Used on token management, where a
    scoped token could otherwise mint an unscoped one for the same user, and on
    creating projects, which are outside any one project's scope."""
    if user.get("pat_project_id"):
        raise HTTPException(status_code=403, detail="Not allowed for a project-scoped token")
    return user


async def check_project_role(user: dict[str, Any], project_id: str, min_role: str) -> None:
    """Raise 403 unless `user` has at least `min_role` in `project_id`.

    A project-scoped PAT is limited to its project (see check_pat_scope). Instance
    admins otherwise bypass the membership check. Callers are responsible for the
    PARANOID_REQUIRE_AUTH=false short-circuit (see require_role).
    """
    check_pat_scope(user, project_id)
    if user.get("is_admin"):
        return

    from backend.db.crud_projects import get_user_role_in_project

    role = await get_user_role_in_project(project_id, user["id"])
    if role is None:
        raise HTTPException(status_code=403, detail="Not a member of this project")

    if ROLE_ORDER.get(role, 0) < ROLE_ORDER.get(min_role, 0):
        raise HTTPException(
            status_code=403,
            detail=f"Requires {min_role} role (you have {role})",
        )


def require_active_project(project: dict[str, Any] | None) -> None:
    """Raise 403 when `project` is archived. A missing project is the caller's to handle.

    check_project_role looks only at membership, and an admin bypasses it, so create
    routes call this too: a source or model created in an archived project would be
    hidden from every list a non-admin can see. It applies to admins and with auth off.
    """
    if project and project.get("is_archived"):
        raise HTTPException(status_code=403, detail="This project is archived.")


async def visible_project_ids(user: dict[str, Any], project_id: str | None) -> list[str] | None:
    """Project ids a list route may show `user`, or ``None`` for no restriction.

    Non-admins see the projects they belong to; a project-scoped PAT sees only its
    project (even for an admin). An explicit `project_id` filter must be one the
    caller can see: archived projects are omitted from membership, so they 403 too.
    Auth off resolves to the instance admin, i.e. no restriction.
    """
    scope = user.get("pat_project_id")
    if scope and project_id is not None:
        check_pat_scope(user, project_id)
    if user.get("is_admin"):
        return [scope] if scope else None

    from backend.db.crud_projects import list_projects_for_user

    member_of = {p["id"] for p in await list_projects_for_user(user["id"])}
    if project_id is not None and project_id not in member_of:
        raise HTTPException(
            status_code=403, detail="Not a member of this project, or it is archived"
        )
    return sorted(member_of & {scope} if scope else member_of)


def require_role(min_role: str, entity_param: str, entity_type: str):
    """Factory: returns a FastAPI dependency that checks project membership.

    When PARANOID_REQUIRE_AUTH is false, passes through (anon admin has all access).
    Otherwise the caller must be an instance admin or a member of the entity's
    project with at least min_role. The Default Project has no special rule: it is
    an ordinary project (the migration makes the admin its owner), so non-admin
    users need to be added as members to reach models that predate projects.

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
        await check_project_role(user, project_id, min_role)

    return _dep


def require_admin(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    """Dependency: require is_admin=True. Returns the user dict.

    A project-scoped PAT is refused even for an admin: instance-wide routes are
    outside any one project, and the scope must not be widened by admin rights.
    """
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    if user.get("pat_project_id"):
        raise HTTPException(status_code=403, detail="Not allowed for a project-scoped token")
    return user
