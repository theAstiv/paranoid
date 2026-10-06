"""API request/response models for the HTTP layer.

These are separate from pipeline state models in state.py. Pipeline models
define the shapes used internally between nodes; these define what the REST
API accepts and returns.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.models.enums import (
    Framework,
    ImpactLevel,
    LikelihoodLevel,
    ModelStatus,
    Provider,
    ScoringMethod,
    ThreatStatus,
)
from backend.scoring.cvss31 import Cvss31Error, parse_vector, to_vector_string


class CreateModelRequest(BaseModel):
    """Request body for POST /api/models."""

    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=10)
    framework: Framework = Framework.STRIDE
    provider: Provider | None = None  # None → project default → settings.default_provider
    model: str | None = None  # None → project default → settings.default_model
    # None → project default_iterations → settings.default_iterations
    iteration_count: int | None = Field(default=None, ge=1, le=15)
    project_id: str | None = None  # None → Default Project sentinel
    scoring_method: ScoringMethod = "dread"


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
    cvss_vector: str | None = None

    @field_validator("cvss_vector")
    @classmethod
    def _validate_cvss_vector(cls, value: str | None) -> str | None:
        """Parse-and-re-render rather than store the client's exact string —
        parse_vector() is deliberately lenient about metric order and an
        optional "CVSS:3.1/" prefix, so the stored/returned value must be
        the canonical form, not whatever order/prefix the client happened
        to send (metric *values* are case-sensitive per the CVSS spec and
        are rejected, not normalized, if sent lowercase).

        A value of None passes through unchanged here — the route
        distinguishes "omitted" (no change) from "explicit null" (clear
        the stored vector) via model_fields_set, the same three-way
        pattern UpdateConfigRequest uses for API keys.
        """
        if value is None:
            return None
        try:
            return to_vector_string(parse_vector(value))
        except Cvss31Error as exc:
            raise ValueError(str(exc)) from exc


class CvssScoreRequest(BaseModel):
    """Request body for POST /api/cvss/score — recompute score+severity
    from a draft vector as the reviewer edits the 8 dropdowns, so the
    frontend never needs to port the CVSS v3.1 formula to JS."""

    vector: str

    @field_validator("vector")
    @classmethod
    def _validate_vector(cls, value: str) -> str:
        """Same parse-and-re-render as UpdateThreatRequest.cvss_vector."""
        try:
            return to_vector_string(parse_vector(value))
        except Cvss31Error as exc:
            raise ValueError(str(exc)) from exc


class BulkStatusRequest(BaseModel):
    """Request body for POST /api/threats/bulk-status."""

    threat_ids: list[str] = Field(..., min_length=1, max_length=500)
    status: ThreatStatus


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

ProjectRole = Literal["owner", "editor", "viewer"]


class CreateProjectRequest(BaseModel):
    """Request body for POST /api/projects."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class UpdateProjectRequest(BaseModel):
    """Request body for PATCH /api/projects/{project_id}."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    default_provider: str | None = None
    default_model: str | None = None
    default_iterations: int | None = Field(default=None, ge=1, le=15)
    default_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    staleness_threshold_days: int | None = Field(default=None, ge=1, le=365)


class AddMemberRequest(BaseModel):
    """Request body for POST /api/projects/{project_id}/members."""

    user_id: str = Field(..., min_length=1)
    role: ProjectRole = "viewer"


class UpdateMemberRoleRequest(BaseModel):
    """Request body for PATCH /api/projects/{project_id}/members/{user_id}."""

    role: ProjectRole


class CreateInvitationRequest(BaseModel):
    """Request body for POST /api/projects/{project_id}/invitations."""

    invited_email: str = Field(..., min_length=3, max_length=320)
    role: ProjectRole = "viewer"


class CreateCommentRequest(BaseModel):
    """Request body for POST /api/models/{model_id}/comments."""

    body: str = Field(..., min_length=1, max_length=10_000)
    parent_id: str | None = None
    entity_type: Literal["threat", "asset", "flow"] | None = None
    entity_id: str | None = None

    @model_validator(mode="after")
    def entity_fields_paired(self):
        if (self.entity_type is None) != (self.entity_id is None):
            raise ValueError("entity_type and entity_id must both be provided or both be null")
        return self


class UpdateCommentRequest(BaseModel):
    """Request body for PATCH /api/comments/{comment_id}."""

    body: str = Field(..., min_length=1, max_length=10_000)


class AddAssigneeRequest(BaseModel):
    """Request body for POST /api/models/{model_id}/assignees."""

    user_id: str = Field(..., min_length=1)


class DescriptionGap(BaseModel):
    """A single gap found in the system description or extracted context."""

    field: str  # e.g. "trust_boundaries", "authentication", "data_flows"
    severity: Literal["warning", "error"]
    message: str  # human-readable explanation of what is missing or ambiguous


class AnalyzeDescriptionResponse(BaseModel):
    """Response body for POST /api/models/{model_id}/analyze."""

    gaps: list[DescriptionGap]
    is_sufficient: bool  # True when len(errors) == 0


class AssumptionsGap(BaseModel):
    """A single gap found in the assumptions section."""

    field: Literal[
        "controls",
        "in_scope",
        "out_of_scope",
        "focus_areas",
        "constraints",
        "coverage",
        "assumptions",
    ]
    severity: Literal["warning", "error", "info"]
    message: str


class AnalyzeAssumptionsResponse(BaseModel):
    """Response body for the assumptions portion of the bundle analysis."""

    gaps: list[AssumptionsGap]
    is_sufficient: bool  # True when no error-severity gaps


class AnalyzeBundleRequest(BaseModel):
    """Request body for POST /api/analyze/."""

    description: str = Field(..., min_length=1, max_length=50_000)
    assumptions: list[str] = Field(default_factory=list, max_length=200)
    framework: Framework = Framework.STRIDE
    has_ai_components: bool = False


class AnalyzeBundleResponse(BaseModel):
    """Response body for POST /api/analyze/ — covers both description and assumptions."""

    description: AnalyzeDescriptionResponse
    assumptions: AnalyzeAssumptionsResponse
