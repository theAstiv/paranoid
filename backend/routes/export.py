"""Export routes — serve threat model reports in multiple formats."""

import json
import logging
import re
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from backend.db import crud
from backend.export.markdown import export_markdown
from backend.export.pdf import export_pdf
from backend.export.sarif import export_sarif
from backend.models.api import ExportFormat
from backend.models.state import Threat, ThreatsList


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])


def _build_threats_list(threat_rows: list[dict]) -> ThreatsList:
    """Reconstruct a ThreatsList from flat DB rows for SARIF export.

    Uses model_construct to skip Pydantic validation — persisted descriptions
    may not satisfy the 35-50 word constraint enforced at generation time.
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
            built.append(Threat.model_construct(**row))
        except Exception as exc:
            logger.warning("Skipping threat '%s' during SARIF build: %s", row.get("name"), exc)

    return ThreatsList.model_construct(threats=built)


@router.get("/{model_id}")
async def export_model(
    model_id: str,
    export_format: Annotated[ExportFormat, Query(alias="format")] = "markdown",
    status_filter: Annotated[str | None, Query()] = None,
) -> Response:
    """Export a threat model in the requested format.

    Query parameters:
    - format: markdown | pdf | sarif | json  (default: markdown)
    - status_filter: pending | approved | rejected | mitigated  (optional)
    """
    model = await crud.get_threat_model(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

    threats = await crud.list_threats(model_id, status=status_filter)
    assets = await crud.list_assets(model_id)
    flows = await crud.list_flows(model_id)
    trust_boundaries = await crud.list_trust_boundaries(model_id)

    title = model.get("title")
    framework = model.get("framework", "STRIDE")
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
            assets=assets,
            flows=flows,
            trust_boundaries=trust_boundaries,
            attack_trees=attack_trees or None,
            test_suites=test_suites or None,
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
            assets=assets,
            flows=flows,
            trust_boundaries=trust_boundaries,
            attack_trees=attack_trees or None,
            test_suites=test_suites or None,
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
            "assets": assets,
            "flows": flows,
            "trust_boundaries": trust_boundaries,
        },
        headers={
            "Content-Disposition": f'attachment; filename="{safe_title}.json"',
        },
    )
