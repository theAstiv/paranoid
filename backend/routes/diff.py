"""Model diff route — compare threats between two pipeline runs."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from backend.auth.dependencies import get_current_user
from backend.db import crud
from backend.db.crud_diff import compare_models


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["diff"])


@router.get("/{head_id}/diff")
async def get_model_diff(
    head_id: str,
    base_id: str = Query(..., description="ID of the base (older) model to compare against"),
    threshold: float = Query(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Cosine similarity threshold for matching threats (0–1)",
    ),
    _user: Annotated[dict | None, Depends(get_current_user)] = None,
) -> JSONResponse:
    """Compare threats between two models.

    Returns a diff classifying each threat as added, removed, changed, or
    unchanged relative to the base model. Uses embedding cosine similarity
    to match threats across runs.

    Args:
        head_id: The newer / re-run model (in the URL path).
        base_id: The older / reference model (query param).
        threshold: Minimum similarity to consider two threats the same (default 0.75).
    """
    if head_id == base_id:
        raise HTTPException(status_code=400, detail="head_id and base_id must be different models")

    head = await crud.get_threat_model(head_id)
    if head is None:
        raise HTTPException(status_code=404, detail=f"Model '{head_id}' not found")
    if head["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Head model '{head_id}' is not completed (status: {head['status']})",
        )

    base = await crud.get_threat_model(base_id)
    if base is None:
        raise HTTPException(status_code=404, detail=f"Base model '{base_id}' not found")
    if base["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Base model '{base_id}' is not completed (status: {base['status']})",
        )

    # Cross-project diffing is intentionally allowed: users choose both models
    # explicitly and both are already visible to them through the model list.
    # If projects become strictly isolated namespaces in a future auth revision,
    # add a project_id equality check here.

    result = await compare_models(
        base_model_id=base_id,
        head_model_id=head_id,
        match_threshold=threshold,
    )

    return JSONResponse(content=result.to_dict())
