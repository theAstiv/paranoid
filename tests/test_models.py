"""Tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from backend.models import (
    Asset,
    AssetsList,
    AssetType,
    AttackTree,
    DataFlow,
    DreadScore,
    FlowsList,
    Framework,
    GapAnalysis,
    HybridThreat,
    ImpactLevel,
    LikelihoodLevel,
    MaestroCategory,
    MaestroThreat,
    Provider,
    StrideCategory,
    SummaryState,
    TestCase,
    Threat,
    ThreatModelConfig,
    ThreatsList,
    ThreatSource,
    TrustBoundary,
)


def test_stride_category_enum():
    """Test STRIDE category enum values."""
    assert StrideCategory.SPOOFING.value == "Spoofing"
    assert StrideCategory.TAMPERING.value == "Tampering"
    assert StrideCategory.INFORMATION_DISCLOSURE.value == "Information Disclosure"


def test_maestro_category_enum():
    """Test MAESTRO category enum values."""
    assert MaestroCategory.MODEL_SECURITY.value == "Model Security"
    assert MaestroCategory.LLM_SECURITY.value == "LLM Security"
    assert MaestroCategory.PRIVACY.value == "Privacy"


def test_asset_creation():
    """Test creating an Asset."""
    asset = Asset(
        type=AssetType.ASSET, name="Database", description="PostgreSQL database"
    )
    assert asset.name == "Database"
    assert asset.type == AssetType.ASSET


def test_assets_list_creation():
    """Test creating an AssetsList."""
    assets = AssetsList(
        assets=[
            Asset(type=AssetType.ASSET, name="API", description="REST API"),
            Asset(type=AssetType.ENTITY, name="User", description="End user"),
        ]
    )
    assert len(assets.assets) == 2
    assert assets.assets[0].name == "API"


def test_data_flow_creation():
    """Test creating a DataFlow."""
    flow = DataFlow(
        flow_description="User authentication",
        source_entity="Client",
        target_entity="API Gateway",
    )
    assert flow.source_entity == "Client"
    assert flow.target_entity == "API Gateway"


def test_trust_boundary_creation():
    """Test creating a TrustBoundary."""
    boundary = TrustBoundary(
        purpose="Separate public from private network",
        source_entity="Internet",
        target_entity="DMZ",
    )
    assert boundary.purpose == "Separate public from private network"


def test_threat_source_creation():
    """Test creating a ThreatSource."""
    source = ThreatSource(
        category="External Attacker",
        description="Malicious actor from internet",
        example="Script kiddie using automated tools",
    )
    assert source.category == "External Attacker"


def test_flows_list_creation():
    """Test creating a FlowsList."""
    flows = FlowsList(
        data_flows=[
            DataFlow(
                flow_description="Login", source_entity="Client", target_entity="API"
            )
        ],
        trust_boundaries=[
            TrustBoundary(purpose="DMZ", source_entity="Internet", target_entity="DMZ")
        ],
        threat_sources=[
            ThreatSource(
                category="Attacker",
                description="External threat",
                example="Hacker",
            )
        ],
    )
    assert len(flows.data_flows) == 1
    assert len(flows.trust_boundaries) == 1
    assert len(flows.threat_sources) == 1


def test_threat_creation():
    """Test creating a Threat."""
    threat = Threat(
        name="SQL Injection",
        stride_category=StrideCategory.TAMPERING,
        description="An attacker can inject malicious SQL code through the login form, "
        "potentially accessing or modifying database contents. This occurs when user "
        "input is not properly sanitized before being used in SQL queries, allowing "
        "arbitrary SQL execution.",
        target="Database",
        impact="High",
        likelihood="Medium",
        mitigations=["Use parameterized queries", "Input validation"],
    )
    assert threat.name == "SQL Injection"
    assert threat.stride_category == StrideCategory.TAMPERING
    assert len(threat.mitigations) == 2


def test_threat_mitigation_validation():
    """Test that threat mitigations must have 2-5 items."""
    # Too few mitigations
    with pytest.raises(ValidationError):
        Threat(
            name="Test",
            stride_category=StrideCategory.SPOOFING,
            description="A" * 40,  # 40 words minimum
            target="Target",
            impact="High",
            likelihood="Low",
            mitigations=["Only one mitigation"],  # Less than min_length=2
        )


def test_threats_list_addition():
    """Test adding two ThreatsList instances."""
    list1 = ThreatsList(
        threats=[
            Threat(
                name="Threat 1",
                stride_category=StrideCategory.SPOOFING,
                description="Test " * 8,
                target="Target",
                impact="High",
                likelihood="Low",
                mitigations=["Mit1", "Mit2"],
            )
        ]
    )
    list2 = ThreatsList(
        threats=[
            Threat(
                name="Threat 2",
                stride_category=StrideCategory.TAMPERING,
                description="Test " * 8,
                target="Target",
                impact="Medium",
                likelihood="High",
                mitigations=["Mit3", "Mit4"],
            )
        ]
    )

    combined = list1 + list2
    assert len(combined.threats) == 2
    assert combined.threats[0].name == "Threat 1"
    assert combined.threats[1].name == "Threat 2"


def test_summary_state_creation():
    """Test creating a SummaryState."""
    summary = SummaryState(summary="Web application with user authentication")
    assert summary.summary == "Web application with user authentication"


def test_gap_analysis_creation():
    """Test creating a GapAnalysis."""
    gap = GapAnalysis(
        stop=False,
        gap="Need to analyze additional authentication threats",
    )
    assert gap.stop is False
    assert gap.gap is not None


def test_dread_score_calculation():
    """Test DREAD score calculation."""
    dread = DreadScore(
        damage=8, reproducibility=7, exploitability=6, affected_users=9, discoverability=5
    )
    assert dread.score == 7.0  # (8+7+6+9+5)/5


def test_dread_score_validation():
    """Test DREAD score validation (0-10 range)."""
    with pytest.raises(ValidationError):
        DreadScore(
            damage=11,  # Out of range
            reproducibility=7,
            exploitability=6,
            affected_users=9,
            discoverability=5,
        )


def test_maestro_threat_creation():
    """Test creating a MAESTRO threat."""
    threat = MaestroThreat(
        name="Model Inversion Attack",
        maestro_category=MaestroCategory.MODEL_SECURITY,
        description="Attacker reconstructs training data through repeated queries",
        target="ML Model API",
        impact=ImpactLevel.HIGH,
        likelihood=LikelihoodLevel.MEDIUM,
        mitigations=["Add differential privacy", "Rate limiting"],
    )
    assert threat.maestro_category == MaestroCategory.MODEL_SECURITY
    assert threat.impact == ImpactLevel.HIGH


def test_hybrid_threat_creation():
    """Test creating a hybrid STRIDE+MAESTRO threat."""
    threat = HybridThreat(
        name="Prompt Injection",
        stride_category=StrideCategory.TAMPERING,
        maestro_category=MaestroCategory.LLM_SECURITY,
        description="Malicious prompts bypass safety controls",
        target="LLM Application",
        impact=ImpactLevel.HIGH,
        likelihood=LikelihoodLevel.HIGH,
        dread=DreadScore(
            damage=8,
            reproducibility=9,
            exploitability=7,
            affected_users=6,
            discoverability=8,
        ),
        mitigations=["Input filtering", "Output validation"],
    )
    assert threat.stride_category == StrideCategory.TAMPERING
    assert threat.maestro_category == MaestroCategory.LLM_SECURITY
    assert threat.dread is not None
    assert threat.dread.score == 7.6


def test_attack_tree_creation():
    """Test creating an AttackTree."""
    tree = AttackTree(
        threat_name="SQL Injection",
        mermaid_source="graph TD\n  A[SQL Injection] --> B[Exploit Input Field]",
    )
    assert tree.threat_name == "SQL Injection"
    assert "graph TD" in tree.mermaid_source


def test_test_case_creation():
    """Test creating a TestCase."""
    test_case = TestCase(
        threat_name="SQL Injection",
        gherkin_source="Given a login form\nWhen I enter malicious SQL\nThen the system rejects it",
    )
    assert test_case.threat_name == "SQL Injection"
    assert "Given" in test_case.gherkin_source


def test_threat_model_config_validation():
    """Test ThreatModelConfig validation."""
    config = ThreatModelConfig(
        title="Test Model",
        description="Test system",
        framework=Framework.STRIDE,
        provider=Provider.ANTHROPIC,
        model="claude-sonnet-4",
        iteration_count=3,
        temperature=0.0,
    )
    assert config.iteration_count == 3
    assert config.framework == Framework.STRIDE

    # Test iteration_count range validation
    with pytest.raises(ValidationError):
        ThreatModelConfig(
            title="Test",
            description="Test",
            provider=Provider.ANTHROPIC,
            model="claude-sonnet-4",
            iteration_count=20,  # Exceeds max of 15
        )
