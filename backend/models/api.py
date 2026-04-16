"""API request/response models for the HTTP layer.

These are separate from pipeline state models in state.py. Pipeline models
define the shapes used internally between nodes; these define what the REST
API accepts and returns.
"""

from typing import Literal

from pydantic import BaseModel, Field

from backend.models.enums import (
    Framework,
    ImpactLevel,
    LikelihoodLevel,
    ModelStatus,
    Provider,
    ThreatStatus,
)


class CreateModelRequest(BaseModel):
    """Request body for POST /api/models."""

    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=10)
    framework: Framework = Framework.STRIDE
    provider: Provider | None = None  # None → settings.default_provider
    model: str | None = None  # None → settings.default_model
    iteration_count: int = Field(default=3, ge=1, le=15)


class UpdateModelRequest(BaseModel):
    """Request body for PATCH /api/models/{model_id}."""

    title: str | None = None
    description: str | None = None
    framework: Framework | None = None
    status: ModelStatus | None = None


class UpdateThreatRequest(BaseModel):
    """Request body for PATCH /api/threats/{threat_id}."""

    name: str | None = None
    description: str | None = None
    target: str | None = None
    impact: ImpactLevel | None = None
    likelihood: LikelihoodLevel | None = None
    status: ThreatStatus | None = None
    mitigations: list[str] | None = None
    dread_damage: float | None = Field(default=None, ge=0, le=10)
    dread_reproducibility: float | None = Field(default=None, ge=0, le=10)
    dread_exploitability: float | None = Field(default=None, ge=0, le=10)
    dread_affected_users: float | None = Field(default=None, ge=0, le=10)
    dread_discoverability: float | None = Field(default=None, ge=0, le=10)


class CreateAssetRequest(BaseModel):
    """Request body for POST /api/models/{model_id}/assets."""

    name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(default="Asset", pattern="^(Asset|Entity)$")
    description: str = Field(default="")


class UpdateAssetRequest(BaseModel):
    """Request body for PATCH /api/models/{model_id}/assets/{asset_id}."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    type: str | None = Field(default=None, pattern="^(Asset|Entity)$")
    description: str | None = None


class CreateFlowRequest(BaseModel):
    """Request body for POST /api/models/{model_id}/flows."""

    source_entity: str = Field(..., min_length=1)
    target_entity: str = Field(..., min_length=1)
    flow_description: str = Field(default="")
    flow_type: str = Field(default="data")


class UpdateFlowRequest(BaseModel):
    """Request body for PATCH /api/models/{model_id}/flows/{flow_id}."""

    source_entity: str | None = None
    target_entity: str | None = None
    flow_description: str | None = None
    flow_type: str | None = None


class CreateTrustBoundaryRequest(BaseModel):
    """Request body for POST /api/models/{model_id}/trust-boundaries."""

    source_entity: str = Field(..., min_length=1)
    target_entity: str = Field(..., min_length=1)
    purpose: str = Field(default="")


class UpdateTrustBoundaryRequest(BaseModel):
    """Request body for PATCH /api/models/{model_id}/trust-boundaries/{boundary_id}."""

    source_entity: str | None = None
    target_entity: str | None = None
    purpose: str | None = None


ExportFormat = Literal["markdown", "pdf", "sarif", "json"]


class DescriptionGap(BaseModel):
    """A single gap found in the system description or extracted context."""

    field: str  # e.g. "trust_boundaries", "authentication", "data_flows"
    severity: Literal["warning", "error"]
    message: str  # human-readable explanation of what is missing or ambiguous


class AnalyzeDescriptionResponse(BaseModel):
    """Response body for POST /api/models/{model_id}/analyze."""

    gaps: list[DescriptionGap]
    is_sufficient: bool  # True when len(errors) == 0
