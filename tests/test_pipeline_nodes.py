"""Tests for pipeline node functions (backend/pipeline/nodes.py).

Each async node is tested with MockProvider. Error tests use error_types
to trigger ProviderError on specific response models (per RULES.md).
"""

import pytest

from backend.models.enums import Framework
from backend.models.extended import AttackTree, CodeSummary, TestSuite
from backend.models.state import (
    AssetsList,
    FlowsList,
    GapAnalysis,
    SummaryState,
    ThreatsList,
)
from backend.pipeline import nodes
from backend.providers.base import ProviderError
from tests.fixtures.pipeline import (
    make_assets,
    make_code_context,
    make_code_summary,
    make_flows,
    make_stride_threats,
)
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


# ---------------------------------------------------------------------------
# Code context tests (MCP code-as-input)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_code_with_code_context(mock_provider):
    """Test code summarization with MockProvider."""
    code_context = make_code_context()
    result = await nodes.summarize_code(
        code_context=code_context,
        provider=mock_provider,
    )
    assert isinstance(result, CodeSummary)
    assert len(result.tech_stack) > 0
    assert len(result.entry_points) > 0
    assert len(result.raw_summary) > 0
    assert len(mock_provider.calls) == 1
    assert mock_provider.calls[0]["response_model"] is CodeSummary


@pytest.mark.asyncio
async def test_summarize_code_deterministic_fallback():
    """Test deterministic fallback when LLM fails."""
    provider = MockProvider()
    provider.error_types.add(CodeSummary)
    code_context = make_code_context()

    # Should not raise - falls back to deterministic extraction
    result = await nodes.summarize_code(
        code_context=code_context,
        provider=provider,
    )

    assert isinstance(result, CodeSummary)
    # Deterministic fallback should still extract basic info
    assert len(result.tech_stack) > 0
    assert len(result.raw_summary) > 0


def test_format_code_context_helper():
    """Test _format_code_context XML formatting."""
    code_context = make_code_context()
    result = nodes._format_code_context(code_context)

    assert "Repository:" in result
    assert "/home/user/document-sharing-app" in result
    assert "backend/routes/documents.py" in result
    # Should escape XML special characters
    assert "&lt;" in result or "<" not in result  # Either escaped or no raw <
    assert "##" in result  # Markdown header for file paths


def test_format_code_summary_helper():
    """Test _format_code_summary XML formatting."""
    code_summary = make_code_summary()
    result = nodes._format_code_summary(code_summary)

    assert "**Technology Stack:**" in result
    assert "Python 3.11" in result or "FastAPI" in result
    assert "**Entry Points:**" in result
    assert "POST /api/documents" in result or "GET /api/" in result
    assert "**Authentication" in result
    assert "**Data Stores:**" in result
    assert "**Security Observations:**" in result
    assert "**Summary:**" in result


@pytest.mark.asyncio
async def test_extract_assets_with_code_summary(mock_provider):
    """Test extract_assets receives and uses code_summary."""
    code_summary = make_code_summary()
    result = await nodes.extract_assets(
        summary="A document sharing web app",
        description="Users upload and share documents via API",
        architecture_diagram=None,
        assumptions=None,
        framework=Framework.STRIDE,
        code_summary=code_summary,
        provider=mock_provider,
    )

    assert isinstance(result, AssetsList)
    assert len(result.assets) > 0
    # Verify the prompt included code summary
    call = mock_provider.calls[0]
    assert call["prompt_length"] > 1000  # Longer due to code summary


@pytest.mark.asyncio
async def test_extract_flows_with_code_summary(mock_provider):
    """Test extract_flows receives and uses code_summary."""
    code_summary = make_code_summary()
    assets = make_assets()
    result = await nodes.extract_flows(
        summary="A document sharing web app",
        description="Users upload and share documents",
        architecture_diagram=None,
        assumptions=None,
        assets=assets,
        code_summary=code_summary,
        provider=mock_provider,
    )

    assert isinstance(result, FlowsList)
    assert len(result.data_flows) > 0
    # Verify code summary was included in prompt
    call = mock_provider.calls[0]
    assert call["prompt_length"] > 1000


@pytest.mark.asyncio
async def test_generate_threats_with_code_summary(mock_provider):
    """Test generate_threats receives and uses code_summary."""
    code_summary = make_code_summary()
    assets = make_assets()
    flows = make_flows()
    result = await nodes.generate_threats(
        description="Users upload and share documents via API gateway",
        architecture_diagram=None,
        assumptions=None,
        assets=assets,
        flows=flows,
        framework=Framework.STRIDE,
        code_summary=code_summary,
        provider=mock_provider,
    )

    assert isinstance(result, ThreatsList)
    assert len(result.threats) == 6
    # Verify code summary was included in prompt
    call = mock_provider.calls[0]
    assert call["prompt_length"] > 2000


@pytest.mark.asyncio
async def test_gap_analysis_with_code_summary(mock_provider):
    """Test gap_analysis receives and uses code_summary."""
    code_summary = make_code_summary()
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
        code_summary=code_summary,
        provider=mock_provider,
    )

    assert isinstance(result, GapAnalysis)
    assert result.stop is False
    # Verify code summary was included in prompt
    call = mock_provider.calls[0]
    assert call["prompt_length"] > 2000


def test_deterministic_code_summary_extraction():
    """Test deterministic extraction of CodeSummary from CodeContext."""
    code_context = make_code_context()
    result = nodes._deterministic_code_summary(code_context)

    assert isinstance(result, CodeSummary)
    # Should detect Python from file extensions
    assert any("python" in tech.lower() for tech in result.tech_stack)
    # Should detect FastAPI from imports
    assert any("fastapi" in tech.lower() for tech in result.tech_stack)
    # Should detect HTTP routes
    assert len(result.entry_points) > 0
    assert any("/api/" in ep for ep in result.entry_points)
    # Should detect security issues
    assert len(result.security_observations) > 0
    # Should have a summary
    assert len(result.raw_summary) >= 100
