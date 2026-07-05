"""Comment and assignee routes for threat models (Phase 3)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.auth.dependencies import get_current_user, require_role
from backend.db import crud_activity, crud_comments, crud_projects
from backend.models.api import AddAssigneeRequest, CreateCommentRequest, UpdateCommentRequest


logger = logging.getLogger(__name__)

router = APIRouter(tags=["comments"])


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


@router.get("/models/{model_id}/comments")
async def list_comments(
    model_id: str,
    _authz: None = Depends(require_role("viewer", "model_id", "model")),
) -> list[dict]:
    return await crud_comments.list_comments(model_id)


@router.post("/models/{model_id}/comments", status_code=201)
async def create_comment(
    model_id: str,
    body: CreateCommentRequest,
    user: Annotated[dict, Depends(get_current_user)],
    _authz: None = Depends(require_role("viewer", "model_id", "model")),
) -> dict:
    if body.parent_id is not None:
        await _require_valid_parent(model_id, body.parent_id)

    created = await crud_comments.create_comment(
        threat_model_id=model_id,
        user_id=user["id"],
        body=body.body,
        parent_id=body.parent_id,
    )
    if created is None:
        raise HTTPException(status_code=404, detail="Threat model not found")

    project_id = await crud_projects.resolve_project_id_from_model(model_id)
    await crud_activity.safe_log_activity(
        project_id=project_id,
        user_id=user["id"],
        entity_type="comment",
        entity_id=created["id"],
        action="created",
        details={"threat_model_id": model_id},
    )
    assignees = await crud_comments.list_assignees(model_id)
    await crud_activity.safe_notify_users(
        {a["user_id"] for a in assignees if a["user_id"] != user["id"]},
        notification_type="comment_added",
        title=f"{user.get('display_name') or user.get('username', 'Someone')} commented on a threat model",
        entity_type="comment",
        entity_id=created["id"],
    )
    return created


@router.patch("/comments/{comment_id}")
async def update_comment(
    comment_id: str,
    body: UpdateCommentRequest,
    user: Annotated[dict, Depends(get_current_user)],
    _authz: None = Depends(require_role("viewer", "comment_id", "comment")),
) -> dict:
    comment = await crud_comments.get_comment(comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    _require_author(comment, user)

    updated = await crud_comments.update_comment(comment_id, body.body)
    if updated is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    return updated


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    _authz: None = Depends(require_role("viewer", "comment_id", "comment")),
) -> None:
    comment = await crud_comments.get_comment(comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    await _require_author_or_moderator(comment, user)
    project_id = await crud_projects.resolve_project_id_from_comment(comment_id)
    await crud_comments.delete_comment(comment_id)
    await crud_activity.safe_log_activity(
        project_id=project_id,
        user_id=user["id"],
        entity_type="comment",
        entity_id=comment_id,
        action="deleted",
        details={"threat_model_id": comment.get("threat_model_id")},
    )


# ---------------------------------------------------------------------------
# Assignees
# ---------------------------------------------------------------------------


@router.get("/models/{model_id}/assignees")
async def list_assignees(
    model_id: str,
    _authz: None = Depends(require_role("viewer", "model_id", "model")),
) -> list[dict]:
    return await crud_comments.list_assignees(model_id)


@router.post("/models/{model_id}/assignees", status_code=201)
async def add_assignee(
    model_id: str,
    body: AddAssigneeRequest,
    user: Annotated[dict, Depends(get_current_user)],
    _authz: None = Depends(require_role("editor", "model_id", "model")),
) -> dict:
    await _require_project_member(model_id, body.user_id)

    assignee = await crud_comments.add_assignee(model_id, body.user_id, user["id"])
    if assignee is None:
        raise HTTPException(status_code=404, detail="User not found")

    project_id = await crud_projects.resolve_project_id_from_model(model_id)
    await crud_activity.safe_log_activity(
        project_id=project_id,
        user_id=user["id"],
        entity_type="model",
        entity_id=model_id,
        action="assignee_added",
        details={"assignee_id": body.user_id},
    )
    if body.user_id != user["id"]:
        await crud_activity.safe_notify_users(
            {body.user_id},
            notification_type="assigned",
            title=f"You were assigned to a threat model by {user.get('display_name') or user.get('username', 'a teammate')}",
            entity_type="model",
            entity_id=model_id,
        )
    return assignee


@router.delete("/models/{model_id}/assignees/{user_id}", status_code=204)
async def remove_assignee(
    model_id: str,
    user_id: str,
    actor: Annotated[dict, Depends(get_current_user)],
    _authz: None = Depends(require_role("editor", "model_id", "model")),
) -> None:
    await crud_comments.remove_assignee(model_id, user_id)
    project_id = await crud_projects.resolve_project_id_from_model(model_id)
    await crud_activity.safe_log_activity(
        project_id=project_id,
        user_id=actor["id"],
        entity_type="model",
        entity_id=model_id,
        action="assignee_removed",
        details={"assignee_id": user_id},
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_author(comment: dict, user: dict) -> None:
    if user.get("is_admin"):
        return
    if comment.get("user_id") != user.get("id"):
        raise HTTPException(status_code=403, detail="Only the comment author may edit this comment")


async def _require_valid_parent(model_id: str, parent_id: str) -> None:
    parent = await crud_comments.get_comment(parent_id)
    if parent is None or parent["threat_model_id"] != model_id:
        raise HTTPException(
            status_code=422,
            detail="parent_id must reference a comment in the same threat model",
        )
    if parent.get("parent_id") is not None:
        raise HTTPException(
            status_code=422,
            detail="Cannot reply to a reply — only one level of nesting is supported",
        )


async def _require_project_member(model_id: str, user_id: str) -> None:
    from backend.config import settings

    if not settings.paranoid_require_auth:
        return

    project_id = await crud_projects.resolve_project_id_from_model(model_id)
    role = await crud_projects.get_user_role_in_project(project_id, user_id)
    if role is None:
        raise HTTPException(status_code=404, detail="User is not a member of this project")


async def _require_author_or_moderator(comment: dict, user: dict) -> None:
    if user.get("is_admin"):
        return
    if comment.get("user_id") == user.get("id"):
        return

    from backend.config import settings

    if not settings.paranoid_require_auth:
        return

    project_id = await crud_projects.resolve_project_id_from_comment(comment["id"])
    role = await crud_projects.get_user_role_in_project(project_id, user["id"])
    role_order = crud_projects.ROLE_ORDER
    if role is None or role_order.get(role, 0) < role_order.get("editor", 0):
        raise HTTPException(
            status_code=403,
            detail="Only the author or an editor may delete this comment",
        )
