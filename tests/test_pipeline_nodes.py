"""Tests for pipeline node functions (backend/pipeline/nodes.py).

Each async node is tested with MockProvider. Error tests use error_types
to trigger ProviderError on specific response models (per RULES.md).
"""

import pytest

from backend.models.enums import Framework
from backend.models.extended import AttackTree, CodeContext, CodeFile, CodeSummary, TestSuite
from backend.models.state import (
    AssetsList,
    FlowsList,
    GapAnalysis,
    SummaryState,
    ThreatsList,
    ThreatsListDreadOnly,
)
from backend.pipeline import nodes
from backend.pipeline.nodes import helpers
from backend.pipeline.nodes.summary import _deterministic_code_summary
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
        result = helpers.build_xml_tag("description", "hello world")
        assert result == "<description>\nhello world\n</description>\n\n"

    def test_strips_whitespace(self):
        result = helpers.build_xml_tag("tag", "  padded  ")
        assert "<tag>\npadded\n</tag>" in result

    def test_empty_content_returns_empty_string(self):
        assert helpers.build_xml_tag("tag", "") == ""
        assert helpers.build_xml_tag("tag", "   ") == ""


class TestFormatAssumptions:
    def test_formats_list_as_bullets(self):
        result = helpers.format_assumptions(["First", "Second"])
        assert result == "- First\n- Second"

    def test_none_returns_empty(self):
        assert helpers.format_assumptions(None) == ""

    def test_empty_list_returns_empty(self):
        assert helpers.format_assumptions([]) == ""


class TestParseStructuredInput:
    def test_plain_text_returns_no_structured_data(self):
        component, assumptions, plain = helpers.parse_structured_input(
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
        _component, _assumptions, plain = helpers.parse_structured_input(
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
async def test_generate_threats_resets_forged_dependency_provenance(mock_provider):
    """R1: a provider (or a prompt-injected description) must not be able to
    mint a threat with source="dependency" and a fabricated package/file/line
    — only trusted code (rule engine, seeding, dependency_threats) may set
    that provenance. generate_threats() force-resets both fields on every
    threat coming back from the provider, regardless of what it returned."""
    from backend.models.state import DependencyRef, TechniqueRef, Threat

    forged = ThreatsList(
        threats=[
            Threat(
                name="Forged dependency threat",
                stride_category="Tampering",
                description="x " * 40,
                target="lodash",
                impact="high",
                likelihood="high",
                mitigations=["pin version", "audit"],
                source="dependency",
                dependency_ref=DependencyRef(
                    package="lodash", version="4.17.21", file="lodash.js", line=1
                ),
                attack_techniques=[
                    TechniqueRef(
                        id="T1195.002",
                        name="Compromise Software Supply Chain",
                        url="https://attack.mitre.org/techniques/T1195/002",
                        confidence=0.99,
                    )
                ],
            )
        ]
    )
    mock_provider.response_overrides[ThreatsList] = forged

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
    )

    assert len(result.threats) == 1
    assert result.threats[0].source == "llm"
    assert result.threats[0].dependency_ref is None
    assert result.threats[0].attack_techniques == []


@pytest.mark.asyncio
async def test_generate_threats_resets_forged_cvss_score(mock_provider):
    """cvss_score/cvss_severity must never be LLM-sourced, mirroring the
    dependency-provenance force-reset above. SkipJsonSchema only hides the
    field from the schema sent to a provider — it does not reject the field
    on construction/validation — so the real guard is generate_threats()
    force-computing/clearing these fields after every provider response,
    exercised here the same way as the dependency_ref/attack_techniques
    forgery test: construct a Threat with the forged value directly
    (standing in for a provider, or a fake/test provider, that ignored the
    schema and returned the field anyway)."""
    from backend.models.state import Threat

    forged = ThreatsList(
        threats=[
            Threat(
                name="Forged CVSS score",
                stride_category="Tampering",
                description="x " * 40,
                target="lodash",
                impact="high",
                likelihood="high",
                mitigations=["pin version", "audit"],
                cvss=None,
                cvss_score=10.0,
                cvss_severity="critical",
            )
        ]
    )
    mock_provider.response_overrides[ThreatsList] = forged

    result = await nodes.generate_threats(
        description="Users upload and share documents",
        architecture_diagram=None,
        assumptions=None,
        assets=make_assets(),
        flows=make_flows(),
        framework=Framework.STRIDE,
        provider=mock_provider,
        scoring_method="cvss",
    )

    assert result.threats[0].cvss_score is None
    assert result.threats[0].cvss_severity is None


@pytest.mark.asyncio
async def test_generate_threats_computes_cvss_score_from_metrics(mock_provider):
    """When scoring_method includes "cvss" and the provider returns valid
    cvss metrics, the score/severity are computed server-side from them —
    never trusted even if the provider also sent its own score (covered by
    the forged-score test above)."""
    from backend.models.state import Threat
    from backend.scoring.cvss31 import Cvss31Metrics, score_and_severity_from_metrics

    metrics = Cvss31Metrics(
        attack_vector="N",
        attack_complexity="L",
        privileges_required="N",
        user_interaction="N",
        scope="U",
        confidentiality="H",
        integrity="H",
        availability="H",
    )
    response = ThreatsList(
        threats=[
            Threat(
                name="SQL Injection",
                stride_category="Tampering",
                description="x " * 40,
                target="DB",
                impact="high",
                likelihood="high",
                mitigations=["pin version", "audit"],
                cvss=metrics,
            )
        ]
    )
    mock_provider.response_overrides[ThreatsList] = response

    result = await nodes.generate_threats(
        description="Users upload and share documents",
        architecture_diagram=None,
        assumptions=None,
        assets=make_assets(),
        flows=make_flows(),
        framework=Framework.STRIDE,
        provider=mock_provider,
        scoring_method="cvss",
    )

    expected_score, expected_severity = score_and_severity_from_metrics(metrics)
    threat = result.threats[0]
    assert threat.cvss_score == pytest.approx(expected_score)
    assert threat.cvss_severity == expected_severity
    assert expected_score == pytest.approx(9.8)
    assert expected_severity == "critical"


@pytest.mark.asyncio
async def test_generate_threats_default_scoring_method_clears_cvss(mock_provider):
    """Default scoring_method ("dread") must clear `cvss` too, not just the
    score/severity — "nothing changes unless chosen" holds on the stored
    data even if a provider fills `cvss` in on a dread-only run."""
    from backend.models.state import Threat
    from backend.scoring.cvss31 import Cvss31Metrics

    metrics = Cvss31Metrics(
        attack_vector="N",
        attack_complexity="L",
        privileges_required="N",
        user_interaction="N",
        scope="U",
        confidentiality="H",
        integrity="H",
        availability="H",
    )
    response = ThreatsList(
        threats=[
            Threat(
                name="SQL Injection",
                stride_category="Tampering",
                description="x " * 40,
                target="DB",
                impact="high",
                likelihood="high",
                mitigations=["pin version", "audit"],
                cvss=metrics,
            )
        ]
    )
    mock_provider.response_overrides[ThreatsList] = response

    result = await nodes.generate_threats(
        description="Users upload and share documents",
        architecture_diagram=None,
        assumptions=None,
        assets=make_assets(),
        flows=make_flows(),
        framework=Framework.STRIDE,
        provider=mock_provider,
        # scoring_method omitted -> default "dread"
    )

    threat = result.threats[0]
    assert threat.cvss is None
    assert threat.cvss_score is None
    assert threat.cvss_severity is None


@pytest.mark.asyncio
async def test_generate_threats_dread_only_prompt_has_no_cvss_section(mock_provider):
    """The CVSS instruction block is appended only when scoring_method !=
    "dread" — mirrors the dependency_capabilities "append only if relevant"
    pattern in helpers.py. A dread-only run's prompt must not mention CVSS
    at all, so a dread-only demo/screenshot never shows the new section."""
    await nodes.generate_threats(
        description="Users upload and share documents",
        architecture_diagram=None,
        assumptions=None,
        assets=make_assets(),
        flows=make_flows(),
        framework=Framework.STRIDE,
        provider=mock_provider,
        scoring_method="dread",
    )

    assert "CVSS" not in mock_provider.last_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scoring_method", "expected_model"),
    [("dread", ThreatsListDreadOnly), ("cvss", ThreatsList), ("both", ThreatsList)],
)
async def test_generate_threats_requests_schema_matching_scoring_method(
    mock_provider, scoring_method, expected_model
):
    """A dread-only run must request ThreatsListDreadOnly (the schema
    without `cvss`) from the provider — not just avoid showing it in the
    prompt. cvss/both runs still need the full ThreatsList schema."""
    await nodes.generate_threats(
        description="Users upload and share documents",
        architecture_diagram=None,
        assumptions=None,
        assets=make_assets(),
        flows=make_flows(),
        framework=Framework.STRIDE,
        provider=mock_provider,
        scoring_method=scoring_method,
    )

    threat_calls = [
        c for c in mock_provider.calls if c["response_model"] in (ThreatsList, ThreatsListDreadOnly)
    ]
    assert len(threat_calls) == 1
    assert threat_calls[0]["response_model"] is expected_model


@pytest.mark.asyncio
async def test_generate_threats_starts_at_the_auto_bump_ceiling(mock_provider):
    """generate_threats asks for 16,384 output tokens up front. Starting at
    4,096 made every live iteration-1 call truncate twice (4,096 -> 8,192 ->
    16,384) before completing; the ceiling itself is unchanged."""
    await nodes.generate_threats(
        description="Users upload and share documents",
        architecture_diagram=None,
        assumptions=None,
        assets=make_assets(),
        flows=make_flows(),
        framework=Framework.STRIDE,
        provider=mock_provider,
    )

    threat_calls = [
        c for c in mock_provider.calls if c["response_model"] in (ThreatsList, ThreatsListDreadOnly)
    ]
    assert [c["max_tokens"] for c in threat_calls] == [16384]


@pytest.mark.asyncio
async def test_generate_threats_normalizes_real_threatslistdreadonly_response(mock_provider):
    """MockProvider canonicalizes ThreatsListDreadOnly -> ThreatsList before
    returning (so other tests can share fixtures/overrides across both), so
    nothing above exercises what a *real* provider does: validate the raw
    response directly against the schema it was asked for, producing actual
    _ThreatDreadOnly instances. Use a bare-bones fake that skips the
    canonicalization and returns a real ThreatsListDreadOnly, to confirm
    `ThreatsList(threats=raw_response.threats)` in generate_threats()
    normalizes those subclass instances without error and that the
    force-clear still nulls cvss/cvss_score/cvss_severity on them."""
    from backend.models.state import ThreatsListDreadOnly

    class _RealSchemaProvider(MockProvider):
        async def generate_structured(self, prompt, response_model, **kwargs):
            self.last_prompt = prompt
            if response_model is ThreatsListDreadOnly:
                return ThreatsListDreadOnly.model_validate(
                    {
                        "threats": [
                            {
                                "name": "SQL Injection",
                                "stride_category": "Tampering",
                                "description": "x " * 40,
                                "target": "DB",
                                "impact": "high",
                                "likelihood": "high",
                                "mitigations": ["pin version", "audit"],
                            }
                        ]
                    }
                )
            return await super().generate_structured(prompt, response_model, **kwargs)

    provider = _RealSchemaProvider()
    result = await nodes.generate_threats(
        description="Users upload and share documents",
        architecture_diagram=None,
        assumptions=None,
        assets=make_assets(),
        flows=make_flows(),
        framework=Framework.STRIDE,
        provider=provider,
        scoring_method="dread",
    )

    assert isinstance(result, ThreatsList)
    threat = result.threats[0]
    # Confirms the subclass instance round-trips cleanly through
    # ThreatsList(threats=raw_response.threats) and model_dump().
    threat.model_dump()
    assert threat.cvss is None
    assert threat.cvss_score is None
    assert threat.cvss_severity is None


@pytest.mark.asyncio
@pytest.mark.parametrize("scoring_method", ["cvss", "both"])
@pytest.mark.parametrize("framework", [Framework.STRIDE, Framework.MAESTRO])
async def test_generate_threats_cvss_prompt_has_scoring_section(
    mock_provider, scoring_method, framework
):
    """Both STRIDE and MAESTRO prompts get the CVSS section when
    scoring_method is "cvss" or "both", for both the initial and
    improve-iteration templates."""
    mock_provider._framework = framework

    await nodes.generate_threats(
        description="Users upload and share documents",
        architecture_diagram=None,
        assumptions=None,
        assets=make_assets(),
        flows=make_flows(),
        framework=framework,
        provider=mock_provider,
        scoring_method=scoring_method,
    )

    assert "CVSS v3.1 Base Scoring" in mock_provider.last_prompt
    assert "Attack Vector (AV)" in mock_provider.last_prompt

    # Must land *inside* the <instructions> block, not appended after its
    # closing tag — all four prompt templates wrap their numbered sections
    # in one <instructions>...</instructions> block.
    prompt = mock_provider.last_prompt
    cvss_idx = prompt.index("CVSS v3.1 Base Scoring")
    closing_idx = prompt.rindex("</instructions>")
    assert cvss_idx < closing_idx


@pytest.mark.asyncio
async def test_generate_threats_cvss_prompt_improve_iteration_has_scoring_section(
    mock_provider,
):
    """The improve-iteration prompt (existing_threats + gap_analysis set)
    also gets the CVSS section when requested."""
    await nodes.generate_threats(
        description="Users upload and share documents",
        architecture_diagram=None,
        assumptions=None,
        assets=make_assets(),
        flows=make_flows(),
        framework=Framework.STRIDE,
        provider=mock_provider,
        existing_threats=make_stride_threats(),
        gap_analysis="Missing coverage for X",
        scoring_method="cvss",
    )

    assert "CVSS v3.1 Base Scoring" in mock_provider.last_prompt


class TestThreatSchemaHidesDependencyProvenance:
    """R1: source/dependency_ref must never appear in the JSON schema sent to
    an LLM provider — that schema is the structured-output contract every
    provider (Anthropic tool_use, OpenAI response_format, Ollama/Bedrock
    format=) sends to the model, so a visible field is a mintable field.
    attack_techniques follows the same rule for the same reason."""

    def test_source_and_dependency_ref_absent_from_schema(self):
        from backend.models.state import Threat

        schema = Threat.model_json_schema()
        assert "source" not in schema.get("properties", {})
        assert "dependency_ref" not in schema.get("properties", {})
        assert "attack_techniques" not in schema.get("properties", {})

    def test_threats_list_schema_excludes_dependency_provenance(self):
        schema = ThreatsList.model_json_schema()
        # Threat is a $defs entry referenced from the "threats" array item.
        threat_def = schema.get("$defs", {}).get("Threat", {})
        assert "source" not in threat_def.get("properties", {})
        assert "dependency_ref" not in threat_def.get("properties", {})
        assert "attack_techniques" not in threat_def.get("properties", {})


class TestThreatSchemaCvssScoreNeverLlmSourced:
    """CVSS metrics (`cvss`) are a normal LLM-writable field — a bad answer
    there is a review problem, not a provenance attack, same tier as
    stride_category/dread. But `cvss_score`/`cvss_severity` must never be
    LLM-trusted: they're always computed server-side from `cvss` by
    backend.scoring.cvss31, so they follow the same SkipJsonSchema rule as
    source/dependency_ref/attack_techniques."""

    def test_cvss_metrics_present_cvss_score_and_severity_hidden(self):
        from backend.models.state import Threat

        schema = Threat.model_json_schema()
        properties = schema.get("properties", {})
        assert "cvss" in properties
        assert "cvss_score" not in properties
        assert "cvss_severity" not in properties

    def test_threats_list_schema_hides_cvss_score_and_severity(self):
        schema = ThreatsList.model_json_schema()
        threat_def = schema.get("$defs", {}).get("Threat", {})
        assert "cvss" in threat_def.get("properties", {})
        assert "cvss_score" not in threat_def.get("properties", {})
        assert "cvss_severity" not in threat_def.get("properties", {})

    def test_cvss_metrics_are_enum_constrained(self):
        """Each of the 8 base metrics must surface as a JSON Schema enum —
        confirms the Literal fields on Cvss31Metrics constrain the provider
        schema the same way SkipJsonSchema/Literal already do elsewhere."""
        schema = ThreatsList.model_json_schema()
        cvss_def = schema.get("$defs", {}).get("Cvss31Metrics", {})
        properties = cvss_def.get("properties", {})
        assert set(properties) == {
            "attack_vector",
            "attack_complexity",
            "privileges_required",
            "user_interaction",
            "scope",
            "confidentiality",
            "integrity",
            "availability",
        }
        for field_schema in properties.values():
            assert "enum" in field_schema, field_schema

    def test_dread_only_schema_hides_cvss_entirely(self):
        """ThreatsListDreadOnly (the response model generate_threats() uses
        for scoring_method="dread") must not mention `cvss` at all — unlike
        ThreatsList, where `cvss` is present but score/severity are hidden.
        This is what actually avoids paying for the field on a dread-only
        call, not just a comment claiming the cost is accepted."""
        import json

        from backend.models.state import ThreatsListDreadOnly

        schema = ThreatsListDreadOnly.model_json_schema()
        threat_def = schema.get("$defs", {}).get("_ThreatDreadOnly", {})
        assert "cvss" not in threat_def.get("properties", {})
        assert "cvss_score" not in threat_def.get("properties", {})
        assert "cvss_severity" not in threat_def.get("properties", {})
        assert "Cvss31Metrics" not in schema.get("$defs", {})

        # Measured, not asserted-to-be-smaller-by-magic: confirms the schema
        # sent on a dread-only call is substantially smaller than the
        # cvss/both schema (full ThreatsList), which is what the #117 review
        # flagged as an unmeasured ~72% schema growth.
        full_chars = len(json.dumps(ThreatsList.model_json_schema()))
        dread_only_chars = len(json.dumps(schema))
        assert dread_only_chars < full_chars * 0.7


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
    """Test format_code_context XML formatting."""
    code_context = make_code_context()
    result = helpers.format_code_context(code_context)

    assert "Repository:" in result
    assert "/home/user/document-sharing-app" in result
    assert "backend/routes/documents.py" in result
    # Should escape XML special characters
    assert "&lt;" in result or "<" not in result  # Either escaped or no raw <
    assert "##" in result  # Markdown header for file paths


def test_format_code_summary_helper():
    """Test format_code_summary XML formatting."""
    code_summary = make_code_summary()
    result = helpers.format_code_summary(code_summary)

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
    result = _deterministic_code_summary(code_context)

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


def test_deterministic_code_summary_with_json_skeleton():
    """Skeleton files from context-link tier 3 should be parsed for patterns."""
    import json as _json

    skeleton_content = _json.dumps(
        {
            "symbols": [
                {"signature": "from fastapi import APIRouter", "kind": "import"},
                {"signature": "@router.post('/api/users')", "kind": "function"},
            ]
        }
    )
    code_context = CodeContext(
        repository="/repo/test-app",
        files=[
            CodeFile(path="routes/users.py", language="python", content=skeleton_content),
        ],
    )
    result = _deterministic_code_summary(code_context)
    assert "FastAPI" in result.tech_stack
    assert any("/api/users" in ep for ep in result.entry_points)


# ---------------------------------------------------------------------------
# Diagram integration tests (PNG/JPG/Mermaid via vision API)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_with_png_diagram():
    """Test summarize passes PNG diagram via images parameter."""
    from backend.models.enums import DiagramFormat
    from backend.models.extended import DiagramData

    diagram_data = DiagramData(
        format=DiagramFormat.PNG,
        source_path="test.png",
        base64_data="base64encodeddata",
        media_type="image/png",
        size_bytes=1000,
    )

    provider = MockProvider()
    result = await nodes.summarize(
        description="Test system",
        architecture_diagram=None,
        assumptions=None,
        code_context=None,
        provider=provider,
        diagrams=[diagram_data],
    )

    # Verify images parameter was passed to provider
    assert provider.last_images is not None
    assert len(provider.last_images) == 1
    assert provider.last_images[0].data == "base64encodeddata"
    assert provider.last_images[0].media_type == "image/png"

    # Verify placeholder tag was added to prompt
    assert "[Provided as vision image 1 of 1]" in provider.last_prompt


@pytest.mark.asyncio
async def test_summarize_with_mermaid_diagram():
    """Test summarize injects Mermaid source into prompt."""
    from backend.models.enums import DiagramFormat
    from backend.models.extended import DiagramData

    diagram_data = DiagramData(
        format=DiagramFormat.MERMAID,
        source_path="flow.mmd",
        mermaid_source="graph TD\n  A-->B",
    )

    provider = MockProvider()
    result = await nodes.summarize(
        description="Test system",
        architecture_diagram=None,
        assumptions=None,
        code_context=None,
        provider=provider,
        diagrams=[diagram_data],
    )

    # Verify images parameter is None for Mermaid
    assert provider.last_images is None

    # Verify Mermaid source appears in prompt XML tag
    assert "<architecture_diagram " in provider.last_prompt
    assert "graph TD" in provider.last_prompt
    assert "A-->B" in provider.last_prompt


@pytest.mark.asyncio
async def test_summarize_without_diagram():
    """Test summarize works without diagram (backward compat)."""
    provider = MockProvider()
    result = await nodes.summarize(
        description="Test system",
        architecture_diagram=None,
        assumptions=None,
        code_context=None,
        provider=provider,
        diagrams=None,
    )

    # Verify no images parameter
    assert provider.last_images is None

    # Verify no architecture_diagram tag in prompt (no data to inject)
    # (instructions may mention it, but no actual tag with content)
    assert result.summary  # Just verify it worked


@pytest.mark.asyncio
async def test_summarize_with_legacy_diagram_string():
    """Test summarize still supports legacy architecture_diagram: str."""
    provider = MockProvider()
    result = await nodes.summarize(
        description="Test system",
        architecture_diagram="Legacy diagram description text",
        assumptions=None,
        code_context=None,
        provider=provider,
        diagrams=None,
    )

    # Verify no images parameter for legacy string
    assert provider.last_images is None

    # Verify legacy diagram text appears in prompt
    assert "Legacy diagram description text" in provider.last_prompt


@pytest.mark.asyncio
async def test_generate_threats_with_jpeg_diagram():
    """Test generate_threats passes JPEG via images parameter."""
    from backend.models.enums import DiagramFormat
    from backend.models.extended import DiagramData

    diagram_data = DiagramData(
        format=DiagramFormat.JPEG,
        source_path="arch.jpg",
        base64_data="jpegbase64",
        media_type="image/jpeg",
        size_bytes=2000,
    )

    assets = make_assets()
    flows = make_flows()

    provider = MockProvider()
    result = await nodes.generate_threats(
        description="Test system",
        architecture_diagram=None,
        assumptions=None,
        assets=assets,
        flows=flows,
        framework=Framework.STRIDE,
        provider=provider,
        diagrams=[diagram_data],
    )

    # Verify images parameter was passed
    assert provider.last_images is not None
    assert len(provider.last_images) == 1
    assert provider.last_images[0].media_type == "image/jpeg"

    # Verify placeholder tag
    assert "[Provided as vision image 1 of 1]" in provider.last_prompt
