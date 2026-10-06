"""Stateless CVSS v3.1 scoring endpoint.

Pure computation, no DB access: the single implementation the frontend
calls for live score recomputation as a reviewer edits the 8 metric
dropdowns, instead of porting backend.scoring.cvss31's formula to JS.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.auth.dependencies import get_current_user
from backend.models.api import CvssScoreRequest
from backend.scoring.cvss31 import score_and_severity


router = APIRouter(prefix="/cvss", tags=["cvss"])


@router.post("/score")
async def score_cvss_vector(
    body: CvssScoreRequest,
    _user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Parse a CVSS v3.1 vector and return its computed score + severity.

    `body.vector` is already parsed and canonicalized by
    CvssScoreRequest's validator (422 on anything malformed), so this is
    just score_and_severity() on the now-trusted string.
    """
    score, severity = score_and_severity(body.vector)
    return {"score": score, "severity": severity}
