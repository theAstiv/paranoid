"""Threat model CRUD routes and pipeline SSE streaming."""

import base64
import json
import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from backend.config import settings
from backend.db import crud
from backend.models.api import CreateModelRequest, UpdateModelRequest
from backend.models.enums import DiagramFormat, Framework, ModelStatus, ThreatStatus
from backend.models.extended import DiagramData
from backend.pipeline.runner import PipelineEvent, PipelineStep, run_pipeline_for_model
from backend.providers.base import create_provider
from backend.routes._helpers import get_api_key, resolve_provider

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
    provider_type, model_id_str = resolve_provider(
        body.provider.value if body.provider else None
    )

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
# Pipeline SSE stream
# ---------------------------------------------------------------------------


@router.post("/{model_id}/run")
async def run_pipeline(
    model_id: str,
    assumptions: Annotated[str, Form()] = "[]",
    temperature: Annotated[float, Form()] = 0.2,
    has_ai_components: Annotated[bool, Form()] = False,
    diagram: Annotated[UploadFile | None, File()] = None,
) -> StreamingResponse:
    """Run the threat modeling pipeline, streaming SSE progress events.

    Accepts multipart/form-data:
    - assumptions: JSON array string, e.g. '["TLS is enforced","Auth is OAuth2"]'
    - temperature: float 0.0–1.0 (default 0.2)
    - has_ai_components: bool, enables MAESTRO alongside STRIDE
    - diagram: optional PNG/JPG/Mermaid file upload
    """
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

    # Resolve provider
    provider_type = record.get("provider") or settings.default_provider
    model_str = record.get("model") or settings.default_model
    api_key = get_api_key(provider_type)
    base_url = settings.ollama_base_url if provider_type == "ollama" else None

    try:
        provider = create_provider(
            provider_type=provider_type,
            model=model_str,
            api_key=api_key,
            base_url=base_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    framework = Framework(record.get("framework", "STRIDE"))
    max_iterations = record.get("iteration_count", settings.default_iterations)

    async def event_generator() -> AsyncGenerator[str, None]:
        await crud.update_threat_model_status(model_id, ModelStatus.IN_PROGRESS.value)
        try:
            async with provider:
                async for event in run_pipeline_for_model(
                    model_id=model_id,
                    description=record["description"],
                    framework=framework,
                    provider=provider,
                    assumptions=parsed_assumptions or None,
                    diagram_data=diagram_data,
                    max_iterations=max_iterations,
                    has_ai_components=has_ai_components,
                ):
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
