"""Threat model CRUD routes and pipeline SSE streaming."""

import base64
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from backend.config import settings
from backend.db import crud
from backend.mcp.client import MCPCodeExtractor
from backend.mcp.errors import MCPBinaryNotFoundError
from backend.models.api import (
    AnalyzeDescriptionResponse,
    CreateAssetRequest,
    CreateFlowRequest,
    CreateModelRequest,
    CreateTrustBoundaryRequest,
    UpdateAssetRequest,
    UpdateFlowRequest,
    UpdateModelRequest,
    UpdateTrustBoundaryRequest,
)
from backend.models.enums import DiagramFormat, Framework, ModelStatus, ThreatStatus
from backend.models.extended import CodeContext, DiagramData
from backend.models.state import AssetsList, FlowsList, ThreatsList
from backend.pipeline.pre_flight import analyze_description_gaps
from backend.pipeline.runner import PipelineEvent, PipelineStep, run_pipeline_for_model
from backend.routes._helpers import (
    build_fast_provider,
    build_provider_from_record,
    resolve_provider,
)
from backend.sources.paths import clone_dir_for


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])

_MAX_DIAGRAM_BYTES = 5 * 1024 * 1024  # 5 MB


async def _build_diagram_data(upload: UploadFile) -> DiagramData:
    """Build DiagramData from an uploaded file."""
    filename = upload.filename or ""
    content_type = upload.content_type or ""
    raw = await upload.read()

    if len(raw) > _MAX_DIAGRAM_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Diagram file exceeds 5 MB limit ({len(raw)} bytes)",
        )

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in ("mmd", "txt") or "mermaid" in content_type:
        return DiagramData(
            format=DiagramFormat.MERMAID,
            source_path=filename,
            mermaid_source=raw.decode("utf-8", errors="replace"),
        )

    if ext in ("jpg", "jpeg") or "jpeg" in content_type:
        fmt = DiagramFormat.JPEG
        media_type = "image/jpeg"
    else:
        fmt = DiagramFormat.PNG
        media_type = "image/png"

    return DiagramData(
        format=fmt,
        source_path=filename,
        base64_data=base64.b64encode(raw).decode("ascii"),
        media_type=media_type,
        size_bytes=len(raw),
    )


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post("/", status_code=201)
async def create_model(body: CreateModelRequest) -> JSONResponse:
    """Create a new threat model record."""
    provider_type, model_id_str = resolve_provider(body.provider.value if body.provider else None)

    model_id = await crud.create_threat_model(
        title=body.title,
        description=body.description,
        provider=provider_type,
        model=model_id_str,
        framework=body.framework.value,
        iteration_count=body.iteration_count,
    )

    record = await crud.get_threat_model(model_id)
    return JSONResponse(status_code=201, content=record)


@router.get("/")
async def list_models(
    limit: int = 50,
    framework: str | None = None,
    status: str | None = None,
) -> JSONResponse:
    """List threat models, optionally filtered by framework or status."""
    rows = await crud.list_threat_models(
        limit=limit,
        framework=framework,
        status=status,
    )
    return JSONResponse(content=rows)


@router.get("/{model_id}")
async def get_model(model_id: str) -> JSONResponse:
    """Get a single threat model with its threats."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

    threats = await crud.list_threats(model_id)
    record["threats"] = threats
    return JSONResponse(content=record)


@router.patch("/{model_id}")
async def update_model(model_id: str, body: UpdateModelRequest) -> JSONResponse:
    """Update threat model metadata."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

    await crud.update_threat_model(
        model_id,
        title=body.title,
        description=body.description,
        framework=body.framework.value if body.framework else None,
        status=body.status.value if body.status else None,
    )

    updated = await crud.get_threat_model(model_id)
    return JSONResponse(content=updated)


@router.delete("/{model_id}", status_code=204)
async def delete_model(model_id: str) -> None:
    """Delete a threat model and all associated data."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    await crud.delete_threat_model(model_id)


# ---------------------------------------------------------------------------
# Pipeline persistence helpers
# ---------------------------------------------------------------------------


async def _persist_pipeline_event(model_id: str, event: PipelineEvent) -> None:
    """Persist data from a pipeline event to the database.

    Called for every event; only completed extract_assets, extract_flows, and
    complete events trigger DB writes. Failures are logged and swallowed so
    that a DB error never interrupts the SSE stream.
    """
    if not event.data or event.status != "completed":
        return

    if event.step == PipelineStep.EXTRACT_ASSETS:
        assets_list: AssetsList | None = event.data.get("assets")
        if assets_list and hasattr(assets_list, "assets"):
            for asset in assets_list.assets:
                try:
                    await crud.create_asset(
                        model_id=model_id,
                        asset_type=asset.type.value,
                        name=asset.name,
                        description=asset.description,
                    )
                except Exception:
                    logger.warning("Failed to persist asset '%s'", asset.name, exc_info=True)

    elif event.step == PipelineStep.EXTRACT_FLOWS:
        flows_list: FlowsList | None = event.data.get("flows")
        if flows_list and hasattr(flows_list, "data_flows"):
            for flow in flows_list.data_flows:
                try:
                    await crud.create_flow(
                        model_id=model_id,
                        flow_type="data",
                        flow_description=flow.flow_description,
                        source_entity=flow.source_entity,
                        target_entity=flow.target_entity,
                    )
                except Exception:
                    logger.warning(
                        "Failed to persist flow '%s → %s'",
                        flow.source_entity,
                        flow.target_entity,
                        exc_info=True,
                    )
            for boundary in flows_list.trust_boundaries:
                try:
                    await crud.create_trust_boundary(
                        model_id=model_id,
                        purpose=boundary.purpose,
                        source_entity=boundary.source_entity,
                        target_entity=boundary.target_entity,
                    )
                except Exception:
                    logger.warning(
                        "Failed to persist trust boundary '%s → %s'",
                        boundary.source_entity,
                        boundary.target_entity,
                        exc_info=True,
                    )

    elif event.step == PipelineStep.COMPLETE:
        threats_list: ThreatsList | None = event.data.get("threats")
        if threats_list and hasattr(threats_list, "threats"):
            for threat in threats_list.threats:
                try:
                    dread = threat.dread
                    await crud.create_threat(
                        model_id=model_id,
                        name=threat.name,
                        description=threat.description,
                        target=threat.target,
                        impact=threat.impact,
                        likelihood=threat.likelihood,
                        mitigations=threat.mitigations,
                        stride_category=(
                            threat.stride_category.value if threat.stride_category else None
                        ),
                        maestro_category=None,
                        dread_score=dread.score if dread else None,
                        dread_damage=dread.damage if dread else None,
                        dread_reproducibility=dread.reproducibility if dread else None,
                        dread_exploitability=dread.exploitability if dread else None,
                        dread_affected_users=dread.affected_users if dread else None,
                        dread_discoverability=dread.discoverability if dread else None,
                    )
                except Exception:
                    logger.warning(
                        "Failed to persist threat '%s'",
                        getattr(threat, "name", "unknown"),
                        exc_info=True,
                    )


# ---------------------------------------------------------------------------
# Pipeline SSE stream
# ---------------------------------------------------------------------------


@router.post("/{model_id}/run")
async def run_pipeline(
    model_id: str,
    assumptions: Annotated[str, Form()] = "[]",
    has_ai_components: Annotated[bool, Form()] = False,
    diagram: Annotated[UploadFile | None, File()] = None,
    code_source_id: Annotated[str, Form()] = "",
) -> StreamingResponse:
    """Run the threat modeling pipeline, streaming SSE progress events.

    Accepts multipart/form-data:
    - assumptions: JSON array string, e.g. '["TLS is enforced","Auth is OAuth2"]'
    - has_ai_components: bool, enables MAESTRO alongside STRIDE
    - diagram: optional PNG/JPG/Mermaid file upload
    - code_source_id: optional ID of a ready code source for code context
    """
    code_source_id = code_source_id.strip() or ""

    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

    # Parse assumptions JSON array
    try:
        parsed_assumptions: list[str] = json.loads(assumptions) if assumptions.strip() else []
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=422,
            detail="'assumptions' must be a JSON array string, e.g. '[\"assumption 1\"]'",
        )

    # Build DiagramData if a file was uploaded
    diagram_data: DiagramData | None = None
    if diagram is not None and diagram.filename:
        diagram_data = await _build_diagram_data(diagram)

    # Validate code source — fast fail before opening the SSE stream.
    source_row: dict | None = None
    if code_source_id:
        source_row = await crud.get_code_source(code_source_id)
        if source_row is None:
            raise HTTPException(
                status_code=422, detail=f"Code source '{code_source_id}' not found."
            )
        if source_row["last_index_status"] != "ready":
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Code source is not indexed yet (status: {source_row['last_index_status']}). "
                    "Wait for status 'ready'."
                ),
            )

    provider = build_provider_from_record(record)
    fast_provider = build_fast_provider(record)
    framework = Framework(record.get("framework", "STRIDE"))
    max_iterations = record.get("iteration_count", settings.default_iterations)

    async def event_generator() -> AsyncGenerator[str, None]:
        # Clear any previous run's data so re-runs start clean
        await crud.clear_model_data(model_id)
        await crud.update_threat_model_status(model_id, ModelStatus.IN_PROGRESS.value)

        # Extract code context from the indexed clone directory (if requested).
        # This runs inside the SSE stream so the user sees extraction progress.
        # Any failure degrades gracefully — the pipeline continues without code context.
        code_context: CodeContext | None = None
        if source_row is not None:
            yield PipelineEvent(
                step=PipelineStep.SUMMARIZE_CODE,
                status="started",
                message=f"Extracting code context from '{source_row['name']}'...",
            ).to_sse_format()
            try:
                async with MCPCodeExtractor(str(clone_dir_for(code_source_id))) as extractor:
                    code_context = await extractor.extract_context(record["description"])
                yield PipelineEvent(
                    step=PipelineStep.SUMMARIZE_CODE,
                    status="completed",
                    message=(
                        f"Extracted {len(code_context.files)} code files "
                        f"from '{source_row['name']}'"
                    ),
                ).to_sse_format()
            except MCPBinaryNotFoundError as exc:
                logger.warning("context-link binary not found, skipping code context: %s", exc)
                yield PipelineEvent(
                    step=PipelineStep.SUMMARIZE_CODE,
                    status="failed",
                    message="context-link binary not found — continuing without code context.",
                ).to_sse_format()
            except Exception as exc:
                logger.warning(
                    "Code context extraction failed for source %s: %s", code_source_id, exc
                )
                yield PipelineEvent(
                    step=PipelineStep.SUMMARIZE_CODE,
                    status="failed",
                    message=f"Code context unavailable — continuing without: {str(exc)[:200]}",
                ).to_sse_format()

        try:
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(provider)
                if fast_provider is not None and fast_provider is not provider:
                    await stack.enter_async_context(fast_provider)
                async for event in run_pipeline_for_model(
                    model_id=model_id,
                    description=record["description"],
                    framework=framework,
                    provider=provider,
                    fast_provider=fast_provider,
                    assumptions=parsed_assumptions or None,
                    diagram_data=diagram_data,
                    code_context=code_context,
                    max_iterations=max_iterations,
                    has_ai_components=has_ai_components,
                ):
                    await _persist_pipeline_event(model_id, event)
                    yield event.to_sse_format()

            await crud.update_threat_model_status(model_id, ModelStatus.COMPLETED.value)
        except Exception as exc:
            await crud.update_threat_model_status(model_id, ModelStatus.FAILED.value)
            yield PipelineEvent(
                step=PipelineStep.COMPLETE,
                status="failed",
                message=str(exc),
            ).to_sse_format()
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Sub-resource read endpoints
# ---------------------------------------------------------------------------


@router.get("/{model_id}/threats")
async def list_model_threats(
    model_id: str,
    status: str | None = None,
) -> JSONResponse:
    """List threats for a model, optionally filtered by status."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

    # Validate status value if provided
    if status is not None:
        try:
            ThreatStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status '{status}'. Valid values: {[s.value for s in ThreatStatus]}",
            )

    threats = await crud.list_threats(model_id, status=status)
    return JSONResponse(content=threats)


@router.get("/{model_id}/assets")
async def list_model_assets(model_id: str) -> JSONResponse:
    """List extracted assets for a model."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    assets = await crud.list_assets(model_id)
    return JSONResponse(content=assets)


@router.get("/{model_id}/flows")
async def list_model_flows(model_id: str) -> JSONResponse:
    """List extracted data flows for a model."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    flows = await crud.list_flows(model_id)
    return JSONResponse(content=flows)


@router.get("/{model_id}/trust-boundaries")
async def list_model_trust_boundaries(model_id: str) -> JSONResponse:
    """List extracted trust boundaries for a model."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    boundaries = await crud.list_trust_boundaries(model_id)
    return JSONResponse(content=boundaries)


@router.get("/{model_id}/stats")
async def get_model_stats(model_id: str) -> JSONResponse:
    """Get pipeline execution statistics for a model."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    stats = await crud.get_pipeline_stats(model_id)
    return JSONResponse(content=stats)


# ---------------------------------------------------------------------------
# Asset write routes
# ---------------------------------------------------------------------------


@router.post("/{model_id}/assets", status_code=201)
async def create_asset(model_id: str, body: CreateAssetRequest) -> JSONResponse:
    """Add an asset to a model."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    asset_id = await crud.create_asset(
        model_id=model_id,
        asset_type=body.type,
        name=body.name,
        description=body.description,
    )
    asset = await crud.get_asset(asset_id)
    return JSONResponse(status_code=201, content=asset)


@router.patch("/{model_id}/assets/{asset_id}")
async def update_asset(model_id: str, asset_id: str, body: UpdateAssetRequest) -> JSONResponse:
    """Update an asset."""
    asset = await crud.get_asset(asset_id)
    if asset is None or asset.get("model_id") != model_id:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")
    await crud.update_asset(
        asset_id,
        name=body.name,
        description=body.description,
        asset_type=body.type,
    )
    updated = await crud.get_asset(asset_id)
    return JSONResponse(content=updated)


@router.delete("/{model_id}/assets/{asset_id}", status_code=204)
async def delete_asset(model_id: str, asset_id: str) -> None:
    """Delete an asset."""
    asset = await crud.get_asset(asset_id)
    if asset is None or asset.get("model_id") != model_id:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")
    await crud.delete_asset(asset_id)


# ---------------------------------------------------------------------------
# Flow write routes
# ---------------------------------------------------------------------------


@router.post("/{model_id}/flows", status_code=201)
async def create_flow(model_id: str, body: CreateFlowRequest) -> JSONResponse:
    """Add a data flow to a model."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    flow_id = await crud.create_flow(
        model_id=model_id,
        flow_type=body.flow_type,
        flow_description=body.flow_description,
        source_entity=body.source_entity,
        target_entity=body.target_entity,
    )
    flow = await crud.get_flow(flow_id)
    return JSONResponse(status_code=201, content=flow)


@router.patch("/{model_id}/flows/{flow_id}")
async def update_flow(model_id: str, flow_id: str, body: UpdateFlowRequest) -> JSONResponse:
    """Update a data flow."""
    flow = await crud.get_flow(flow_id)
    if flow is None or flow.get("model_id") != model_id:
        raise HTTPException(status_code=404, detail=f"Flow '{flow_id}' not found")
    await crud.update_flow(
        flow_id,
        flow_type=body.flow_type,
        flow_description=body.flow_description,
        source_entity=body.source_entity,
        target_entity=body.target_entity,
    )
    updated = await crud.get_flow(flow_id)
    return JSONResponse(content=updated)


@router.delete("/{model_id}/flows/{flow_id}", status_code=204)
async def delete_flow(model_id: str, flow_id: str) -> None:
    """Delete a data flow."""
    flow = await crud.get_flow(flow_id)
    if flow is None or flow.get("model_id") != model_id:
        raise HTTPException(status_code=404, detail=f"Flow '{flow_id}' not found")
    await crud.delete_flow(flow_id)


# ---------------------------------------------------------------------------
# Trust boundary write routes
# ---------------------------------------------------------------------------


@router.post("/{model_id}/trust-boundaries", status_code=201)
async def create_trust_boundary(model_id: str, body: CreateTrustBoundaryRequest) -> JSONResponse:
    """Add a trust boundary to a model."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    boundary_id = await crud.create_trust_boundary(
        model_id=model_id,
        purpose=body.purpose,
        source_entity=body.source_entity,
        target_entity=body.target_entity,
    )
    boundary = await crud.get_trust_boundary(boundary_id)
    return JSONResponse(status_code=201, content=boundary)


@router.patch("/{model_id}/trust-boundaries/{boundary_id}")
async def update_trust_boundary(
    model_id: str, boundary_id: str, body: UpdateTrustBoundaryRequest
) -> JSONResponse:
    """Update a trust boundary."""
    boundary = await crud.get_trust_boundary(boundary_id)
    if boundary is None or boundary.get("model_id") != model_id:
        raise HTTPException(status_code=404, detail=f"Trust boundary '{boundary_id}' not found")
    await crud.update_trust_boundary(
        boundary_id,
        purpose=body.purpose,
        source_entity=body.source_entity,
        target_entity=body.target_entity,
    )
    updated = await crud.get_trust_boundary(boundary_id)
    return JSONResponse(content=updated)


@router.delete("/{model_id}/trust-boundaries/{boundary_id}", status_code=204)
async def delete_trust_boundary(model_id: str, boundary_id: str) -> None:
    """Delete a trust boundary."""
    boundary = await crud.get_trust_boundary(boundary_id)
    if boundary is None or boundary.get("model_id") != model_id:
        raise HTTPException(status_code=404, detail=f"Trust boundary '{boundary_id}' not found")
    await crud.delete_trust_boundary(boundary_id)


# ---------------------------------------------------------------------------
# Pre-flight and context-extraction endpoints
# ---------------------------------------------------------------------------


@router.post("/{model_id}/analyze")
async def analyze_model_description(model_id: str) -> AnalyzeDescriptionResponse:
    """Analyze the model's description for completeness gaps.

    Runs fast deterministic checks plus an LLM pass to identify what is missing
    before committing to a full pipeline run. Returns a list of gaps with severity
    and an is_sufficient flag.
    """
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

    description = record.get("description", "")
    provider = build_provider_from_record(record)

    async with provider:
        return await analyze_description_gaps(description=description, provider=provider)


@router.post("/{model_id}/extract")
async def extract_model_context(model_id: str) -> StreamingResponse:
    """Run only the summarize + extract steps (no threat generation), streaming SSE.

    Populates assets, flows, and trust boundaries in the DB so the user can
    review and edit them before triggering a full pipeline run. The SSE stream
    ends with a 'complete' event once extraction is done.
    """
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

    provider = build_provider_from_record(record)
    fast_provider = build_fast_provider(record)
    framework = Framework(record.get("framework", "STRIDE"))

    async def event_generator() -> AsyncGenerator[str, None]:
        await crud.clear_model_data(model_id, preserve_user_edits=True)
        try:
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(provider)
                if fast_provider is not None and fast_provider is not provider:
                    await stack.enter_async_context(fast_provider)
                async for event in run_pipeline_for_model(
                    model_id=model_id,
                    description=record["description"],
                    framework=framework,
                    provider=provider,
                    fast_provider=fast_provider,
                    stop_after="extraction",
                ):
                    await _persist_pipeline_event(model_id, event)
                    yield event.to_sse_format()
        except Exception:
            logger.exception("Extraction pipeline failed for model %s", model_id)
            yield PipelineEvent(
                step=PipelineStep.COMPLETE,
                status="failed",
                message="Extraction failed; see server logs.",
            ).to_sse_format()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
