"""Threat CRUD routes and on-demand enrichment (attack trees, test cases)."""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from backend.config import settings
from backend.db import crud
from backend.models.api import UpdateThreatRequest
from backend.pipeline.runner import PipelineConfig, PipelineRunner
from backend.providers.base import create_provider
from backend.routes._helpers import get_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/threats", tags=["threats"])


def _default_runner(model_id: str) -> PipelineRunner:
    """Create a PipelineRunner with default settings for on-demand enrichment calls."""
    provider_type = settings.default_provider
    model_str = settings.default_model
    api_key = get_api_key(provider_type)
    base_url = settings.ollama_base_url if provider_type == "ollama" else None

    provider = create_provider(
        provider_type=provider_type,
        model=model_str,
        api_key=api_key,
        base_url=base_url,
    )
    config = PipelineConfig(max_iterations=1, temperature=0.3)
    return PipelineRunner(provider=provider, config=config, model_id=model_id)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/{threat_id}")
async def get_threat(threat_id: str) -> JSONResponse:
    """Get a single threat by ID."""
    threat = await crud.get_threat(threat_id)
    if threat is None:
        raise HTTPException(status_code=404, detail=f"Threat '{threat_id}' not found")
    return JSONResponse(content=threat)


@router.patch("/{threat_id}")
async def update_threat(threat_id: str, body: UpdateThreatRequest) -> JSONResponse:
    """Update threat fields. Only provided fields are changed."""
    threat = await crud.get_threat(threat_id)
    if threat is None:
        raise HTTPException(status_code=404, detail=f"Threat '{threat_id}' not found")

    await crud.update_threat(
        threat_id,
        name=body.name,
        description=body.description,
        target=body.target,
        impact=body.impact.value if body.impact else None,
        likelihood=body.likelihood.value if body.likelihood else None,
        mitigations=body.mitigations,
        dread_damage=body.dread_damage,
        dread_reproducibility=body.dread_reproducibility,
        dread_exploitability=body.dread_exploitability,
        dread_affected_users=body.dread_affected_users,
        dread_discoverability=body.dread_discoverability,
        dread_score=None,  # recomputed client-side; not patched directly
    )

    # Handle status separately (uses dedicated update function)
    if body.status is not None:
        await crud.update_threat_status(threat_id, body.status.value)

    updated = await crud.get_threat(threat_id)
    return JSONResponse(content=updated)


@router.delete("/{threat_id}", status_code=204)
async def delete_threat(threat_id: str) -> None:
    """Delete a threat and its associated attack trees and test cases."""
    threat = await crud.get_threat(threat_id)
    if threat is None:
        raise HTTPException(status_code=404, detail=f"Threat '{threat_id}' not found")
    await crud.delete_threat(threat_id)


# ---------------------------------------------------------------------------
# Attack trees
# ---------------------------------------------------------------------------


@router.post("/{threat_id}/attack-tree", status_code=201)
async def generate_attack_tree(threat_id: str) -> JSONResponse:
    """Generate a Mermaid attack tree for a threat using the default LLM provider."""
    threat = await crud.get_threat(threat_id)
    if threat is None:
        raise HTTPException(status_code=404, detail=f"Threat '{threat_id}' not found")

    model_id = threat.get("model_id", "")
    runner = _default_runner(model_id)

    async with runner.provider:
        attack_tree = await runner.generate_attack_tree_for_threat(
            threat_id=threat_id,
            threat_name=threat["name"],
            threat_description=threat["description"],
            target=threat["target"],
            stride_category=threat.get("stride_category"),
            maestro_category=threat.get("maestro_category"),
            mitigations=threat["mitigations"],
        )

    tree_id = await crud.create_attack_tree(
        threat_id=threat_id,
        mermaid_source=attack_tree.mermaid_source,
    )

    record = await crud.get_attack_tree(tree_id)
    return JSONResponse(status_code=201, content=record)


@router.get("/{threat_id}/attack-trees")
async def list_attack_trees(threat_id: str) -> JSONResponse:
    """List all attack trees for a threat."""
    threat = await crud.get_threat(threat_id)
    if threat is None:
        raise HTTPException(status_code=404, detail=f"Threat '{threat_id}' not found")
    trees = await crud.list_attack_trees(threat_id)
    return JSONResponse(content=trees)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@router.post("/{threat_id}/test-cases", status_code=201)
async def generate_test_cases(threat_id: str) -> JSONResponse:
    """Generate Gherkin test cases for a threat using the default LLM provider."""
    threat = await crud.get_threat(threat_id)
    if threat is None:
        raise HTTPException(status_code=404, detail=f"Threat '{threat_id}' not found")

    model_id = threat.get("model_id", "")
    runner = _default_runner(model_id)

    async with runner.provider:
        test_suite = await runner.generate_test_cases_for_threat(
            threat_id=threat_id,
            threat_name=threat["name"],
            threat_description=threat["description"],
            target=threat["target"],
            mitigations=threat["mitigations"],
        )

    case_id = await crud.create_test_case(
        threat_id=threat_id,
        gherkin_source=test_suite.gherkin_source,
    )

    record = await crud.get_test_case(case_id)
    return JSONResponse(status_code=201, content=record)


@router.get("/{threat_id}/test-cases")
async def list_test_cases(threat_id: str) -> JSONResponse:
    """List all test cases for a threat."""
    threat = await crud.get_threat(threat_id)
    if threat is None:
        raise HTTPException(status_code=404, detail=f"Threat '{threat_id}' not found")
    cases = await crud.list_test_cases(threat_id)
    return JSONResponse(content=cases)
