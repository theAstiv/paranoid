"""Export routes — serve threat model reports in multiple formats."""

import json
import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from backend.auth.dependencies import require_role
from backend.db import crud
from backend.db.gap_utils import decode_gap_summaries
from backend.db.maestro_tags import get_model_coverage, parse_categories
from backend.export.markdown import export_markdown
from backend.export.pdf import export_pdf
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

    threats = await crud.list_threats(model_id, status=status_filter)
    assets = await crud.list_assets(model_id)
    flows = await crud.list_flows(model_id)
    trust_boundaries = await crud.list_trust_boundaries(model_id)
    dependency_scans = (
        await crud.list_dependency_scans(model_id) if export_format in ("markdown", "pdf") else []
    )

    title = model.get("title")
    framework = model.get("framework", "STRIDE")
    gap_summaries = decode_gap_summaries(model.get("gap_summaries"))
    description: str | None = model.get("description") or None
    assumptions: list[str] | None = decode_gap_summaries(model.get("assumptions")) or None
    # Strip characters that would break Content-Disposition or filesystem paths.
    raw = title or model_id[:8]
    safe_title = re.sub(r"[^\w\-]", "_", raw).lower().strip("_") or "export"

    # Collect enrichment data (attack trees, test cases) per threat.
    # The export functions render them only when present — no-op when not enriched.
    attack_trees: dict = {}
    test_suites: dict = {}
    if export_format in ("markdown", "pdf"):
        for t in threats:
            tid = t.get("id") or ""
            if not tid:
                continue
            trees = await crud.list_attack_trees(tid)
            if trees:
                attack_trees[tid] = trees[-1]  # most recent tree per threat
            cases = await crud.list_test_cases(tid)
            if cases:
                gherkin = "\n\n".join(c["gherkin_source"] for c in cases if c.get("gherkin_source"))
                if gherkin:
                    test_suites[tid] = {"gherkin_source": gherkin}

    if export_format == "markdown":
        content = export_markdown(
            threats=threats,
            model_id=model_id,
            framework=framework,
            title=title,
            description=description,
            assumptions=assumptions,
            assets=assets,
            flows=flows,
            trust_boundaries=trust_boundaries,
            attack_trees=attack_trees or None,
            test_suites=test_suites or None,
            gap_summaries=gap_summaries or None,
            dependency_scans=dependency_scans or None,
        )
        return Response(
            content=content,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_title}.md"',
            },
        )

    if export_format == "pdf":
        pdf_bytes = export_pdf(
            threats=threats,
            model_id=model_id,
            framework=framework,
            title=title,
            description=description,
            assumptions=assumptions,
            assets=assets,
            flows=flows,
            trust_boundaries=trust_boundaries,
            attack_trees=attack_trees or None,
            test_suites=test_suites or None,
            gap_summaries=gap_summaries or None,
            dependency_scans=dependency_scans or None,
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_title}.pdf"',
            },
        )

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
        },
        headers={
            "Content-Disposition": f'attachment; filename="{safe_title}.json"',
        },
    )
