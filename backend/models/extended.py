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


class DreadScore(BaseModel):
    """DREAD risk assessment scoring model."""

    damage: Annotated[
        int,
        Field(ge=0, le=10, description="Damage potential (0-10)"),
    ]
    reproducibility: Annotated[
        int,
        Field(ge=0, le=10, description="How easy to reproduce (0-10)"),
    ]
    exploitability: Annotated[
        int,
        Field(ge=0, le=10, description="How easy to exploit (0-10)"),
    ]
    affected_users: Annotated[
        int,
        Field(ge=0, le=10, description="Number of affected users (0-10)"),
    ]
    discoverability: Annotated[
        int,
        Field(ge=0, le=10, description="How easy to discover (0-10)"),
    ]

    @property
    def score(self) -> float:
        """Calculate average DREAD score."""
        return (
            self.damage
            + self.reproducibility
            + self.exploitability
            + self.affected_users
            + self.discoverability
        ) / 5.0


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
