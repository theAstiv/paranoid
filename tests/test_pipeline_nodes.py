"""Tests for pipeline node functions (backend/pipeline/nodes.py).

Each async node is tested with MockProvider. Error tests use error_types
to trigger ProviderError on specific response models (per RULES.md).
"""

import pytest

from backend.models.enums import Framework
from backend.models.extended import AttackTree, TestSuite
from backend.models.state import (
    AssetsList,
    FlowsList,
    GapAnalysis,
    SummaryState,
    ThreatsList,
)
from backend.pipeline import nodes
from backend.providers.base import ProviderError
from tests.fixtures.pipeline import make_assets, make_flows, make_stride_threats
from tests.mock_provider import MockProvider


# ---------------------------------------------------------------------------
# Pure helpers (no mock needed)
# ---------------------------------------------------------------------------


class TestBuildXmlTag:
    def test_wraps_content_in_tag(self):
        result = nodes._build_xml_tag("description", "hello world")
        assert result == "<description>\nhello world\n</description>\n\n"

    def test_strips_whitespace(self):
        result = nodes._build_xml_tag("tag", "  padded  ")
        assert "<tag>\npadded\n</tag>" in result

    def test_empty_content_returns_empty_string(self):
        assert nodes._build_xml_tag("tag", "") == ""
        assert nodes._build_xml_tag("tag", "   ") == ""


class TestFormatAssumptions:
    def test_formats_list_as_bullets(self):
        result = nodes._format_assumptions(["First", "Second"])
        assert result == "- First\n- Second"

    def test_none_returns_empty(self):
        assert nodes._format_assumptions(None) == ""

    def test_empty_list_returns_empty(self):
        assert nodes._format_assumptions([]) == ""


class TestParseStructuredInput:
    def test_plain_text_returns_no_structured_data(self):
        component, assumptions, plain = nodes._parse_structured_input(
            "A simple web application", Framework.STRIDE
        )
        assert component is None
        assert assumptions is None
        assert plain == "A simple web application"

    def test_stride_structured_input(self):
        stride_input = (
            "<component_description>\n"
            "<name>Auth Service</name>\n"
            "<type>Backend Service</type>\n"
            "<description>Handles authentication</description>\n"
            "</component_description>\n"
        )
        component, assumptions, plain = nodes._parse_structured_input(
            stride_input, Framework.STRIDE
        )
        # Structured input detected — component should be parsed (or None if tags incomplete)
        # The plain description is always returned as-is
        assert plain == stride_input


# ---------------------------------------------------------------------------
# Async node happy paths (MockProvider)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_returns_summary_state(mock_provider):
    result = await nodes.summarize(
        description="A document sharing web application",
        architecture_diagram=None,
        assumptions=None,
        code_context=None,
        provider=mock_provider,
    )
    assert isinstance(result, SummaryState)
    assert len(result.summary) > 0
    assert len(mock_provider.calls) == 1
    assert mock_provider.calls[0]["response_model"] is SummaryState


@pytest.mark.asyncio
async def test_extract_assets_stride(mock_provider):
    result = await nodes.extract_assets(
        summary="A document sharing web app",
        description="Users upload and share documents via API",
        architecture_diagram=None,
        assumptions=None,
        framework=Framework.STRIDE,
        provider=mock_provider,
    )
    assert isinstance(result, AssetsList)
    assert len(result.assets) > 0


@pytest.mark.asyncio
async def test_extract_assets_maestro(mock_provider_maestro):
    result = await nodes.extract_assets(
        summary="An AI-powered doc classifier",
        description="ML model classifies uploaded documents",
        architecture_diagram=None,
        assumptions=None,
        framework=Framework.MAESTRO,
        provider=mock_provider_maestro,
    )
    assert isinstance(result, AssetsList)


@pytest.mark.asyncio
async def test_extract_flows(mock_provider):
    assets = make_assets()
    result = await nodes.extract_flows(
        summary="A document sharing web app",
        description="Users upload and share documents",
        architecture_diagram=None,
        assumptions=None,
        assets=assets,
        provider=mock_provider,
    )
    assert isinstance(result, FlowsList)
    assert len(result.data_flows) > 0
    assert len(result.trust_boundaries) > 0


@pytest.mark.asyncio
async def test_generate_threats_initial(mock_provider):
    assets = make_assets()
    flows = make_flows()
    result = await nodes.generate_threats(
        description="Users upload and share documents via API gateway",
        architecture_diagram=None,
        assumptions=None,
        assets=assets,
        flows=flows,
        framework=Framework.STRIDE,
        provider=mock_provider,
    )
    assert isinstance(result, ThreatsList)
    assert len(result.threats) == 6  # One per STRIDE category


@pytest.mark.asyncio
async def test_generate_threats_improvement_iteration(mock_provider):
    assets = make_assets()
    flows = make_flows()
    existing = make_stride_threats()
    result = await nodes.generate_threats(
        description="Users upload and share documents",
        architecture_diagram=None,
        assumptions=None,
        assets=assets,
        flows=flows,
        framework=Framework.STRIDE,
        provider=mock_provider,
        existing_threats=existing,
        gap_analysis="Missing XSS and SSRF threats",
    )
    assert isinstance(result, ThreatsList)


@pytest.mark.asyncio
async def test_generate_threats_with_rag_context(mock_provider):
    assets = make_assets()
    flows = make_flows()
    result = await nodes.generate_threats(
        description="Users upload and share documents",
        architecture_diagram=None,
        assumptions=None,
        assets=assets,
        flows=flows,
        framework=Framework.STRIDE,
        provider=mock_provider,
        rag_context=["SQL injection on user search endpoint", "CSRF on delete action"],
    )
    assert isinstance(result, ThreatsList)


@pytest.mark.asyncio
async def test_gap_analysis_continues(mock_provider):
    assets = make_assets()
    flows = make_flows()
    threats = make_stride_threats()
    result = await nodes.gap_analysis(
        description="Document sharing web app",
        architecture_diagram=None,
        assumptions=None,
        assets=assets,
        flows=flows,
        threats=threats,
        framework=Framework.STRIDE,
        provider=mock_provider,
    )
    assert isinstance(result, GapAnalysis)
    assert result.stop is False
    assert result.gap is not None


@pytest.mark.asyncio
async def test_gap_analysis_stops():
    provider = MockProvider(gap_call_threshold=1)
    assets = make_assets()
    flows = make_flows()
    threats = make_stride_threats()
    result = await nodes.gap_analysis(
        description="Document sharing web app",
        architecture_diagram=None,
        assumptions=None,
        assets=assets,
        flows=flows,
        threats=threats,
        framework=Framework.STRIDE,
        provider=provider,
    )
    assert isinstance(result, GapAnalysis)
    assert result.stop is True


@pytest.mark.asyncio
async def test_generate_attack_tree(mock_provider):
    result = await nodes.generate_attack_tree(
        threat="SQL Injection",
        threat_description="Attacker injects SQL via search endpoint",
        target="PostgreSQL Database",
        stride_category="tampering",
        maestro_category=None,
        mitigations=["Parameterized queries", "Input validation"],
        provider=mock_provider,
    )
    assert isinstance(result, AttackTree)
    assert "graph" in result.mermaid_source.lower() or "TD" in result.mermaid_source


@pytest.mark.asyncio
async def test_generate_test_cases(mock_provider):
    result = await nodes.generate_test_cases(
        threat="SQL Injection",
        threat_description="Attacker injects SQL via search endpoint",
        target="PostgreSQL Database",
        mitigations=["Parameterized queries", "Input validation"],
        provider=mock_provider,
    )
    assert isinstance(result, TestSuite)
    assert "Scenario" in result.gherkin_source


# ---------------------------------------------------------------------------
# Error paths (ProviderError on specific response models)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_raises_on_provider_error():
    provider = MockProvider()
    provider.error_types.add(SummaryState)
    with pytest.raises(ProviderError):
        await nodes.summarize(
            description="A web app",
            architecture_diagram=None,
            assumptions=None,
            code_context=None,
            provider=provider,
        )


@pytest.mark.asyncio
async def test_extract_assets_raises_on_provider_error():
    provider = MockProvider()
    provider.error_types.add(AssetsList)
    with pytest.raises(ProviderError):
        await nodes.extract_assets(
            summary="Summary",
            description="Description",
            architecture_diagram=None,
            assumptions=None,
            framework=Framework.STRIDE,
            provider=provider,
        )


@pytest.mark.asyncio
async def test_generate_threats_raises_on_provider_error():
    provider = MockProvider()
    provider.error_types.add(ThreatsList)
    with pytest.raises(ProviderError):
        await nodes.generate_threats(
            description="Description",
            architecture_diagram=None,
            assumptions=None,
            assets=make_assets(),
            flows=make_flows(),
            framework=Framework.STRIDE,
            provider=provider,
        )


@pytest.mark.asyncio
async def test_gap_analysis_raises_on_provider_error():
    provider = MockProvider()
    provider.error_types.add(GapAnalysis)
    with pytest.raises(ProviderError):
        await nodes.gap_analysis(
            description="Description",
            architecture_diagram=None,
            assumptions=None,
            assets=make_assets(),
            flows=make_flows(),
            threats=make_stride_threats(),
            framework=Framework.STRIDE,
            provider=provider,
        )


@pytest.mark.asyncio
async def test_generate_attack_tree_raises_on_provider_error():
    provider = MockProvider()
    provider.error_types.add(AttackTree)
    with pytest.raises(ProviderError):
        await nodes.generate_attack_tree(
            threat="SQL Injection",
            threat_description="Injection via search",
            target="Database",
            stride_category="tampering",
            maestro_category=None,
            mitigations=["Parameterized queries"],
            provider=provider,
        )
