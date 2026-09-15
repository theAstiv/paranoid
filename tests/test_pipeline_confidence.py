"""Tests for backend.pipeline.confidence — threat confidence scoring."""

from backend.models.enums import StrideCategory
from backend.models.state import Threat
from backend.pipeline.confidence import score_threat_confidence


def _make_threat(
    name: str = "Test Threat",
    target: str = "API Gateway",
    description: str = (
        "An attacker exploits SQL injection in the API Gateway endpoint "
        "to extract sensitive user data from the PostgreSQL database"
    ),
    source: str = "llm",
) -> Threat:
    threat = Threat(
        name=name,
        stride_category=StrideCategory.TAMPERING,
        description=description,
        target=target,
        impact="High",
        likelihood="Medium",
        mitigations=["Use parameterized queries", "Input validation"],
    )
    threat._source = source
    return threat


SAMPLE_ASSETS = [
    {"name": "API Gateway", "type": "Asset", "description": "Public entry point"},
    {"name": "PostgreSQL Database", "type": "Asset", "description": "Primary data store"},
    {"name": "Redis Cache", "type": "Asset", "description": "Session cache"},
]

SAMPLE_FLOWS = [
    {
        "source_entity": "API Gateway",
        "target_entity": "PostgreSQL Database",
        "flow_description": "User queries forwarded to database",
    },
    {
        "source_entity": "API Gateway",
        "target_entity": "Redis Cache",
        "flow_description": "Session lookups for authentication",
    },
]

SAMPLE_DESCRIPTION = (
    "A REST API service with an API Gateway frontend, PostgreSQL database, "
    "and Redis cache for session management. Handles user authentication "
    "and data CRUD operations."
)


class TestAssetMatchHighConfidence:
    def test_target_matches_asset_name(self):
        threat = _make_threat(target="API Gateway")
        score = score_threat_confidence(threat, SAMPLE_ASSETS, SAMPLE_FLOWS, SAMPLE_DESCRIPTION)
        assert score > 0.5

    def test_target_with_flow_refs_scores_highest(self):
        threat = _make_threat(
            target="API Gateway",
            description=(
                "An attacker exploits SQL injection in the API Gateway endpoint "
                "to extract data from the PostgreSQL Database via Redis Cache bypass"
            ),
        )
        score = score_threat_confidence(threat, SAMPLE_ASSETS, SAMPLE_FLOWS, SAMPLE_DESCRIPTION)
        assert score > 0.6


class TestGenericThreatLowConfidence:
    def test_completely_generic(self):
        threat = _make_threat(
            target="The System",
            description=(
                "An attacker could compromise the system and gain "
                "unauthorized access to resources causing damage to the organization "
                "through various attack vectors and exploitation techniques"
            ),
        )
        score = score_threat_confidence(threat, [], [], "")
        assert score < 0.4

    def test_generic_with_no_assets(self):
        threat = _make_threat(
            target="Unknown Component",
            description=(
                "An attacker could potentially exploit a vulnerability in the "
                "system to cause disruption and gain elevated privileges within "
                "the application boundary leading to data exposure"
            ),
        )
        score = score_threat_confidence(threat, [], [], "A web application")
        assert score < 0.5


class TestRuleEngineOverride:
    def test_rule_engine_returns_fixed_score(self):
        threat = _make_threat(source="rule_engine")
        score = score_threat_confidence(threat, [], [], "")
        assert score == 0.85

    def test_rule_engine_ignores_content(self):
        threat = _make_threat(
            target="Nonexistent Thing",
            description=(
                "An attacker could compromise the system and gain "
                "unauthorized access to sensitive data through various vectors "
                "which are not specifically mentioned anywhere in this model"
            ),
            source="rule_engine",
        )
        score = score_threat_confidence(threat, SAMPLE_ASSETS, SAMPLE_FLOWS, SAMPLE_DESCRIPTION)
        assert score == 0.85


class TestEdgeCases:
    def test_empty_assets_no_crash(self):
        threat = _make_threat()
        score = score_threat_confidence(threat, [], SAMPLE_FLOWS, SAMPLE_DESCRIPTION)
        assert 0.0 <= score <= 1.0

    def test_empty_flows_no_crash(self):
        threat = _make_threat()
        score = score_threat_confidence(threat, SAMPLE_ASSETS, [], SAMPLE_DESCRIPTION)
        assert 0.0 <= score <= 1.0

    def test_empty_description_no_crash(self):
        threat = _make_threat()
        score = score_threat_confidence(threat, SAMPLE_ASSETS, SAMPLE_FLOWS, "")
        assert 0.0 <= score <= 1.0

    def test_all_empty_no_crash(self):
        threat = _make_threat()
        score = score_threat_confidence(threat, [], [], "")
        assert 0.0 <= score <= 1.0

    def test_score_bounded(self):
        threat = _make_threat()
        score = score_threat_confidence(threat, SAMPLE_ASSETS, SAMPLE_FLOWS, SAMPLE_DESCRIPTION)
        assert 0.0 <= score <= 1.0
