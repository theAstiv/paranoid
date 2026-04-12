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


ExportFormat = Literal["markdown", "pdf", "sarif", "json"]
