"""Notification routes (Phase 5). Notifications are user-scoped, not project-scoped."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth.dependencies import get_current_user
from backend.db import crud_activity


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    user: Annotated[dict, Depends(get_current_user)],
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict]:
    return await crud_activity.list_notifications(user["id"], limit=limit, unread_only=unread_only)


@router.patch("/{notification_id}")
async def mark_notification_read(
    notification_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    updated = await crud_activity.mark_notification_read(notification_id, user["id"])
    if updated is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return updated


@router.post("/mark-all-read", status_code=204)
async def mark_all_notifications_read(
    user: Annotated[dict, Depends(get_current_user)],
) -> None:
    await crud_activity.mark_all_read(user["id"])
