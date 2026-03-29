"""Extended Pydantic models for Paranoid-specific functionality."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

from backend.models.enums import (
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
        Field(description="Orchestration framework, languages, infrastructure, supporting services"),
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
        Field(description="Whether the system has AI/ML components (triggers MAESTRO alongside STRIDE)"),
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
