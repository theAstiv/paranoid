"""Threat CRUD routes and on-demand enrichment (attack trees, test cases)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from backend.auth.dependencies import ROLE_ORDER, get_current_user, require_role
from backend.config import settings
from backend.db import crud, crud_activity, crud_projects, vectors
from backend.models.api import BulkStatusRequest, UpdateThreatRequest
from backend.pipeline.runner import PipelineConfig, PipelineRunner
from backend.providers.base import ProviderError, create_provider
from backend.routes._helpers import bedrock_kwargs, get_api_key, model_assignee_ids
from backend.security.rate_limit import enrichment_rate_limit


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
        **bedrock_kwargs(provider_type),
    )
    config = PipelineConfig(max_iterations=1, temperature=0.3)
    return PipelineRunner(provider=provider, config=config, model_id=model_id)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/{threat_id}")
async def get_threat(
    threat_id: str,
    _user: Annotated[dict | None, Depends(get_current_user)] = None,
) -> JSONResponse:
    """Get a single threat by ID."""
    threat = await crud.get_threat(threat_id)
    if threat is None:
        raise HTTPException(status_code=404, detail=f"Threat '{threat_id}' not found")
    return JSONResponse(content=threat)


@router.patch("/{threat_id}")
async def update_threat(
    threat_id: str,
    body: UpdateThreatRequest,
    user: Annotated[dict, Depends(get_current_user)],
    _authz: None = Depends(require_role("editor", "threat_id", "threat")),
) -> JSONResponse:
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

    if body.status is not None:
        was_approved = threat.get("status") == "approved"
        is_approved = body.status.value == "approved"
        if is_approved:
            await _embed_approved_threat(updated)
        elif was_approved:
            await _remove_threat_vector(threat_id)

        if body.status.value != threat.get("status"):
            model_id = threat["model_id"]
            project_id = await crud_projects.resolve_project_id_from_model(model_id)
            await crud_activity.safe_log_activity(
                project_id=project_id,
                user_id=user["id"],
                entity_type="threat",
                entity_id=threat_id,
                action="status_changed",
                details={"from": threat.get("status"), "to": body.status.value},
            )
            await crud_activity.safe_notify_users(
                await model_assignee_ids(model_id, exclude=user["id"]),
                notification_type="threat_status_changed",
                title=f'Threat "{(updated or {}).get("name", threat_id)}" was {body.status.value}',
                entity_type="threat",
                entity_id=threat_id,
            )

    return JSONResponse(content=updated)


@router.post("/bulk-status")
async def bulk_status(
    body: BulkStatusRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> JSONResponse:
    """Bulk-update threat status. All threats must belong to the same model."""
    threats = await crud.get_threats_by_ids(body.threat_ids)
    if len(threats) != len(body.threat_ids):
        found = {t["id"] for t in threats}
        missing = [tid for tid in body.threat_ids if tid not in found]
        raise HTTPException(status_code=404, detail=f"Threats not found: {missing}")

    model_ids = {t["model_id"] for t in threats}
    if len(model_ids) > 1:
        raise HTTPException(status_code=400, detail="All threats must belong to the same model")
    model_id = model_ids.pop()

    if settings.paranoid_require_auth and not user.get("is_admin"):
        project_id = await crud_projects.resolve_project_id_from_model(model_id)
        role = await crud_projects.get_user_role_in_project(project_id, user["id"])
        if role is None or ROLE_ORDER.get(role, 0) < ROLE_ORDER["editor"]:
            raise HTTPException(status_code=403, detail="Requires editor role")

    updated = await crud.bulk_update_threat_status(body.threat_ids, body.status.value)

    new_status = body.status.value
    for prior in threats:
        was_approved = prior.get("status") == "approved"
        is_approved = new_status == "approved"
        if is_approved and not was_approved:
            # Use already-fetched data — _embed_approved_threat only needs
            # id, model_id, name, description (status doesn't matter for embedding)
            await _embed_approved_threat(prior)
        elif was_approved and not is_approved:
            await _remove_threat_vector(prior["id"])

    project_id = await crud_projects.resolve_project_id_from_model(model_id)
    await crud_activity.safe_log_activity(
        project_id=project_id,
        user_id=user["id"],
        entity_type="model",
        entity_id=model_id,
        action="bulk_status_changed",
        details={"count": updated, "status": new_status},
    )
    assignee_ids = await model_assignee_ids(model_id, exclude=user["id"])
    if assignee_ids:
        await crud_activity.safe_notify_users(
            assignee_ids,
            notification_type="threat_status_changed",
            title=f"{updated} threats bulk-{new_status}",
            entity_type="model",
            entity_id=model_id,
        )

    return JSONResponse(content={"updated": updated})


@router.delete("/{threat_id}", status_code=204)
async def delete_threat(
    threat_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    _authz: None = Depends(require_role("editor", "threat_id", "threat")),
) -> None:
    """Delete a threat and its associated attack trees and test cases."""
    threat = await crud.get_threat(threat_id)
    if threat is None:
        raise HTTPException(status_code=404, detail=f"Threat '{threat_id}' not found")
    # Must run before crud.delete_threat: threat_metadata cascades on threat
    # deletion, so delete_threat_vector's lookup would find nothing afterward,
    # orphaning the threat_vectors row.
    await _remove_threat_vector(threat_id)
    await crud.delete_threat(threat_id)
    project_id = await crud_projects.resolve_project_id_from_model(threat["model_id"])
    await crud_activity.safe_log_activity(
        project_id=project_id,
        user_id=user["id"],
        entity_type="threat",
        entity_id=threat_id,
        action="deleted",
        details={"name": threat.get("name")},
    )


# ---------------------------------------------------------------------------
# RAG vector maintenance (best-effort — never blocks the approve/reject UX)
# ---------------------------------------------------------------------------


async def _embed_approved_threat(threat: dict) -> None:
    try:
        project_id = await crud_projects.resolve_project_id_from_model(threat["model_id"])
        text = f"{threat['name']} {threat['description']}"
        await vectors.upsert_threat_vector(
            threat_id=threat["id"],
            text=text,
            source="approved",
            project_id=project_id,
        )
    except Exception as exc:
        logger.warning(f"Failed to embed approved threat {threat['id']}: {exc}")


async def _remove_threat_vector(threat_id: str) -> None:
    try:
        await vectors.delete_threat_vector(threat_id)
    except Exception as exc:
        logger.warning(f"Failed to remove vector for threat {threat_id}: {exc}")


# ---------------------------------------------------------------------------
# Attack trees
# ---------------------------------------------------------------------------


@router.post("/{threat_id}/attack-tree", status_code=201)
async def generate_attack_tree(
    threat_id: str,
    _rate: None = Depends(enrichment_rate_limit),
    _authz: None = Depends(require_role("editor", "threat_id", "threat")),
) -> JSONResponse:
    """Generate a Mermaid attack tree for a threat using the default LLM provider."""
    threat = await crud.get_threat(threat_id)
    if threat is None:
        raise HTTPException(status_code=404, detail=f"Threat '{threat_id}' not found")

    model_id = threat.get("model_id", "")

    try:
        runner = _default_runner(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
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
    except ProviderError as exc:
        logger.error("Provider error generating attack tree for %s: %s", threat_id, exc)
        raise HTTPException(status_code=503, detail=f"LLM provider error: {exc.message}")

    tree_id = await crud.create_attack_tree(
        threat_id=threat_id,
        mermaid_source=attack_tree.mermaid_source,
    )

    record = await crud.get_attack_tree(tree_id)
    return JSONResponse(status_code=201, content=record)


@router.get("/{threat_id}/attack-trees")
async def list_attack_trees(
    threat_id: str,
    _user: Annotated[dict | None, Depends(get_current_user)] = None,
) -> JSONResponse:
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
async def generate_test_cases(
    threat_id: str,
    _rate: None = Depends(enrichment_rate_limit),
    _authz: None = Depends(require_role("editor", "threat_id", "threat")),
) -> JSONResponse:
    """Generate Gherkin test cases for a threat using the default LLM provider."""
    threat = await crud.get_threat(threat_id)
    if threat is None:
        raise HTTPException(status_code=404, detail=f"Threat '{threat_id}' not found")

    model_id = threat.get("model_id", "")

    try:
        runner = _default_runner(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        async with runner.provider:
            test_suite = await runner.generate_test_cases_for_threat(
                threat_id=threat_id,
                threat_name=threat["name"],
                threat_description=threat["description"],
                target=threat["target"],
                mitigations=threat["mitigations"],
            )
    except ProviderError as exc:
        logger.error("Provider error generating test cases for %s: %s", threat_id, exc)
        raise HTTPException(status_code=503, detail=f"LLM provider error: {exc.message}")

    case_id = await crud.create_test_case(
        threat_id=threat_id,
        gherkin_source=test_suite.gherkin_source,
    )

    record = await crud.get_test_case(case_id)
    return JSONResponse(status_code=201, content=record)


@router.get("/{threat_id}/test-cases")
async def list_test_cases(
    threat_id: str,
    _user: Annotated[dict | None, Depends(get_current_user)] = None,
) -> JSONResponse:
    """List all test cases for a threat."""
    threat = await crud.get_threat(threat_id)
    if threat is None:
        raise HTTPException(status_code=404, detail=f"Threat '{threat_id}' not found")
    cases = await crud.list_test_cases(threat_id)
    return JSONResponse(content=cases)
