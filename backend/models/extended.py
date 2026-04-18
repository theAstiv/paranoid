"""Extended Pydantic models for Paranoid-specific functionality."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, SecretStr

from backend.models.enums import (
    DiagramFormat,
    Framework,
    ImpactLevel,
    LikelihoodLevel,
    MaestroCategory,
    ModelStatus,
    Provider,
    StrideCategory,
    ThreatStatus,
)
from backend.models.state import DreadScore


class MaestroThreat(BaseModel):
    """Model for ML/AI-specific threats using MAESTRO framework."""

    name: Annotated[str, Field(description="The name of the ML/AI threat")]
    maestro_category: Annotated[
        MaestroCategory,
        Field(description="The MAESTRO category of the threat"),
    ]
    description: Annotated[
        str,
        Field(description="Detailed description of the ML/AI threat"),
    ]
    target: Annotated[str, Field(description="The target ML component or pipeline")]
    impact: Annotated[ImpactLevel, Field(description="Impact level")]
    likelihood: Annotated[LikelihoodLevel, Field(description="Likelihood level")]
    mitigations: Annotated[
        list[str],
        Field(description="List of ML-specific mitigations", min_length=2),
    ]


class HybridThreat(BaseModel):
    """Model for threats that span both STRIDE and MAESTRO frameworks."""

    name: Annotated[str, Field(description="The name of the threat")]
    stride_category: Annotated[
        StrideCategory | None,
        Field(description="Optional STRIDE category"),
    ] = None
    maestro_category: Annotated[
        MaestroCategory | None,
        Field(description="Optional MAESTRO category"),
    ] = None
    description: Annotated[str, Field(description="Detailed threat description")]
    target: Annotated[str, Field(description="The target of the threat")]
    impact: Annotated[ImpactLevel, Field(description="Impact level")]
    likelihood: Annotated[LikelihoodLevel, Field(description="Likelihood level")]
    dread: Annotated[
        DreadScore | None,
        Field(description="Optional DREAD scoring"),
    ] = None
    mitigations: Annotated[
        list[str],
        Field(description="List of mitigations", min_length=2),
    ]


class AttackTree(BaseModel):
    """Model for attack tree visualization."""

    threat_name: Annotated[str, Field(description="Name of the threat")]
    mermaid_source: Annotated[
        str,
        Field(description="Mermaid.js graph definition for attack tree"),
    ]


class TestCase(BaseModel):
    """Model for BDD-style security test cases."""

    threat_name: Annotated[str, Field(description="Name of the threat")]
    gherkin_source: Annotated[
        str,
        Field(description="Gherkin/BDD format test case"),
    ]


class TestSuite(BaseModel):
    """Model for a complete test suite (collection of test cases)."""

    feature: Annotated[str, Field(description="Feature being tested")]
    gherkin_source: Annotated[
        str,
        Field(description="Complete Gherkin feature file with scenarios"),
    ]


class CodeFile(BaseModel):
    """Model for a single code file from MCP context."""

    path: Annotated[str, Field(description="File path relative to repository root")]
    content: Annotated[str, Field(description="File content")]
    language: Annotated[str | None, Field(description="Programming language")] = None


class CodeContext(BaseModel):
    """Model for code context extracted from MCP server."""

    repository: Annotated[str, Field(description="Repository name or path")]
    files: Annotated[
        list[CodeFile],
        Field(description="List of relevant code files"),
    ]
    summary: Annotated[
        str | None,
        Field(description="Optional summary of the codebase"),
    ] = None


class CodeSummary(BaseModel):
    """Condensed code context for downstream pipeline nodes.

    Produced by summarize_code() node, this provides a ~2KB security-focused
    summary of the codebase for use in asset extraction, flow analysis, threat
    generation, and gap analysis steps.
    """

    tech_stack: Annotated[
        list[str],
        Field(description="Languages, frameworks, libraries, infrastructure"),
    ]
    entry_points: Annotated[
        list[str],
        Field(description="HTTP routes, API endpoints, CLI commands, queue consumers"),
    ]
    auth_patterns: Annotated[
        list[str],
        Field(description="Authentication and authorization mechanisms observed in code"),
    ]
    data_stores: Annotated[
        list[str],
        Field(description="Databases, caches, file storage, message queues"),
    ]
    external_dependencies: Annotated[
        list[str],
        Field(description="Third-party APIs, services, SDKs called by the code"),
    ]
    security_observations: Annotated[
        list[str],
        Field(description="Security-relevant findings from code review"),
    ]
    raw_summary: Annotated[
        str,
        Field(description="150-200 word free-text summary of security posture"),
    ]


class ImageContent(BaseModel):
    """Image content for vision API calls (RULES.md: all pipeline data as Pydantic).

    Passed to LLM providers for vision-enabled models (Claude/GPT-4 with vision).
    """

    data: Annotated[str, Field(description="Base64-encoded image data")]
    media_type: Annotated[
        str,
        Field(description="MIME type: image/png or image/jpeg"),
    ]
    source: Annotated[
        str,
        Field(description="Original file path (for error messages and logging)"),
    ]


class DiagramData(BaseModel):
    """Architecture diagram data for threat modeling.

    Supports PNG/JPG images (vision API) and Mermaid text files (parsed by LLM).
    Loaded once at CLI, passed through all 5 pipeline nodes.
    """

    format: Annotated[
        DiagramFormat,
        Field(description="Diagram format: png, jpeg, or mermaid"),
    ]
    source_path: Annotated[
        str,
        Field(description="Original file path"),
    ]

    # For PNG/JPG images (vision API input)
    base64_data: Annotated[
        str | None,
        Field(description="Base64-encoded image for vision API"),
    ] = None
    media_type: Annotated[
        str | None,
        Field(description="MIME type for images: image/png or image/jpeg"),
    ] = None
    size_bytes: Annotated[
        int | None,
        Field(description="File size in bytes (for validation)"),
    ] = None

    # For Mermaid .mmd files (text input)
    mermaid_source: Annotated[
        str | None,
        Field(description="Raw Mermaid syntax (Claude/GPT-4 parse natively)"),
    ] = None


class StrideComponentDescription(BaseModel):
    """Structured STRIDE component description from template."""

    name: Annotated[str, Field(description="Name of the component")]
    purpose: Annotated[str, Field(description="Brief explanation of what the component does")]
    technology_stack: Annotated[
        dict[str, list[str]],
        Field(description="Technology stack details (languages, frameworks, libraries, etc.)"),
    ]
    interfaces: Annotated[
        dict[str, list[str]],
        Field(description="Inbound and outbound interfaces/protocols"),
    ]
    data_handled: Annotated[
        dict[str, list[str]],
        Field(description="Sensitive data types and storage mechanisms"),
    ]
    trust_level: Annotated[
        dict[str, str | list[str]],
        Field(description="Trust level details (internal/external, auth/authz)"),
    ]
    dependencies: Annotated[
        list[str],
        Field(description="External dependencies"),
    ]


class MaestroComponentDescription(BaseModel):
    """Structured MAESTRO component description from template."""

    name: Annotated[str, Field(description="Name of the AI component, agent, or pipeline stage")]
    mission_alignment: Annotated[
        dict[str, str],
        Field(description="Operational mission, autonomy level, decision authority"),
    ]
    agent_profile: Annotated[
        dict[str, str | list[str]],
        Field(description="Model(s) used, hosting, modalities, tool access, memory/state"),
    ]
    technology_stack: Annotated[
        dict[str, list[str]],
        Field(
            description="Orchestration framework, languages, infrastructure, supporting services"
        ),
    ]
    assets: Annotated[
        dict[str, list[str]],
        Field(description="Data assets, model assets, operational assets"),
    ]
    actors: Annotated[
        dict[str, list[str]],
        Field(description="Human principals, AI agents/sub-agents, external systems"),
    ]
    interfaces: Annotated[
        dict[str, list[str]],
        Field(description="Inbound and outbound interfaces"),
    ]
    trust_boundaries: Annotated[
        dict[str, str | list[str]],
        Field(description="Trust level, agent trust chain, human override, auth/authz"),
    ]
    dependencies: Annotated[
        list[str],
        Field(description="External dependencies"),
    ]


class StrideAssumptions(BaseModel):
    """Structured STRIDE assumptions from template."""

    security_controls: Annotated[
        list[str],
        Field(description="Security controls already in place"),
    ]
    in_scope: Annotated[
        list[str],
        Field(description="Areas considered in-scope"),
    ]
    out_of_scope: Annotated[
        list[str],
        Field(description="Areas considered out-of-scope"),
    ]
    constraints: Annotated[
        list[str],
        Field(description="Known constraints or limitations"),
    ]
    operational_considerations: Annotated[
        list[str],
        Field(description="Development or operational considerations"),
    ]
    focus_areas: Annotated[
        list[str],
        Field(description="Threat modeling focus areas"),
    ]


class MaestroAssumptions(BaseModel):
    """Structured MAESTRO assumptions from template."""

    mission_constraints: Annotated[
        list[str],
        Field(description="Mission-level constraints"),
    ]
    security_controls: Annotated[
        list[str],
        Field(description="Security controls already in place"),
    ]
    ai_specific_controls: Annotated[
        list[str],
        Field(description="AI-specific controls in place"),
    ]
    in_scope: Annotated[
        list[str],
        Field(description="Areas considered in-scope"),
    ]
    out_of_scope: Annotated[
        list[str],
        Field(description="Areas considered out-of-scope"),
    ]
    constraints: Annotated[
        list[str],
        Field(description="Known constraints or limitations"),
    ]
    agentic_considerations: Annotated[
        list[str],
        Field(description="Agentic/AI-specific considerations"),
    ]
    operational_considerations: Annotated[
        list[str],
        Field(description="Development or operational considerations"),
    ]
    focus_areas: Annotated[
        list[str],
        Field(description="Threat modeling focus areas"),
    ]


class ThreatModelConfig(BaseModel):
    """Configuration for a threat modeling run."""

    title: Annotated[str, Field(description="Title of the threat model")]
    description: Annotated[
        str,
        Field(description="System description or architecture details"),
    ]
    framework: Annotated[
        Framework,
        Field(description="Threat modeling framework to use"),
    ] = Framework.STRIDE
    has_ai_components: Annotated[
        bool,
        Field(
            description="Whether the system has AI/ML components (triggers MAESTRO alongside STRIDE)"
        ),
    ] = False
    provider: Annotated[Provider, Field(description="LLM provider")]
    model: Annotated[str, Field(description="Specific model identifier")]
    iteration_count: Annotated[
        int,
        Field(ge=1, le=15, description="Number of iterative refinement passes"),
    ] = 3
    temperature: Annotated[
        float,
        Field(ge=0.0, le=1.0, description="LLM temperature"),
    ] = 0.0


class ThreatModelResult(BaseModel):
    """Complete result of a threat modeling run."""

    id: str
    config: ThreatModelConfig
    status: ModelStatus
    summary: str | None = None
    assets: list[dict] = []
    flows: list[dict] = []
    threats: list[dict] = []
    attack_trees: list[AttackTree] = []
    test_cases: list[TestCase] = []
    iterations_completed: int = 0
    created_at: datetime
    updated_at: datetime
    duration_ms: int | None = None
    total_tokens: int | None = None


class ExportConfig(BaseModel):
    """Configuration for exporting threat models."""

    model_id: Annotated[str, Field(description="Threat model ID to export")]
    format: Annotated[
        str,
        Field(description="Export format: pdf, json, markdown, sarif"),
    ]
    include_attack_trees: Annotated[
        bool,
        Field(description="Include attack tree visualizations"),
    ] = True
    include_test_cases: Annotated[
        bool,
        Field(description="Include BDD test cases"),
    ] = True
    status_filter: Annotated[
        ThreatStatus | None,
        Field(description="Optional filter by threat status"),
    ] = None


# Status values emitted by the clone/index manager (Task 5). Kept here with
# the model so a future v2 can't silently introduce a value the route
# consumers don't know about.
SourceStatus = Literal["queued", "cloning", "indexing", "ready", "failed"]


class CodeSource(BaseModel):
    """Public view of a code_sources row.

    Used for both list (``GET /api/sources``) and detail
    (``GET /api/sources/{id}``) — identical shape. The raw PAT ciphertext
    is never serialised; callers get ``has_pat: bool`` and
    ``pat_last_used_at`` so the UI can render "last used 2h ago" without
    leaking the credential.
    """

    id: str
    name: str
    git_url: str
    ref: str | None = None
    has_pat: bool
    pat_last_used_at: str | None = None
    last_indexed_at: str | None = None
    last_index_status: SourceStatus | None = None
    last_index_error: str | None = None
    resolved_sha: str | None = None
    created_at: str
    updated_at: str


class CreateCodeSourceRequest(BaseModel):
    """POST /api/sources body. ``id`` is server-generated and cannot be
    supplied by the client — reserved so a future multi-user build can't
    be tricked into letting callers pick arbitrary IDs."""

    name: Annotated[str, Field(min_length=1, max_length=200)]
    git_url: Annotated[str, Field(min_length=1)]
    ref: str | None = None
    pat: SecretStr | None = None
