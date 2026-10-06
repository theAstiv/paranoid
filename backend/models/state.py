"""Core Pydantic models for state management."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

from backend.models.enums import AssetType, StrideCategory
from backend.scoring.cvss31 import Cvss31Metrics as CvssVector


# Constants for validation
SUMMARY_MAX_WORDS = 40
THREAT_DESCRIPTION_MIN_WORDS = 35
THREAT_DESCRIPTION_MAX_WORDS = 50
MITIGATION_MIN_ITEMS = 2
MITIGATION_MAX_ITEMS = 5


class DreadScore(BaseModel):
    """DREAD risk assessment scoring model.

    Scores use float to match prompt anchor values (0, 2.5, 5, 7.5, 10).
    """

    damage: Annotated[
        float,
        Field(ge=0, le=10, description="Damage potential (0-10)"),
    ]
    reproducibility: Annotated[
        float,
        Field(ge=0, le=10, description="How easy to reproduce (0-10)"),
    ]
    exploitability: Annotated[
        float,
        Field(ge=0, le=10, description="How easy to exploit (0-10)"),
    ]
    affected_users: Annotated[
        float,
        Field(ge=0, le=10, description="Number of affected users (0-10)"),
    ]
    discoverability: Annotated[
        float,
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


class SummaryState(BaseModel):
    """Model representing the summary of a threat catalog."""

    summary: Annotated[
        str,
        Field(description=f"A short headline summary of max {SUMMARY_MAX_WORDS} words"),
    ]


class Asset(BaseModel):
    """Model representing system assets or entities in threat modeling."""

    type: Annotated[
        AssetType,
        Field(description="Type: Asset or Entity"),
    ]
    name: Annotated[str, Field(description="The name of the asset")]
    description: Annotated[str, Field(description="The description of the asset or entity")]


class AssetsList(BaseModel):
    """Collection of system assets for threat modeling."""

    assets: Annotated[list[Asset], Field(description="The list of assets")]


class DataFlow(BaseModel):
    """Model representing data flow between entities in a system architecture."""

    flow_description: Annotated[str, Field(description="The description of the data flow")]
    source_entity: Annotated[str, Field(description="The source entity/asset of the data flow")]
    target_entity: Annotated[str, Field(description="The target entity/asset of the data flow")]


class TrustBoundary(BaseModel):
    """Model representing trust boundaries between entities in system architecture."""

    purpose: Annotated[str, Field(description="The purpose of the trust boundary")]
    source_entity: Annotated[
        str, Field(description="The source entity/asset of the trust boundary")
    ]
    target_entity: Annotated[
        str, Field(description="The target entity/asset of the trust boundary")
    ]


class ThreatSource(BaseModel):
    """Model representing sources of threats in the system."""

    category: Annotated[str, Field(description="The category of the threat source")]
    description: Annotated[str, Field(description="The description of the threat source")]
    # Illustrative only — not read by any downstream node or the frontend
    # today. Optional because some models (e.g. claude-sonnet-5) reliably
    # omit it despite the schema instruction, which otherwise fails the
    # whole extract_flows call over a field nothing actually consumes.
    example: Annotated[str, Field(description="An example of the threat source")] = ""


class FlowsList(BaseModel):
    """Collection of data flows, trust boundaries, and threat sources."""

    data_flows: Annotated[list[DataFlow], Field(description="The list of data flows")]
    trust_boundaries: Annotated[
        list[TrustBoundary], Field(description="The list of trust boundaries")
    ]
    threat_sources: Annotated[list[ThreatSource], Field(description="The list of threat actors")]


class DependencyRef(BaseModel):
    """Provenance for a threat derived from the dependency capability engine."""

    package: str
    version: str
    file: str | None = None
    line: int | None = None
    rule_id: str | None = None


class TechniqueRef(BaseModel):
    """A MITRE ATT&CK / ATLAS technique matched to a threat by map_techniques.

    `method` records how the match was made and is what the UI and exports
    use to decide whether to present it as confirmed or as a guess:
    - "table": a dependency-engine rule_id resolved deterministically via a
      fixed lookup table. Trusted.
    - "seed": extracted from a parenthesized ID already embedded in a
      rule-engine seed pattern's name. Trusted (the ID was curated by hand
      into the seed, not matched by similarity).
    - "embedding": ranked by cosine+keyword similarity against the
      catalog. The measured golden-set precision@3 is well below the
      project's target bar — see tests/live/test_attack_mapping_golden.py —
      so these are guesses, not confirmed matches, regardless of their
      confidence score.
    """

    id: str
    name: str
    url: str
    confidence: Annotated[float, Field(ge=0, le=1)]
    method: Literal["table", "seed", "embedding"] = "embedding"


class Threat(BaseModel):
    """Model representing an identified security threat."""

    name: Annotated[str, Field(description="The name of the threat")]
    stride_category: Annotated[
        StrideCategory,
        Field(description="The STRIDE category of the threat"),
    ]
    description: Annotated[
        str,
        Field(
            description=f"The exhaustive description of the threat. From {THREAT_DESCRIPTION_MIN_WORDS} "
            f"to {THREAT_DESCRIPTION_MAX_WORDS} words. Follow threat grammar structure."
        ),
    ]
    target: Annotated[str, Field(description="The target of the threat")]
    impact: Annotated[str, Field(description="The impact of the threat")]
    likelihood: Annotated[str, Field(description="The likelihood of the threat")]
    dread: Annotated[
        DreadScore | None,
        Field(description="Optional DREAD risk assessment scoring"),
    ] = None
    # CVSS v3.1 base metrics. The prompt only asks for this when the model's
    # scoring_method includes "cvss" (day 2 — the CVSS instruction block is
    # not yet wired into stride.py/maestro.py). Until then generate_threats()
    # force-clears it on every "dread"-scored run regardless of what a
    # provider returns. Like dread/stride_category, this is a plain
    # LLM-writable field — a bad answer here is a review problem, not a
    # provenance attack.
    cvss: Annotated[
        CvssVector | None,
        Field(
            description="Optional CVSS v3.1 base metrics (requested only when scoring_method includes cvss)"
        ),
    ] = None
    mitigations: Annotated[
        list[str],
        Field(
            description="The list of mitigations for the threat",
            min_length=MITIGATION_MIN_ITEMS,
            max_length=MITIGATION_MAX_ITEMS,
        ),
    ]

    # SkipJsonSchema hides both fields from the schema sent to providers
    # (Anthropic tool_use, OpenAI response_format, Ollama/Bedrock format=) —
    # all four call Threat.model_json_schema() or an equivalent that respects
    # it. Without this an LLM (or a prompt-injected description) could set
    # source="dependency" and forge a dependency_ref with a fabricated
    # package/file/line. Only trusted code (rule engine, seeding, the
    # dependency-capability engine) sets these; generate_threats() also
    # force-resets both fields on every provider response as a second layer.
    source: SkipJsonSchema[str] = Field(default="llm")
    # Provenance when source == "dependency" — which package/file/rule this
    # threat came from. None for llm/rule_engine/seeded threats.
    dependency_ref: SkipJsonSchema[DependencyRef | None] = None
    # MITRE ATT&CK / ATLAS techniques matched by the deterministic
    # map_techniques pipeline step. Hidden from providers for the same
    # reason as source/dependency_ref: an LLM must never invent technique
    # IDs. generate_threats() force-resets this to [] on every response.
    attack_techniques: SkipJsonSchema[list[TechniqueRef]] = []
    # The CVSS score/severity are NEVER LLM-sourced, even though `cvss`
    # (the 8 base metrics) is: these two are hidden from providers and
    # force-computed from `cvss` by generate_threats() (and the
    # deterministic dependency-threat path) right after the provider call,
    # so the number a reviewer sees always matches backend.scoring.cvss31's
    # formula applied to the metrics, never a value a provider invented.
    cvss_score: SkipJsonSchema[float | None] = None
    cvss_severity: SkipJsonSchema[str | None] = None


class ThreatsList(BaseModel):
    """Collection of identified security threats."""

    threats: Annotated[list[Threat], Field(description="The list of threats")]

    def __add__(self, other: "ThreatsList") -> "ThreatsList":
        """Combine two ThreatsList instances."""
        combined_threats = self.threats + other.threats
        return ThreatsList(threats=combined_threats)


# Response model for dread-only generate_threats() calls, so the schema sent
# to the provider doesn't carry the CVSS metrics object at all (unlike
# Threat, where `cvss` is present but cvss_score/cvss_severity are hidden).
# Measured (see test_dread_only_schema_hides_cvss_entirely, which fails if
# this drifts): ThreatsList.model_json_schema() is 4,689 chars vs.
# ThreatsListDreadOnly's 2,788 — dropping the Cvss31Metrics $defs entry and
# its 8 enum-constrained properties. Paid on every provider call for every
# scoring_method, including a dread-only run that never asks the LLM to fill
# `cvss` (see generate_threats()'s force-clear in
# backend/pipeline/nodes/threats.py). Under OpenAI strict mode it's not just
# a one-time schema-definition cost either: a required-but-nullable `cvss`
# means the model writes "cvss": null on every threat, every iteration,
# every dread-only call — this variant removes that too.
#
# IMPORTANT: keep both classes' docstrings to one line. Pydantic embeds a
# model's docstring verbatim as its JSON-schema "description", so a long one
# here would eat back the size saving this class exists for.
class _ThreatDreadOnly(Threat):
    """Same as Threat, with `cvss` also hidden from the provider schema."""

    cvss: SkipJsonSchema[CvssVector | None] = None


class ThreatsListDreadOnly(BaseModel):
    """Response model for a dread-only generate_threats() call."""

    threats: Annotated[list[_ThreatDreadOnly], Field(description="The list of threats")]


class GapAnalysis(BaseModel):
    """Model representing gap analysis for iterative threat modeling."""

    stop: Annotated[
        bool,
        Field(
            description="Should continue evaluation for further threats or is the catalog comprehensive"
        ),
    ]
    gap: Annotated[
        str | None,
        Field(
            description="An in-depth gap analysis on how to improve the threat catalog. Required when stop is False"
        ),
    ] = None


# Alias for compatibility
ContinueThreatModeling = GapAnalysis


class PipelineState(BaseModel):
    """Container for pipeline state during threat modeling execution."""

    summary: str | None = None
    assets: AssetsList | None = None
    flows: FlowsList | None = None
    threats: ThreatsList | None = None
    gap_analysis: list[str] = []
    iteration: int = 1
    stop: bool = False
