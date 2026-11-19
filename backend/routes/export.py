"""Export routes — serve threat model reports in multiple formats."""

import json
import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from backend.auth.dependencies import require_role
from backend.db import crud
from backend.db.maestro_tags import get_model_coverage, parse_categories
from backend.export.context_diagram import context_to_mermaid
from backend.export.markdown import export_markdown
from backend.export.pdf import export_pdf
from backend.export.report_inputs import gather_report_inputs
from backend.export.sarif import export_sarif, sanitize_source_file, threat_from_row
from backend.models.api import ExportFormat
from backend.models.state import ThreatsList


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])


def _build_threats_list(threat_rows: list[dict]) -> ThreatsList:
    """Reconstruct a ThreatsList from flat DB rows for SARIF export.

    Each row goes through sarif.threat_from_row() (shared with the CLI's
    SARIF export), which rebuilds the nested fields export_sarif reads.
    MAESTRO-only threats (no stride_category) are filtered out because the SARIF
    exporter only handles STRIDE categories; a per-threat warning is logged.
    """
    stride_rows = [r for r in threat_rows if r.get("stride_category")]
    skipped = len(threat_rows) - len(stride_rows)
    if skipped:
        logger.warning("%d MAESTRO-only threat(s) skipped — SARIF export is STRIDE-only", skipped)

    built = []
    for row in stride_rows:
        try:
            built.append(threat_from_row(row))
        except Exception as exc:
            logger.warning("Skipping threat '%s' during SARIF build: %s", row.get("name"), exc)

    return ThreatsList.model_construct(threats=built)


@router.get("/{model_id}")
async def export_model(
    model_id: str,
    export_format: Annotated[ExportFormat, Query(alias="format")] = "markdown",
    status_filter: Annotated[str | None, Query()] = None,
    source_file: Annotated[str | None, Query()] = None,
    _authz: None = Depends(require_role("viewer", "model_id", "model")),
) -> Response:
    """Export a threat model in the requested format.

    Query parameters:
    - format: markdown | pdf | sarif | json  (default: markdown)
    - status_filter: pending | approved | rejected | mitigated  (optional)
    - source_file: sarif only — repo-relative path GitHub code scanning
      should anchor non-dependency results to (point this at your
      description file in the repo). Defaults to "threat-model.md".
      Must be a plain relative path: no leading "/", no URL scheme, no
      ".." segment, and no longer than 1024 characters
    """
    if source_file is not None and sanitize_source_file(source_file) is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Invalid source_file: must be a relative path with no '..' segment, "
                "URL scheme, or leading '/', and no longer than 1024 characters"
            ),
        )

    model = await crud.get_threat_model(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

    framework = model.get("framework", "STRIDE")
    # Strip characters that would break Content-Disposition or filesystem paths.
    raw = model.get("title") or model_id[:8]
    safe_title = re.sub(r"[^\w\-]", "_", raw).lower().strip("_") or "export"

    if export_format in ("markdown", "pdf"):
        # The same loader as the CLI's `models export`, so both reports match.
        report = await gather_report_inputs(model, status=status_filter)
        if export_format == "markdown":
            return Response(
                content=export_markdown(**report),
                media_type="text/markdown",
                headers={"Content-Disposition": f'attachment; filename="{safe_title}.md"'},
            )
        return Response(
            content=export_pdf(**report),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.pdf"'},
        )

    threats = await crud.list_threats(model_id, status=status_filter)

    if export_format == "sarif":
        threats_list = _build_threats_list(threats)
        sarif_data = export_sarif(
            threats=threats_list,
            model_id=model_id,
            framework=framework,
            source_file=source_file,
        )
        return Response(
            content=json.dumps(sarif_data, indent=2),
            media_type="application/sarif+json",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_title}.sarif"',
            },
        )

    # format == "json"
    assets = await crud.list_assets(model_id)
    flows = await crud.list_flows(model_id)
    trust_boundaries = await crud.list_trust_boundaries(model_id)
    return JSONResponse(
        content={
            "model": model,
            "threats": threats,
            "assets": [
                {**a, "maestro_categories": parse_categories(a.get("maestro_categories"))}
                for a in assets
            ],
            "flows": flows,
            "trust_boundaries": trust_boundaries,
            "maestro_coverage": await get_model_coverage(model_id),
            # Uploaded diagrams (images as base64) and the one drawn from the context.
            "diagrams": [_diagram_json(d) for d in await crud.list_model_diagrams(model_id)],
            "context_diagram": context_to_mermaid(assets, flows, trust_boundaries) or None,
        },
        headers={
            "Content-Disposition": f'attachment; filename="{safe_title}.json"',
        },
    )


def _diagram_json(row: dict) -> dict:
    keys = ("id", "name", "kind", "media_type", "size_bytes", "position", "content", "created_at")
    return {k: row.get(k) for k in keys}
