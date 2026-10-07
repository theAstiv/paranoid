"""Threat model CRUD routes and pipeline SSE streaming."""

import asyncio
import base64
import binascii
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from backend.auth.dependencies import get_current_user, require_role
from backend.config import settings
from backend.db import crud, crud_activity, crud_projects
from backend.db.gap_utils import decode_gap_summaries
from backend.deps.analyze import (
    DEFAULT_MAX_DIRECT_DEPENDENCIES,
    count_resolvable_direct_dependencies,
    dependency_scan_rows,
)
from backend.image import (
    MAX_DIAGRAMS,
    MAX_IMAGE_SIZE_BYTES,
    MAX_MERMAID_SIZE_BYTES,
    MAX_TOTAL_IMAGE_BYTES,
    MAX_TOTAL_MERMAID_BYTES,
    format_for_extension,
    image_byte_length,
    sanitize_diagram_name,
    validate_diagram_bytes,
    validate_diagram_set,
)
from backend.image.errors import DiagramValidationError
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
from backend.models.enums import (
    DiagramFormat,
    Framework,
    ModelStatus,
    ThreatStatus,
    is_valid_model_status_transition,
)
from backend.models.extended import CodeContext, DiagramData
from backend.models.state import AssetsList, FlowsList, ThreatsList
from backend.pipeline.confidence import score_threat_confidence
from backend.pipeline.pre_flight import analyze_description_gaps
from backend.pipeline.runner import PipelineEvent, PipelineStep, run_pipeline_for_model
from backend.routes._helpers import (
    build_fast_provider,
    build_provider_from_record,
    model_assignee_ids,
    resolve_provider,
)
from backend.scoring.cvss31 import to_vector_string
from backend.security.rate_limit import pipeline_rate_limit, write_rate_limit
from backend.sources.paths import clone_dir_for, index_db_for


logger = logging.getLogger(__name__)


def _decode_json_field(value: str | None) -> dict | None:
    """Parse a JSON-encoded DB column; return None on missing or invalid input."""
    if not value:
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


router = APIRouter(prefix="/models", tags=["models"])

_MAX_MANIFEST_BYTES = 1024 * 1024  # 1 MB — package.json itself is never large
_MAX_LOCKFILE_BYTES = 20 * 1024 * 1024  # 20 MB — real package-lock.json files
# from large monorepos routinely exceed 1 MB
_VALID_DEPS_SOURCE_MODES = frozenset({"npm", "both"})


async def _build_diagram_data(upload: UploadFile, *, name_hint: str | None = None) -> DiagramData:
    """Build DiagramData from one uploaded file: a bounded read, then full
    content validation (Pillow for images; size/UTF-8 for Mermaid).

    The bounded read (`upload.read(cap + 1)`) protects this handler's own
    memory use — Starlette has already received the whole request and
    spooled it to a temp file before this handler runs, so it doesn't stop
    an oversize request early, only how much of it this function holds at
    once. `validate_diagram_bytes` is CPU-bound (Pillow decode), so it runs
    via `asyncio.to_thread` rather than blocking the event loop.
    """
    filename = upload.filename or "diagram"
    try:
        diagram_format = format_for_extension(filename)
    except DiagramValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    cap = (
        MAX_MERMAID_SIZE_BYTES if diagram_format == DiagramFormat.MERMAID else MAX_IMAGE_SIZE_BYTES
    )
    raw = await upload.read(cap + 1)
    if len(raw) > cap:
        raise HTTPException(
            status_code=413,
            detail=f"'{filename}' exceeds the {cap} byte limit for its type",
        )

    try:
        await asyncio.to_thread(validate_diagram_bytes, filename, raw)
    except DiagramValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    name = sanitize_diagram_name(name_hint or Path(filename).stem)

    if diagram_format == DiagramFormat.MERMAID:
        return DiagramData(
            format=DiagramFormat.MERMAID,
            source_path=filename,
            mermaid_source=raw.decode("utf-8"),
            name=name,
        )

    media_type = "image/jpeg" if diagram_format == DiagramFormat.JPEG else "image/png"
    return DiagramData(
        format=diagram_format,
        source_path=filename,
        base64_data=base64.b64encode(raw).decode("ascii"),
        media_type=media_type,
        size_bytes=len(raw),
        name=name,
    )


async def _build_diagrams_from_request(
    diagram: UploadFile | None,
    diagrams: list[UploadFile] | None,
    diagram_names: str | None,
) -> list[DiagramData]:
    """Build the full diagram set for a run from the request's upload fields.

    `diagram` is the deprecated singular field (kept for one release); when
    present it's merged in first (position 0). `diagrams` is the current
    multi-file field; `diagram_names` optionally labels those files (not the
    deprecated `diagram` field) — a JSON array of strings the same length as
    `diagrams`, empty strings falling back to the file's own stem.

    Returns an empty list when nothing was uploaded (the caller then
    decides whether to reuse stored diagrams). Raises HTTPException (422/413)
    for any malformed or over-limit upload, before any SSE stream opens.
    """
    diagram_files = [f for f in (diagrams or []) if f.filename]
    shim_file = diagram if diagram is not None and diagram.filename else None

    names: list[str | None] = [None] * len(diagram_files)
    if diagram_names is not None:
        try:
            parsed_names = json.loads(diagram_names)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=422, detail="'diagram_names' must be a JSON array string"
            )
        if not isinstance(parsed_names, list) or not all(isinstance(n, str) for n in parsed_names):
            raise HTTPException(
                status_code=422, detail="'diagram_names' must be a JSON array of strings"
            )
        if len(parsed_names) != len(diagram_files):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"diagram_names has {len(parsed_names)} entries for {len(diagram_files)} files"
                ),
            )
        names = [n or None for n in parsed_names]

    total_uploaded = len(diagram_files) + (1 if shim_file else 0)
    if total_uploaded > MAX_DIAGRAMS:
        detail = f"Too many diagrams: {total_uploaded} uploaded"
        if shim_file:
            detail += " (including the deprecated `diagram` field)"
        detail += f"; the limit is {MAX_DIAGRAMS}."
        raise HTTPException(status_code=422, detail=detail)

    built: list[DiagramData] = []
    if shim_file:
        built.append(await _build_diagram_data(shim_file))
    for upload, name in zip(diagram_files, names, strict=True):
        built.append(await _build_diagram_data(upload, name_hint=name))

    if not built:
        return []

    try:
        return validate_diagram_set(built)
    except DiagramValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


async def _persist_diagram_data(model_id: str, diagrams: list[DiagramData]) -> None:
    """Store an uploaded diagram set so it survives a page reload (Results tab).

    Unlike dependency_scans, diagrams are user input, not pipeline output —
    they're replaced here only because a new set was actually uploaded,
    never wiped by clear_model_data() on a re-run that didn't upload one
    (see crud.replace_model_diagrams's docstring). The delete-old +
    insert-new sequence is atomic (one commit) so a failed insert can't
    leave the model with no diagrams at all.
    """
    await crud.replace_model_diagrams(model_id, [crud.diagram_data_to_row(d) for d in diagrams])


async def _load_stored_diagrams_for_reuse(
    model_id: str,
) -> tuple[list[DiagramData], list[dict[str, str]]]:
    """Reconstruct a model's stored diagrams for a re-run/re-extract that
    didn't upload a new set.

    Stored rows are re-checked against today's limits — a row saved under a
    looser cap in an earlier release can now exceed a lowered one, and the
    4b-1 upload route did no content check at all (any file up to 5MB,
    unknown extensions treated as PNG), so a stored row can also be a
    corrupt file or a non-image that would otherwise get resent to a
    vision API on every re-run. A row that fails any check is skipped, not
    fatal: the rest of the set still runs. Caps and the count limit are
    applied in stored order, so earlier diagrams are kept over later ones.

    Returns (kept, skipped) — `skipped` entries have "name" and "reason",
    meant to be sent as the SSE stream's first info event.
    """
    rows = await crud.list_model_diagrams(model_id, include_image_content=True)
    if not rows:
        return [], []

    kept: list[DiagramData] = []
    skipped: list[dict[str, str]] = []
    image_total = 0
    mermaid_total = 0

    for row in rows:
        if len(kept) >= MAX_DIAGRAMS:
            skipped.append(
                {"name": row.get("name") or "diagram", "reason": "too many stored diagrams"}
            )
            continue

        try:
            diagram = crud.diagram_data_from_row(row)
        except (ValidationError, ValueError, KeyError):
            skipped.append(
                {"name": row.get("name") or "diagram", "reason": "stored row is malformed"}
            )
            continue

        if diagram.format == DiagramFormat.MERMAID:
            size = len((diagram.mermaid_source or "").encode("utf-8"))
            if size > MAX_MERMAID_SIZE_BYTES:
                skipped.append(
                    {"name": diagram.name, "reason": "exceeds the current Mermaid size limit"}
                )
                continue
            if mermaid_total + size > MAX_TOTAL_MERMAID_BYTES:
                skipped.append(
                    {"name": diagram.name, "reason": "exceeds the total Mermaid size budget"}
                )
                continue
            mermaid_total += size
        else:
            size = image_byte_length(diagram)
            if size > MAX_IMAGE_SIZE_BYTES:
                skipped.append(
                    {"name": diagram.name, "reason": "exceeds the current image size limit"}
                )
                continue
            if image_total + size > MAX_TOTAL_IMAGE_BYTES:
                skipped.append(
                    {"name": diagram.name, "reason": "exceeds the total image size budget"}
                )
                continue
            try:
                await asyncio.to_thread(
                    validate_diagram_bytes,
                    f"{diagram.name}.{diagram.format.value}",
                    base64.b64decode(diagram.base64_data or ""),
                )
            except (DiagramValidationError, ValueError, binascii.Error):
                skipped.append(
                    {"name": diagram.name, "reason": "stored image content is no longer valid"}
                )
                continue
            image_total += size

        kept.append(diagram)

    return kept, skipped


async def _parse_dependency_json_upload(
    upload: UploadFile, field_name: str, max_bytes: int
) -> dict:
    """Read and parse an uploaded package.json / package-lock.json file into
    a dict, raising 422 on anything that isn't a well-formed, size-bounded
    JSON object. Used only for user-submitted manifests — a code-source
    auto-detected manifest degrades silently instead (see
    `_detect_manifest_from_code_source`), since a malformed file in someone
    else's repo shouldn't fail the whole run.

    Accepted as a file upload (multipart File, not a plain Form field)
    deliberately: Starlette's multipart parser caps plain non-file form
    fields at 1 MB (its own 400, raised before this function ever runs) —
    a limit real package-lock.json files from large monorepos routinely
    exceed. File parts aren't subject to that per-field text cap, so this
    function enforces its own size limit instead, consistently as a 422.

    Reads at most `max_bytes + 1` rather than `upload.read()` with no
    argument: Starlette spools an oversized file part to disk during
    multipart parsing (bounded there), but an unbounded `.read()` still
    pulls the whole spooled file into one in-memory `bytes` object before
    any size check runs — an arbitrarily large upload would be fully
    buffered in RAM first. Capping the read itself means memory use stays
    bounded by `max_bytes` regardless of how large the actual upload is.
    """
    raw = await upload.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' exceeds the {max_bytes // (1024 * 1024)} MB limit "
            f"({len(raw)} bytes)",
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail=f"'{field_name}' must be UTF-8 text")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail=f"'{field_name}' must be valid JSON")
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' must be a JSON object, not {type(parsed).__name__}",
        )
    return parsed


def _validate_direct_dependency_count(manifest: dict, lockfile: dict | None) -> None:
    """Fail fast with a clear 422 instead of letting analyze_manifest() silently
    truncate to DEFAULT_MAX_DIRECT_DEPENDENCIES — a truncated scan run without
    warning would under-report dependency threats without the user knowing."""
    count = count_resolvable_direct_dependencies(manifest, lockfile)
    if count > DEFAULT_MAX_DIRECT_DEPENDENCIES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'dependency_manifest' resolves {count} direct dependencies; "
                f"the limit is {DEFAULT_MAX_DIRECT_DEPENDENCIES}."
            ),
        )


async def _detect_manifest_from_code_source(code_source_id: str) -> tuple[dict | None, dict | None]:
    """Offer the code source's own root package.json (+ lockfile) as the
    dependency manifest when the user didn't upload one explicitly. Reuses
    the existing clone — nothing new is fetched. Degrades to (None, None) on
    any read/parse failure (missing file, malformed JSON, oversized file):
    this is best-effort convenience, not a user-submitted input, so it must
    never fail the run the way an explicit bad upload does."""
    manifest_path = clone_dir_for(code_source_id) / "package.json"
    if not manifest_path.is_file():
        return None, None
    try:
        if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
            return None, None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            return None, None
    except (OSError, ValueError):
        return None, None

    lockfile: dict | None = None
    lockfile_path = clone_dir_for(code_source_id) / "package-lock.json"
    try:
        if lockfile_path.is_file() and lockfile_path.stat().st_size <= _MAX_LOCKFILE_BYTES:
            candidate = json.loads(lockfile_path.read_text(encoding="utf-8"))
            if isinstance(candidate, dict):
                lockfile = candidate
    except (OSError, ValueError):
        lockfile = None

    # Same "never fail the run" contract as above: an auto-detected manifest
    # over the direct-dependency cap doesn't get the explicit-upload 422
    # (_validate_direct_dependency_count) — it's dropped, same as a missing
    # or malformed file, rather than silently truncated deep inside
    # analyze_manifest() with no signal at all that it happened.
    if count_resolvable_direct_dependencies(manifest, lockfile) > DEFAULT_MAX_DIRECT_DEPENDENCIES:
        return None, None

    return manifest, lockfile


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post("/", status_code=201)
async def create_model(
    body: CreateModelRequest,
    _rate: None = Depends(write_rate_limit),
    _user: Annotated[dict | None, Depends(get_current_user)] = None,
) -> JSONResponse:
    """Create a new threat model record."""
    project = await crud_projects.get_project(body.project_id or crud_projects.DEFAULT_PROJECT_ID)

    provider_type, model_id_str = resolve_provider(
        body.provider.value if body.provider else None, body.model, project
    )
    iteration_count = (
        body.iteration_count
        or (project or {}).get("default_iterations")
        or settings.default_iterations
    )

    model_id = await crud.create_threat_model(
        title=body.title,
        description=body.description,
        provider=provider_type,
        model=model_id_str,
        framework=body.framework.value,
        iteration_count=iteration_count,
        project_id=body.project_id,
        scoring_method=body.scoring_method,
    )

    record = await crud.get_threat_model(model_id)
    await crud_activity.safe_log_activity(
        project_id=record.get("project_id") if record else None,
        user_id=_user["id"] if _user else None,
        entity_type="model",
        entity_id=model_id,
        action="created",
        details={"title": body.title},
    )
    return JSONResponse(status_code=201, content=record)


@router.get("/")
async def list_models(
    limit: int = 50,
    framework: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
    _user: Annotated[dict | None, Depends(get_current_user)] = None,
) -> JSONResponse:
    """List threat models, optionally filtered by framework, status, or project."""
    rows = await crud.list_threat_models(
        limit=limit,
        framework=framework,
        status=status,
        project_id=project_id,
    )
    for row in rows:
        row["gap_summaries"] = decode_gap_summaries(row.get("gap_summaries"))
        row["code_summary"] = _decode_json_field(row.get("code_summary"))
    return JSONResponse(content=rows)


@router.get("/{model_id}")
async def get_model(
    model_id: str,
    _user: Annotated[dict | None, Depends(get_current_user)] = None,
) -> JSONResponse:
    """Get a single threat model with its threats."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

    threats = await crud.list_threats(model_id)
    record["threats"] = threats
    record["gap_summaries"] = decode_gap_summaries(record.get("gap_summaries"))
    record["code_summary"] = _decode_json_field(record.get("code_summary"))
    # Exposed as "usage" (not the raw usage_summary column name) so the
    # frontend reads the same shape here as from the live SSE event's
    # data.usage — see Results.svelte's runUsage fallback.
    record["usage"] = _decode_json_field(record.get("usage_summary"))
    return JSONResponse(content=record)


@router.patch("/{model_id}")
async def update_model(
    model_id: str,
    body: UpdateModelRequest,
    user: Annotated[dict, Depends(get_current_user)],
    _authz: None = Depends(require_role("editor", "model_id", "model")),
) -> JSONResponse:
    """Update threat model metadata."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

    if body.status is not None and not is_valid_model_status_transition(
        record.get("status"), body.status.value
    ):
        raise HTTPException(
            status_code=422,
            detail=f"Cannot transition from '{record.get('status')}' to '{body.status.value}'",
        )

    await crud.update_threat_model(
        model_id,
        title=body.title,
        description=body.description,
        framework=body.framework.value if body.framework else None,
        status=body.status.value if body.status else None,
    )

    updated = await crud.get_threat_model(model_id)

    if body.status is not None and body.status.value != record.get("status"):
        await crud_activity.safe_log_activity(
            project_id=record.get("project_id"),
            user_id=user["id"],
            entity_type="model",
            entity_id=model_id,
            action="status_changed",
            details={"from": record.get("status"), "to": body.status.value},
        )
        await crud_activity.safe_notify_users(
            await model_assignee_ids(model_id, exclude=user["id"]),
            notification_type="threat_status_changed",
            title=f'Model "{(updated or {}).get("title", model_id)}" status changed to {body.status.value}',
            entity_type="model",
            entity_id=model_id,
        )

    return JSONResponse(content=updated)


@router.delete("/{model_id}", status_code=204)
async def delete_model(
    model_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    _authz: None = Depends(require_role("owner", "model_id", "model")),
) -> None:
    """Delete a threat model and all associated data."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    await crud.delete_threat_model(model_id)
    await crud_activity.safe_log_activity(
        project_id=record.get("project_id"),
        user_id=user["id"],
        entity_type="model",
        entity_id=model_id,
        action="deleted",
        details={"title": record.get("title")},
    )


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
            model_record = await crud.get_threat_model(model_id)
            sys_description = (model_record or {}).get("description", "")
            assets = await crud.list_assets(model_id)
            flows = await crud.list_flows(model_id)

            for threat in threats_list.threats:
                try:
                    confidence = score_threat_confidence(threat, assets, flows, sys_description)
                    dread = threat.dread
                    cvss_vector = to_vector_string(threat.cvss) if threat.cvss else None
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
                        source=threat.source,
                        confidence=confidence,
                        dependency_ref=(
                            threat.dependency_ref.model_dump() if threat.dependency_ref else None
                        ),
                        attack_techniques=(
                            [t.model_dump() for t in threat.attack_techniques]
                            if threat.attack_techniques
                            else None
                        ),
                        cvss_vector=cvss_vector,
                        cvss_score=threat.cvss_score,
                        cvss_severity=threat.cvss_severity,
                    )
                except Exception:
                    logger.warning(
                        "Failed to persist threat '%s'",
                        getattr(threat, "name", "unknown"),
                        exc_info=True,
                    )

        dependency_context = event.data.get("dependency_context")
        if dependency_context and hasattr(dependency_context, "packages"):
            for package, version, analysis in dependency_scan_rows(dependency_context):
                try:
                    await crud.create_dependency_scan(
                        model_id=model_id,
                        package=package,
                        version=version,
                        source_mode=dependency_context.source_mode,
                        analysis=analysis,
                    )
                except Exception:
                    logger.warning(
                        "Failed to persist dependency scan for '%s'", package, exc_info=True
                    )

        gap_list = event.data.get("gaps")
        if gap_list:
            try:
                await crud.update_threat_model(model_id, gap_summaries=json.dumps(gap_list))
            except Exception:
                logger.warning(
                    "Failed to persist gap_summaries for model %s",
                    model_id,
                    exc_info=True,
                )

        cs = event.data.get("code_summary")
        if cs is not None:
            try:
                cs_dict = cs.model_dump(mode="json") if hasattr(cs, "model_dump") else cs
                await crud.update_threat_model(model_id, code_summary=json.dumps(cs_dict))
            except Exception:
                logger.warning(
                    "Failed to persist code_summary for model %s",
                    model_id,
                    exc_info=True,
                )

        usage = event.data.get("usage")
        if usage is not None:
            try:
                await crud.update_threat_model(model_id, usage_summary=json.dumps(usage))
            except Exception:
                logger.warning(
                    "Failed to persist usage_summary for model %s",
                    model_id,
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
    diagrams: Annotated[list[UploadFile] | None, File()] = None,
    diagram_names: Annotated[str | None, Form()] = None,
    code_source_id: Annotated[str, Form()] = "",
    dependency_manifest: Annotated[UploadFile | None, File()] = None,
    dependency_lockfile: Annotated[UploadFile | None, File()] = None,
    deps_source_mode: Annotated[str, Form()] = "npm",
    use_code_source_manifest: Annotated[bool, Form()] = False,
    _rate: None = Depends(pipeline_rate_limit),
    _authz: None = Depends(require_role("editor", "model_id", "model")),
) -> StreamingResponse:
    """Run the threat modeling pipeline, streaming SSE progress events.

    Accepts multipart/form-data:
    - assumptions: JSON array string, e.g. '["TLS is enforced","Auth is OAuth2"]'
    - has_ai_components: bool, enables MAESTRO alongside STRIDE
    - diagram: DEPRECATED — optional single PNG/JPG/Mermaid file upload, kept
      for one release. Merged first (position 0) if `diagrams` is also sent.
    - diagrams: optional 1-5 PNG/JPG/Mermaid file uploads. Replaces the
      model's entire stored diagram set. Omit entirely (with no `diagram`
      either) to reuse the diagrams already stored from a previous run.
    - diagram_names: optional JSON array of strings, same length as
      `diagrams`, labeling each file (not the deprecated `diagram` field).
      An empty string falls back to that file's own name.
    - code_source_id: optional ID of a ready code source for code context
    - dependency_manifest: optional package.json file upload (<= 1 MB,
      <= 50 resolvable direct dependencies). A file upload, not a plain form
      field: Starlette caps plain multipart text fields at 1 MB with its own
      400 before our validation ever runs, and real package-lock.json files
      routinely need more room than that (see dependency_lockfile).
    - dependency_lockfile: optional package-lock.json file upload (<= 20 MB;
      requires dependency_manifest)
    - deps_source_mode: "npm" (fast, default) or "both" (adds GitHub drift)
    - use_code_source_manifest: opt-in — when true, no dependency_manifest was
      uploaded, and code_source_id is a ready source, its root package.json
      (+ lockfile) is auto-detected from the existing clone and analyzed.
      Off by default: dependency analysis does registry/codeload fetches and
      a Semgrep scan (up to deps_analysis_timeout_seconds), so it must not
      silently turn on for every code-source run.
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

    # Build the diagram set if any files were uploaded. An empty list means
    # nothing was uploaded — the event_generator below then falls back to
    # whatever is already stored, rather than wiping it.
    uploaded_diagrams = await _build_diagrams_from_request(diagram, diagrams, diagram_names)

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

    # Dependency manifest — explicit upload, or (opt-in) auto-detected from the
    # code source's own clone. DEPS_ANALYSIS_ENABLED is a hard kill switch:
    # when false, neither path is used and ANALYZE_DEPENDENCIES never runs.
    has_manifest_upload = dependency_manifest is not None and bool(dependency_manifest.filename)
    has_lockfile_upload = dependency_lockfile is not None and bool(dependency_lockfile.filename)

    dependency_manifest_dict: dict | None = None
    dependency_lockfile_dict: dict | None = None
    if not settings.deps_analysis_enabled:
        if has_manifest_upload:
            raise HTTPException(
                status_code=422,
                detail="Dependency analysis is disabled on this instance (DEPS_ANALYSIS_ENABLED=false).",
            )
    else:
        if deps_source_mode not in _VALID_DEPS_SOURCE_MODES:
            raise HTTPException(
                status_code=422,
                detail=f"'deps_source_mode' must be one of {sorted(_VALID_DEPS_SOURCE_MODES)}",
            )
        if has_manifest_upload:
            dependency_manifest_dict = await _parse_dependency_json_upload(
                dependency_manifest, "dependency_manifest", _MAX_MANIFEST_BYTES
            )
            if has_lockfile_upload:
                dependency_lockfile_dict = await _parse_dependency_json_upload(
                    dependency_lockfile, "dependency_lockfile", _MAX_LOCKFILE_BYTES
                )
            _validate_direct_dependency_count(dependency_manifest_dict, dependency_lockfile_dict)
        elif has_lockfile_upload:
            raise HTTPException(
                status_code=422,
                detail="'dependency_lockfile' requires 'dependency_manifest'",
            )
        elif use_code_source_manifest and source_row is not None:
            (
                dependency_manifest_dict,
                dependency_lockfile_dict,
            ) = await _detect_manifest_from_code_source(code_source_id)

    provider = build_provider_from_record(record)
    fast_provider = build_fast_provider(record)
    framework = Framework(record.get("framework", "STRIDE"))
    max_iterations = record.get("iteration_count", settings.default_iterations)
    project = await crud_projects.get_project(record.get("project_id"))
    project_temperature = (project or {}).get("default_temperature")
    temperature = (
        project_temperature if project_temperature is not None else settings.default_temperature
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        # Clear any previous run's data so re-runs start clean
        await crud.clear_model_data(model_id)
        await crud.update_threat_model_status(model_id, ModelStatus.IN_PROGRESS.value)
        # Persist assumptions unconditionally — clears stale data from prior runs
        await crud.update_threat_model(model_id, assumptions=json.dumps(parsed_assumptions))

        skipped_stored_diagrams: list[dict[str, str]] = []
        if uploaded_diagrams:
            run_diagrams = uploaded_diagrams
            try:
                await _persist_diagram_data(model_id, uploaded_diagrams)
            except aiosqlite.Error:
                logger.warning(
                    "Failed to persist uploaded diagrams for model %s", model_id, exc_info=True
                )
        else:
            try:
                run_diagrams, skipped_stored_diagrams = await _load_stored_diagrams_for_reuse(
                    model_id
                )
            except aiosqlite.Error:
                logger.exception("Failed to load stored diagrams for model %s", model_id)
                await crud.update_threat_model_status(model_id, ModelStatus.FAILED.value)
                yield PipelineEvent(
                    step=PipelineStep.COMPLETE,
                    status="failed",
                    message="Failed to load stored diagrams; see server logs.",
                ).to_sse_format()
                return

        if skipped_stored_diagrams:
            yield PipelineEvent(
                step=PipelineStep.SUMMARIZE,
                status="info",
                message=(
                    f"{len(skipped_stored_diagrams)} stored diagram(s) no longer fit current "
                    "limits and were skipped; the rest of the set still runs."
                ),
                data={"warning": "stored_diagram_skipped", "skipped": skipped_stored_diagrams},
            ).to_sse_format()

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
                async with MCPCodeExtractor(
                    str(clone_dir_for(code_source_id)),
                    db_path=str(index_db_for(code_source_id)),
                ) as extractor:
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
                    diagrams=run_diagrams or None,
                    code_context=code_context,
                    max_iterations=max_iterations,
                    has_ai_components=has_ai_components,
                    temperature=temperature,
                    dependency_manifest=dependency_manifest_dict,
                    dependency_lockfile=dependency_lockfile_dict,
                    dependency_source_mode=deps_source_mode,
                    persist_usage=True,  # model_id already names a saved threat_models row
                    scoring_method=record.get("scoring_method") or "dread",
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


@router.get("/{model_id}/dependencies")
async def list_model_dependencies(
    model_id: str,
    _authz: None = Depends(require_role("viewer", "model_id", "model")),
) -> JSONResponse:
    """List persisted dependency capability scans for a model, most recent first.

    Gated at viewer (unlike the other GET sub-resource routes above, which
    predate per-route RBAC): this endpoint exposes package names, versions,
    and raw scanner evidence, which is more sensitive than a threat's own
    text, so it doesn't copy the existing gap.
    """
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    scans = await crud.list_dependency_scans(model_id)
    return JSONResponse(content=scans)


@router.get("/{model_id}/diagrams")
async def list_model_diagrams(
    model_id: str,
    _authz: None = Depends(require_role("viewer", "model_id", "model")),
) -> JSONResponse:
    """List persisted architecture diagrams for a model, most recently uploaded first."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    diagrams = await crud.list_model_diagrams(model_id)
    return JSONResponse(content=diagrams)


@router.get("/{model_id}/diagrams/{diagram_id}")
async def get_model_diagram(
    model_id: str,
    diagram_id: str,
    _authz: None = Depends(require_role("viewer", "model_id", "model")),
) -> JSONResponse:
    """Get one persisted diagram's content for a model."""
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    diagram = await crud.get_model_diagram(diagram_id)
    if diagram is None or diagram["model_id"] != model_id:
        raise HTTPException(status_code=404, detail=f"Diagram '{diagram_id}' not found")
    return JSONResponse(content=diagram)


# ---------------------------------------------------------------------------
# Asset write routes
# ---------------------------------------------------------------------------


@router.post("/{model_id}/assets", status_code=201)
async def create_asset(
    model_id: str,
    body: CreateAssetRequest,
    _authz: None = Depends(require_role("editor", "model_id", "model")),
) -> JSONResponse:
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
async def update_asset(
    model_id: str,
    asset_id: str,
    body: UpdateAssetRequest,
    _authz: None = Depends(require_role("editor", "model_id", "model")),
) -> JSONResponse:
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
async def delete_asset(
    model_id: str,
    asset_id: str,
    _authz: None = Depends(require_role("editor", "model_id", "model")),
) -> None:
    """Delete an asset."""
    asset = await crud.get_asset(asset_id)
    if asset is None or asset.get("model_id") != model_id:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")
    await crud.delete_asset(asset_id)


# ---------------------------------------------------------------------------
# Flow write routes
# ---------------------------------------------------------------------------


@router.post("/{model_id}/flows", status_code=201)
async def create_flow(
    model_id: str,
    body: CreateFlowRequest,
    _authz: None = Depends(require_role("editor", "model_id", "model")),
) -> JSONResponse:
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
async def update_flow(
    model_id: str,
    flow_id: str,
    body: UpdateFlowRequest,
    _authz: None = Depends(require_role("editor", "model_id", "model")),
) -> JSONResponse:
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
async def delete_flow(
    model_id: str,
    flow_id: str,
    _authz: None = Depends(require_role("editor", "model_id", "model")),
) -> None:
    """Delete a data flow."""
    flow = await crud.get_flow(flow_id)
    if flow is None or flow.get("model_id") != model_id:
        raise HTTPException(status_code=404, detail=f"Flow '{flow_id}' not found")
    await crud.delete_flow(flow_id)


# ---------------------------------------------------------------------------
# Trust boundary write routes
# ---------------------------------------------------------------------------


@router.post("/{model_id}/trust-boundaries", status_code=201)
async def create_trust_boundary(
    model_id: str,
    body: CreateTrustBoundaryRequest,
    _authz: None = Depends(require_role("editor", "model_id", "model")),
) -> JSONResponse:
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
    model_id: str,
    boundary_id: str,
    body: UpdateTrustBoundaryRequest,
    _authz: None = Depends(require_role("editor", "model_id", "model")),
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
async def delete_trust_boundary(
    model_id: str,
    boundary_id: str,
    _authz: None = Depends(require_role("editor", "model_id", "model")),
) -> None:
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
    before committing to a full pipeline run. Returns gaps and is_sufficient for
    the description only (for CLI / CI callers). For full description + assumptions
    analysis use POST /api/analyze/ instead.
    """
    record = await crud.get_threat_model(model_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

    description = record.get("description", "")
    provider = build_provider_from_record(record)

    async with provider:
        # Delegate to shared pre_flight function — same logic as /api/analyze/
        return await analyze_description_gaps(description=description, provider=provider)


@router.post("/{model_id}/extract")
async def extract_model_context(
    model_id: str,
    _authz: None = Depends(require_role("editor", "model_id", "model")),
) -> StreamingResponse:
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
            run_diagrams, skipped_stored_diagrams = await _load_stored_diagrams_for_reuse(model_id)
        except aiosqlite.Error:
            logger.exception("Failed to load stored diagrams for model %s", model_id)
            yield PipelineEvent(
                step=PipelineStep.COMPLETE,
                status="failed",
                message="Failed to load stored diagrams; see server logs.",
            ).to_sse_format()
            return

        if skipped_stored_diagrams:
            yield PipelineEvent(
                step=PipelineStep.SUMMARIZE,
                status="info",
                message=(
                    f"{len(skipped_stored_diagrams)} stored diagram(s) no longer fit current "
                    "limits and were skipped; the rest of the set still runs."
                ),
                data={"warning": "stored_diagram_skipped", "skipped": skipped_stored_diagrams},
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
                    diagrams=run_diagrams or None,
                    stop_after="extraction",
                    persist_usage=True,  # model_id already names a saved threat_models row
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
