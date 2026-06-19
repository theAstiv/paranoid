"""Project, member, and invitation routes (Phase 2)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.auth.dependencies import get_current_user, require_admin
from backend.db import crud_projects


logger = logging.getLogger(__name__)

router = APIRouter(tags=["projects"])

# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@router.post("/projects", status_code=201)
async def create_project(
    body: dict,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    return await crud_projects.create_project(
        name=name,
        created_by=user["id"],
        description=body.get("description"),
    )


@router.get("/projects")
async def list_projects(
    user: Annotated[dict, Depends(get_current_user)],
) -> list[dict]:
    if user.get("is_admin"):
        return await crud_projects.list_all_projects()
    return await crud_projects.list_projects_for_user(user["id"])


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    project = await crud_projects.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not user.get("is_admin"):
        role = await crud_projects.get_user_role_in_project(project_id, user["id"])
        if role is None:
            raise HTTPException(status_code=403, detail="Not a member of this project")
    return project


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: str,
    body: dict,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    await _require_owner(project_id, user)
    project = await crud_projects.update_project(project_id, **body)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/projects/{project_id}", status_code=204)
async def archive_project(
    project_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> None:
    await _require_owner(project_id, user)
    await crud_projects.archive_project(project_id)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/members")
async def list_members(
    project_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> list[dict]:
    await _require_member(project_id, user)
    return await crud_projects.list_members(project_id)


@router.post("/projects/{project_id}/members", status_code=201)
async def add_member(
    project_id: str,
    body: dict,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    await _require_owner(project_id, user)
    user_id = body.get("user_id")
    role = body.get("role", "viewer")
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    if role not in ("owner", "editor", "viewer"):
        raise HTTPException(status_code=422, detail="role must be owner/editor/viewer")
    member = await crud_projects.add_member(project_id, user_id, role)
    return member


@router.patch("/projects/{project_id}/members/{user_id}")
async def update_member(
    project_id: str,
    user_id: str,
    body: dict,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    await _require_owner(project_id, user)
    role = body.get("role")
    if role not in ("owner", "editor", "viewer"):
        raise HTTPException(status_code=422, detail="role must be owner/editor/viewer")
    member = await crud_projects.update_member_role(project_id, user_id, role)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
async def remove_member(
    project_id: str,
    user_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> None:
    await _require_owner(project_id, user)
    try:
        await crud_projects.remove_member(project_id, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/invitations", status_code=201)
async def create_invitation(
    project_id: str,
    body: dict,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    await _require_owner(project_id, user)
    email = (body.get("invited_email") or "").strip()
    role = body.get("role", "viewer")
    if not email:
        raise HTTPException(status_code=422, detail="invited_email is required")
    if role not in ("owner", "editor", "viewer"):
        raise HTTPException(status_code=422, detail="role must be owner/editor/viewer")
    try:
        return await crud_projects.create_invitation(
            project_id=project_id,
            invited_email=email,
            role=role,
            invited_by=user["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/projects/{project_id}/invitations")
async def list_invitations(
    project_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> list[dict]:
    await _require_owner(project_id, user)
    return await crud_projects.list_invitations(project_id)


@router.post("/invitations/{invitation_id}/accept", status_code=200)
async def accept_invitation(
    invitation_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    try:
        return await crud_projects.accept_invitation(invitation_id, user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/invitations/{invitation_id}/decline", status_code=204)
async def decline_invitation(
    invitation_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> None:
    inv = await crud_projects.get_invitation(invitation_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")
    await crud_projects.decline_invitation(invitation_id)


# ---------------------------------------------------------------------------
# Admin: Users list
# ---------------------------------------------------------------------------


@router.get("/users")
async def list_users(
    _admin: Annotated[dict, Depends(require_admin)],
) -> list[dict]:
    from backend.db.crud_auth import list_users as _list_users

    return await _list_users()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _require_member(project_id: str, user: dict) -> None:
    if user.get("is_admin"):
        return
    from backend.config import settings

    if not settings.paranoid_require_auth:
        return
    role = await crud_projects.get_user_role_in_project(project_id, user["id"])
    if role is None:
        raise HTTPException(status_code=403, detail="Not a member of this project")


async def _require_owner(project_id: str, user: dict) -> None:
    if user.get("is_admin"):
        return
    from backend.config import settings

    if not settings.paranoid_require_auth:
        return
    role = await crud_projects.get_user_role_in_project(project_id, user["id"])
    if role != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
