"""Project, member, and invitation routes (Phase 2)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.auth.dependencies import get_current_user, require_admin
from backend.db import crud_projects
from backend.models.api import (
    AddMemberRequest,
    CreateInvitationRequest,
    CreateProjectRequest,
    UpdateMemberRoleRequest,
    UpdateProjectRequest,
)


logger = logging.getLogger(__name__)

router = APIRouter(tags=["projects"])

# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@router.post("/projects", status_code=201)
async def create_project(
    body: CreateProjectRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    return await crud_projects.create_project(
        name=body.name,
        created_by=user["id"],
        description=body.description,
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
        await _require_member(project_id, user)
    return project


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    await _require_owner(project_id, user)
    updates = body.model_dump(exclude_none=True)
    project = await crud_projects.update_project(project_id, **updates)
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
    body: AddMemberRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    await _require_owner(project_id, user)
    return await crud_projects.add_member(project_id, body.user_id, body.role)


@router.patch("/projects/{project_id}/members/{user_id}")
async def update_member(
    project_id: str,
    user_id: str,
    body: UpdateMemberRoleRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    await _require_owner(project_id, user)
    member = await crud_projects.update_member_role(project_id, user_id, body.role)
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
    body: CreateInvitationRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    await _require_owner(project_id, user)
    try:
        return await crud_projects.create_invitation(
            project_id=project_id,
            invited_email=body.invited_email,
            role=body.role,
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
    # Pre-check existence so callers get 404 (not 409) for unknown IDs.
    inv = await crud_projects.get_invitation(invitation_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")
    try:
        return await crud_projects.accept_invitation(
            invitation_id, user["id"], user.get("email", "")
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
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

    # Authorization: project owner OR the invited person may decline.
    from backend.config import settings

    if settings.paranoid_require_auth and not user.get("is_admin"):
        role = await crud_projects.get_user_role_in_project(inv["project_id"], user["id"])
        is_owner = role == "owner"
        is_invitee = inv["invited_email"].lower() == user.get("email", "").lower()
        if not is_owner and not is_invitee:
            raise HTTPException(
                status_code=403,
                detail="Only the project owner or the invited user may decline this invitation",
            )

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
