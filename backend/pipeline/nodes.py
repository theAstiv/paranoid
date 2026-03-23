"""Pipeline nodes for threat modeling — plain async functions.

Each node is an independent async function that takes structured input and returns
structured output. No classes, no LangChain, no state management — just pure logic.
"""

import asyncio
from typing import Optional

from backend.models.enums import Framework
from backend.models.extended import AttackTree, CodeContext, TestSuite
from backend.models.state import (
    AssetsList,
    ContinueThreatModeling,
    FlowsList,
    SummaryState,
    ThreatsList,
)
from backend.pipeline.prompts import (
    attack_tree_prompt,
    maestro_asset_prompt,
    maestro_gap_prompt,
    maestro_improve_prompt,
    maestro_threats_prompt,
    stride_asset_prompt,
    stride_flow_prompt,
    stride_gap_prompt,
    stride_summary_prompt,
    stride_threats_improve_prompt,
    stride_threats_prompt,
    test_case_prompt,
)
from backend.providers.base import LLMProvider


def _build_xml_tag(tag: str, content: str) -> str:
    """Build an XML tag with content."""
    if not content or content.strip() == "":
        return ""
    return f"<{tag}>\n{content.strip()}\n</{tag}>\n\n"


def _format_assumptions(assumptions: Optional[list[str]]) -> str:
    """Format assumptions list as a string."""
    if not assumptions:
        return ""
    return "\n".join(f"- {assumption}" for assumption in assumptions)


async def summarize(
    description: str,
    architecture_diagram: Optional[str],
    assumptions: Optional[list[str]],
    code_context: Optional[CodeContext],
    provider: LLMProvider,
    temperature: float = 0.2,
) -> SummaryState:
    """Generate system summary from description and optional diagram/code context.

    Args:
        description: User-provided system description
        architecture_diagram: Optional diagram data (could be text description or base64 image)
        assumptions: Optional list of assumptions about the system
        code_context: Optional code context from MCP server
        provider: LLM provider for generation
        temperature: Sampling temperature

    Returns:
        SummaryState with generated summary
    """
    system_prompt = stride_summary_prompt()

    # Build prompt with XML tags
    prompt_parts = []

    if architecture_diagram:
        prompt_parts.append(_build_xml_tag("architecture_diagram", architecture_diagram))

    prompt_parts.append(_build_xml_tag("description", description))

    if assumptions:
        assumptions_text = _format_assumptions(assumptions)
        prompt_parts.append(_build_xml_tag("assumptions", assumptions_text))

    if code_context:
        code_text = f"Repository: {code_context.repository}\n\n"
        for file in code_context.files:
            code_text += f"## {file.path}\n{file.content}\n\n"
        prompt_parts.append(_build_xml_tag("code_context", code_text))

    user_prompt = "".join(prompt_parts)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    # Generate structured output
    response = await provider.generate_structured(
        prompt=full_prompt,
        response_model=SummaryState,
        temperature=temperature,
    )

    return response


async def extract_assets(
    summary: str,
    description: str,
    architecture_diagram: Optional[str],
    assumptions: Optional[list[str]],
    framework: Framework,
    provider: LLMProvider,
    temperature: float = 0.2,
) -> AssetsList:
    """Extract assets and entities from system description.

    Args:
        summary: Generated system summary
        description: Original system description
        architecture_diagram: Optional diagram data
        assumptions: Optional assumptions
        framework: STRIDE or MAESTRO framework
        provider: LLM provider
        temperature: Sampling temperature

    Returns:
        AssetsList with identified assets and entities
    """
    # Select prompt based on framework
    if framework == Framework.MAESTRO:
        system_prompt = maestro_asset_prompt()
    else:
        system_prompt = stride_asset_prompt()

    # Build prompt
    prompt_parts = []

    if architecture_diagram:
        prompt_parts.append(_build_xml_tag("architecture_diagram", architecture_diagram))

    prompt_parts.append(_build_xml_tag("description", description))

    if assumptions:
        assumptions_text = _format_assumptions(assumptions)
        prompt_parts.append(_build_xml_tag("assumptions", assumptions_text))

    user_prompt = "".join(prompt_parts)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    # Generate structured output
    response = await provider.generate_structured(
        prompt=full_prompt,
        response_model=AssetsList,
        temperature=temperature,
    )

    return response


async def extract_flows(
    summary: str,
    description: str,
    architecture_diagram: Optional[str],
    assumptions: Optional[list[str]],
    assets: AssetsList,
    provider: LLMProvider,
    temperature: float = 0.2,
) -> FlowsList:
    """Extract data flows, trust boundaries, and threat sources.

    Args:
        summary: Generated system summary
        description: Original system description
        architecture_diagram: Optional diagram data
        assumptions: Optional assumptions
        assets: Previously extracted assets
        provider: LLM provider
        temperature: Sampling temperature

    Returns:
        FlowsList with data flows, trust boundaries, and threat sources
    """
    system_prompt = stride_flow_prompt()

    # Build prompt
    prompt_parts = []

    if architecture_diagram:
        prompt_parts.append(_build_xml_tag("architecture_diagram", architecture_diagram))

    prompt_parts.append(_build_xml_tag("description", description))

    if assumptions:
        assumptions_text = _format_assumptions(assumptions)
        prompt_parts.append(_build_xml_tag("assumptions", assumptions_text))

    # Add assets
    assets_text = "## Assets\n"
    for asset in assets.assets_list:
        assets_text += f"- **{asset.name}** ({asset.type}): {asset.description}\n"
    prompt_parts.append(_build_xml_tag("identified_assets_and_entities", assets_text))

    user_prompt = "".join(prompt_parts)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    # Generate structured output
    response = await provider.generate_structured(
        prompt=full_prompt,
        response_model=FlowsList,
        temperature=temperature,
    )

    return response


async def generate_threats(
    description: str,
    architecture_diagram: Optional[str],
    assumptions: Optional[list[str]],
    assets: AssetsList,
    flows: FlowsList,
    framework: Framework,
    provider: LLMProvider,
    existing_threats: Optional[ThreatsList] = None,
    gap_analysis: Optional[str] = None,
    rag_context: Optional[list[str]] = None,
    temperature: float = 0.2,
) -> ThreatsList:
    """Generate or improve threat catalog.

    Args:
        description: System description
        architecture_diagram: Optional diagram data
        assumptions: Optional assumptions
        assets: Identified assets
        flows: Identified flows
        framework: STRIDE or MAESTRO framework
        provider: LLM provider
        existing_threats: Optional existing threats for improvement iteration
        gap_analysis: Optional gap analysis feedback
        rag_context: Optional similar approved threats from vector store
        temperature: Sampling temperature

    Returns:
        ThreatsList with generated threats
    """
    # Select prompt based on framework and iteration
    if existing_threats and gap_analysis:
        # Improvement iteration
        if framework == Framework.MAESTRO:
            system_prompt = maestro_improve_prompt()
        else:
            system_prompt = stride_threats_improve_prompt()
    else:
        # Initial iteration
        if framework == Framework.MAESTRO:
            system_prompt = maestro_threats_prompt()
        else:
            system_prompt = stride_threats_prompt()

    # Build prompt
    prompt_parts = []

    if architecture_diagram:
        prompt_parts.append(_build_xml_tag("architecture_diagram", architecture_diagram))

    prompt_parts.append(_build_xml_tag("description", description))

    if assumptions:
        assumptions_text = _format_assumptions(assumptions)
        prompt_parts.append(_build_xml_tag("assumptions", assumptions_text))

    # Add assets
    assets_text = "## Assets\n"
    for asset in assets.assets_list:
        assets_text += f"- **{asset.name}** ({asset.type}): {asset.description}\n"
    prompt_parts.append(_build_xml_tag("identified_assets_and_entities", assets_text))

    # Add flows
    flows_text = "## Data Flows\n"
    for flow in flows.data_flows:
        flows_text += f"- {flow.source} → {flow.target}: {flow.description}\n"
    flows_text += "\n## Trust Boundaries\n"
    for boundary in flows.trust_boundaries:
        flows_text += f"- {boundary.source} ↔ {boundary.target}: {boundary.description}\n"
    prompt_parts.append(_build_xml_tag("data_flow", flows_text))

    # Add existing threats if improvement iteration
    if existing_threats:
        threats_text = "## Existing Threats\n"
        for threat in existing_threats.threat_list:
            threats_text += f"### {threat.name}\n"
            threats_text += f"- **Category**: {threat.stride_category}\n"
            threats_text += f"- **Target**: {threat.target}\n"
            threats_text += f"- **Description**: {threat.description}\n"
            threats_text += f"- **Impact**: {threat.impact}\n"
            threats_text += f"- **Likelihood**: {threat.likelihood}\n"
            threats_text += f"- **Mitigations**: {', '.join(threat.mitigations)}\n\n"
        prompt_parts.append(_build_xml_tag("threats", threats_text))

    # Add gap analysis if present
    if gap_analysis:
        prompt_parts.append(_build_xml_tag("gap", gap_analysis))

    # Add RAG context if present
    if rag_context:
        rag_text = "## Similar Approved Threats (for reference)\n"
        for idx, threat_text in enumerate(rag_context, 1):
            rag_text += f"### Similar Threat {idx}\n{threat_text}\n\n"
        prompt_parts.append(_build_xml_tag("similar_threats", rag_text))

    user_prompt = "".join(prompt_parts)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    # Generate structured output
    response = await provider.generate_structured(
        prompt=full_prompt,
        response_model=ThreatsList,
        temperature=temperature,
    )

    return response


async def gap_analysis(
    description: str,
    architecture_diagram: Optional[str],
    assumptions: Optional[list[str]],
    assets: AssetsList,
    flows: FlowsList,
    threats: ThreatsList,
    framework: Framework,
    provider: LLMProvider,
    previous_gaps: Optional[list[str]] = None,
    temperature: float = 0.2,
) -> ContinueThreatModeling:
    """Analyze gaps in threat coverage.

    Args:
        description: System description
        architecture_diagram: Optional diagram data
        assumptions: Optional assumptions
        assets: Identified assets
        flows: Identified flows
        threats: Generated threats
        framework: STRIDE or MAESTRO framework
        provider: LLM provider
        previous_gaps: Optional list of previously identified gaps
        temperature: Sampling temperature

    Returns:
        ContinueThreatModeling with stop decision and gap description
    """
    # Select prompt based on framework
    if framework == Framework.MAESTRO:
        system_prompt = maestro_gap_prompt()
    else:
        system_prompt = stride_gap_prompt()

    # Build prompt
    prompt_parts = []

    if architecture_diagram:
        prompt_parts.append(_build_xml_tag("architecture_diagram", architecture_diagram))

    prompt_parts.append(_build_xml_tag("description", description))

    if assumptions:
        assumptions_text = _format_assumptions(assumptions)
        prompt_parts.append(_build_xml_tag("assumptions", assumptions_text))

    # Add assets
    assets_text = "## Assets\n"
    for asset in assets.assets_list:
        assets_text += f"- **{asset.name}** ({asset.type}): {asset.description}\n"
    prompt_parts.append(_build_xml_tag("identified_assets_and_entities", assets_text))

    # Add flows
    flows_text = "## Data Flows\n"
    for flow in flows.data_flows:
        flows_text += f"- {flow.source} → {flow.target}: {flow.description}\n"
    flows_text += "\n## Trust Boundaries\n"
    for boundary in flows.trust_boundaries:
        flows_text += f"- {boundary.source} ↔ {boundary.target}: {boundary.description}\n"
    prompt_parts.append(_build_xml_tag("data_flow", flows_text))

    # Add threats
    threats_text = "## Generated Threats\n"
    for threat in threats.threat_list:
        threats_text += f"### {threat.name}\n"
        threats_text += f"- **Category**: {threat.stride_category}\n"
        threats_text += f"- **Target**: {threat.target}\n"
        threats_text += f"- **Description**: {threat.description}\n"
        threats_text += f"- **Impact**: {threat.impact}\n"
        threats_text += f"- **Likelihood**: {threat.likelihood}\n\n"
    prompt_parts.append(_build_xml_tag("threats", threats_text))

    # Add previous gaps if present
    if previous_gaps:
        previous_gaps_text = "\n".join(f"- {gap}" for gap in previous_gaps)
        prompt_parts.append(_build_xml_tag("previous_gap", previous_gaps_text))

    user_prompt = "".join(prompt_parts)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    # Generate structured output
    response = await provider.generate_structured(
        prompt=full_prompt,
        response_model=ContinueThreatModeling,
        temperature=temperature,
    )

    return response


async def generate_attack_tree(
    threat: str,
    threat_description: str,
    target: str,
    stride_category: Optional[str],
    maestro_category: Optional[str],
    mitigations: list[str],
    provider: LLMProvider,
    temperature: float = 0.3,
) -> AttackTree:
    """Generate attack tree for a specific threat.

    Args:
        threat: Threat name
        threat_description: Detailed threat description
        target: Target asset/component
        stride_category: Optional STRIDE category
        maestro_category: Optional MAESTRO category
        mitigations: List of mitigations
        provider: LLM provider
        temperature: Sampling temperature (slightly higher for creativity)

    Returns:
        AttackTree with Mermaid.js graph
    """
    system_prompt = attack_tree_prompt()

    # Build prompt
    prompt_parts = [
        _build_xml_tag("threat_name", threat),
        _build_xml_tag("threat_description", threat_description),
        _build_xml_tag("target", target),
    ]

    if stride_category:
        prompt_parts.append(_build_xml_tag("stride_category", stride_category))

    if maestro_category:
        prompt_parts.append(_build_xml_tag("maestro_category", maestro_category))

    mitigations_text = "\n".join(f"- {mitigation}" for mitigation in mitigations)
    prompt_parts.append(_build_xml_tag("mitigations", mitigations_text))

    user_prompt = "".join(prompt_parts)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    # Generate structured output
    response = await provider.generate_structured(
        prompt=full_prompt,
        response_model=AttackTree,
        temperature=temperature,
    )

    return response


async def generate_test_cases(
    threat: str,
    threat_description: str,
    target: str,
    mitigations: list[str],
    provider: LLMProvider,
    temperature: float = 0.3,
) -> TestSuite:
    """Generate Gherkin test cases for a specific threat.

    Args:
        threat: Threat name
        threat_description: Detailed threat description
        target: Target asset/component
        mitigations: List of mitigations to validate
        provider: LLM provider
        temperature: Sampling temperature

    Returns:
        TestSuite with Gherkin feature and scenarios
    """
    system_prompt = test_case_prompt()

    # Build prompt
    prompt_parts = [
        _build_xml_tag("threat_name", threat),
        _build_xml_tag("threat_description", threat_description),
        _build_xml_tag("target", target),
    ]

    mitigations_text = "\n".join(f"- {mitigation}" for mitigation in mitigations)
    prompt_parts.append(_build_xml_tag("mitigations", mitigations_text))

    user_prompt = "".join(prompt_parts)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    # Generate structured output
    response = await provider.generate_structured(
        prompt=full_prompt,
        response_model=TestSuite,
        temperature=temperature,
    )

    return response
