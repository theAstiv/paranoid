"""Load everything the Markdown and PDF exports render for a stored model.

Shared by ``GET /export/{id}`` and the CLI's ``models export`` so the two can't
drift apart again: the CLI used to pass only the threats, description,
assumptions and gaps, so its reports had no assets, flows, trust boundaries,
attack trees, test cases, dependency findings or diagrams (B1, BB-69).
"""

from typing import Any

from backend.db import crud
from backend.db.gap_utils import decode_gap_summaries


async def gather_report_inputs(model: dict[str, Any], status: str | None = None) -> dict[str, Any]:
    """Keyword arguments for ``export_markdown`` / ``export_pdf`` for ``model``.

    ``model`` is a ``threat_models`` row. ``status`` limits the threats (and so
    their attack trees and test cases) to one review status.
    """
    model_id = model["id"]
    threats = await crud.list_threats(model_id, status=status)

    attack_trees: dict[str, dict[str, Any]] = {}
    test_suites: dict[str, dict[str, Any]] = {}
    for threat in threats:
        threat_id = threat.get("id") or ""
        if not threat_id:
            continue
        trees = await crud.list_attack_trees(threat_id)
        if trees:
            attack_trees[threat_id] = trees[-1]  # the most recent tree per threat
        cases = await crud.list_test_cases(threat_id)
        gherkin = "\n\n".join(c["gherkin_source"] for c in cases if c.get("gherkin_source"))
        if gherkin:
            test_suites[threat_id] = {"gherkin_source": gherkin}

    return {
        "threats": threats,
        "model_id": model_id,
        "framework": model.get("framework") or "STRIDE",
        "title": model.get("title"),
        "description": model.get("description") or None,
        "assumptions": decode_gap_summaries(model.get("assumptions")) or None,
        "assets": await crud.list_assets(model_id),
        "flows": await crud.list_flows(model_id),
        "trust_boundaries": await crud.list_trust_boundaries(model_id),
        "attack_trees": attack_trees or None,
        "test_suites": test_suites or None,
        "gap_summaries": decode_gap_summaries(model.get("gap_summaries")) or None,
        "dependency_scans": await crud.list_dependency_scans(model_id) or None,
        "diagrams": await crud.list_model_diagrams(model_id) or None,
    }
