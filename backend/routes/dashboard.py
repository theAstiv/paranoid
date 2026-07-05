"""Project dashboard route (Phase 7): aggregate stats for the project landing page."""

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.auth.dependencies import get_current_user
from backend.db import crud_activity, crud_dashboard
from backend.routes.projects import _require_member


router = APIRouter(tags=["dashboard"])


@router.get("/projects/{project_id}/dashboard")
async def get_project_dashboard(
    project_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    await _require_member(project_id, user)

    stats = await crud_dashboard.get_dashboard_stats(project_id)
    severity = await crud_dashboard.get_severity_breakdown(project_id)
    activity = await crud_activity.list_activity(project_id, limit=15)
    assigned_to_you = await crud_dashboard.get_assigned_threats(project_id, user["id"])

    return {
        "stats": stats,
        "severity": severity,
        "activity": activity,
        "assigned_to_you": assigned_to_you,
    }
