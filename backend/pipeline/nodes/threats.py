"""Threat generation and gap analysis nodes.

Contains generate_threats() for creating/improving threat catalogs, and
gap_analysis() for identifying coverage gaps across STRIDE/MAESTRO categories.
"""

from backend.models.enums import DiagramFormat, Framework
from backend.models.extended import CodeSummary, DiagramData, ImageContent
from backend.models.state import AssetsList, FlowsList, GapAnalysis, ThreatsList
from backend.pipeline.nodes.helpers import (
    build_assumptions_section,
    build_xml_tag,
    format_code_summary,
    format_structured_component_for_prompt,
    parse_structured_input,
)
from backend.pipeline.prompts import (
    maestro_gap_prompt,
    maestro_improve_prompt,
    maestro_threats_prompt,
    stride_gap_prompt,
    stride_threats_improve_prompt,
    stride_threats_prompt,
)
from backend.providers.base import LLMProvider


async def generate_threats(
    description: str,
    architecture_diagram: str | None,
    assumptions: list[str] | None,
    assets: AssetsList,
    flows: FlowsList,
    framework: Framework,
    provider: LLMProvider,
    existing_threats: ThreatsList | None = None,
    gap_analysis: str | None = None,
    rag_context: list[str] | None = None,
    temperature: float = 0.2,
    code_summary: CodeSummary | None = None,
    diagram_data: DiagramData | None = None,
) -> ThreatsList:
    """Generate or improve threat catalog.

    Args:
        description: System description (may contain structured XML-tagged input)
        architecture_diagram: DEPRECATED - use diagram_data instead
        assumptions: Optional assumptions (legacy list format)
        assets: Identified assets
        flows: Identified flows
        framework: STRIDE or MAESTRO framework
        provider: LLM provider
        existing_threats: Optional existing threats for improvement iteration
        gap_analysis: Optional gap analysis feedback
        rag_context: Optional similar approved threats from vector store
        temperature: Sampling temperature
        code_summary: Optional condensed code context for threat identification
        diagram_data: Optional diagram data (PNG/JPG/Mermaid)

    Returns:
        ThreatsList with generated threats
    """
    # Parse structured input if present
    component_desc, structured_assumptions, plain_description = parse_structured_input(
        description, framework
    )

    # Select prompt based on framework and iteration
    if existing_threats and gap_analysis:
        # Improvement iteration
        if framework == Framework.MAESTRO:
            system_prompt = maestro_improve_prompt()
        else:
            system_prompt = stride_threats_improve_prompt()
    # Initial iteration
    elif framework == Framework.MAESTRO:
        system_prompt = maestro_threats_prompt()
    else:
        system_prompt = stride_threats_prompt()

    # Build prompt
    prompt_parts = []

    # Handle diagrams: Mermaid goes in prompt, PNG/JPG goes via vision API
    if diagram_data and diagram_data.format == DiagramFormat.MERMAID:
        prompt_parts.append(build_xml_tag("architecture_diagram", diagram_data.mermaid_source))
    elif architecture_diagram:  # Legacy support
        prompt_parts.append(build_xml_tag("architecture_diagram", architecture_diagram))

    # Add component description if structured input was parsed
    if component_desc:
        component_text = format_structured_component_for_prompt(component_desc)
        prompt_parts.append(build_xml_tag("component_description", component_text))

    prompt_parts.append(build_xml_tag("description", plain_description))

    # Build assumptions section (prefer structured over legacy list)
    assumptions_text = build_assumptions_section(assumptions, structured_assumptions)
    if assumptions_text:
        prompt_parts.append(build_xml_tag("assumptions", assumptions_text))

    # Add assets
    assets_text = "## Assets\n"
    for asset in assets.assets:
        assets_text += f"- **{asset.name}** ({asset.type}): {asset.description}\n"
    prompt_parts.append(build_xml_tag("identified_assets_and_entities", assets_text))

    # Add flows
    flows_text = "## Data Flows\n"
    for flow in flows.data_flows:
        flows_text += f"- {flow.source_entity} → {flow.target_entity}: {flow.flow_description}\n"
    flows_text += "\n## Trust Boundaries\n"
    for boundary in flows.trust_boundaries:
        flows_text += f"- {boundary.source_entity} ↔ {boundary.target_entity}: {boundary.purpose}\n"
    prompt_parts.append(build_xml_tag("data_flow", flows_text))

    # Add existing threats if improvement iteration
    if existing_threats:
        threats_text = "## Existing Threats\n"
        for threat in existing_threats.threats:
            threats_text += f"### {threat.name}\n"
            threats_text += f"- **Category**: {threat.stride_category}\n"
            threats_text += f"- **Target**: {threat.target}\n"
            threats_text += f"- **Description**: {threat.description}\n"
            threats_text += f"- **Impact**: {threat.impact}\n"
            threats_text += f"- **Likelihood**: {threat.likelihood}\n"
            threats_text += f"- **Mitigations**: {', '.join(threat.mitigations)}\n\n"
        prompt_parts.append(build_xml_tag("threats", threats_text))

    # Add gap analysis if present
    if gap_analysis:
        prompt_parts.append(build_xml_tag("gap", gap_analysis))

    # Add RAG context if present
    if rag_context:
        rag_text = "## Similar Approved Threats (for reference)\n"
        for idx, threat_text in enumerate(rag_context, 1):
            rag_text += f"### Similar Threat {idx}\n{threat_text}\n\n"
        prompt_parts.append(build_xml_tag("similar_threats", rag_text))

    # Add code summary if available
    if code_summary:
        code_summary_text = format_code_summary(code_summary)
        prompt_parts.append(build_xml_tag("code_summary", code_summary_text))

    user_prompt = "".join(prompt_parts)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    # Build images list for vision API (PNG/JPG only)
    images = None
    if diagram_data and diagram_data.format in (DiagramFormat.PNG, DiagramFormat.JPEG):
        # Add placeholder tag to satisfy prompt instruction enumeration
        # (actual image arrives via vision API content block)
        prompt_parts.insert(
            0,
            build_xml_tag(
                "architecture_diagram", "[Architecture diagram provided as vision image]"
            ),
        )
        user_prompt = "".join(prompt_parts)
        full_prompt = f"{system_prompt}\n\n{user_prompt}"

        images = [
            ImageContent(
                data=diagram_data.base64_data,
                media_type=diagram_data.media_type,
                source=diagram_data.source_path,
            )
        ]

    # Generate structured output
    response = await provider.generate_structured(
        prompt=full_prompt,
        response_model=ThreatsList,
        temperature=temperature,
        images=images,
    )

    return response


async def gap_analysis(
    description: str,
    architecture_diagram: str | None,
    assumptions: list[str] | None,
    assets: AssetsList,
    flows: FlowsList,
    threats: ThreatsList,
    framework: Framework,
    provider: LLMProvider,
    previous_gaps: list[str] | None = None,
    temperature: float = 0.2,
    code_summary: CodeSummary | None = None,
    diagram_data: DiagramData | None = None,
) -> GapAnalysis:
    """Analyze gaps in threat coverage.

    Args:
        description: System description (may contain structured XML-tagged input)
        architecture_diagram: DEPRECATED - use diagram_data instead
        assumptions: Optional assumptions (legacy list format)
        assets: Identified assets
        flows: Identified flows
        threats: Generated threats
        framework: STRIDE or MAESTRO framework
        provider: LLM provider
        previous_gaps: Optional list of previously identified gaps
        temperature: Sampling temperature
        code_summary: Optional condensed code context for gap analysis
        diagram_data: Optional diagram data (PNG/JPG/Mermaid)

    Returns:
        GapAnalysis with stop decision and gap description
    """
    # Parse structured input if present
    component_desc, structured_assumptions, plain_description = parse_structured_input(
        description, framework
    )

    # Select prompt based on framework
    system_prompt = maestro_gap_prompt() if framework == Framework.MAESTRO else stride_gap_prompt()

    # Build prompt
    prompt_parts = []

    # Handle diagrams: Mermaid goes in prompt, PNG/JPG goes via vision API
    if diagram_data and diagram_data.format == DiagramFormat.MERMAID:
        prompt_parts.append(build_xml_tag("architecture_diagram", diagram_data.mermaid_source))
    elif architecture_diagram:  # Legacy support
        prompt_parts.append(build_xml_tag("architecture_diagram", architecture_diagram))

    # Add component description if structured input was parsed
    if component_desc:
        component_text = format_structured_component_for_prompt(component_desc)
        prompt_parts.append(build_xml_tag("component_description", component_text))

    prompt_parts.append(build_xml_tag("description", plain_description))

    # Build assumptions section (prefer structured over legacy list)
    assumptions_text = build_assumptions_section(assumptions, structured_assumptions)
    if assumptions_text:
        prompt_parts.append(build_xml_tag("assumptions", assumptions_text))

    # Add assets
    assets_text = "## Assets\n"
    for asset in assets.assets:
        assets_text += f"- **{asset.name}** ({asset.type}): {asset.description}\n"
    prompt_parts.append(build_xml_tag("identified_assets_and_entities", assets_text))

    # Add flows
    flows_text = "## Data Flows\n"
    for flow in flows.data_flows:
        flows_text += f"- {flow.source_entity} → {flow.target_entity}: {flow.flow_description}\n"
    flows_text += "\n## Trust Boundaries\n"
    for boundary in flows.trust_boundaries:
        flows_text += f"- {boundary.source_entity} ↔ {boundary.target_entity}: {boundary.purpose}\n"
    prompt_parts.append(build_xml_tag("data_flow", flows_text))

    # Add threats
    threats_text = "## Generated Threats\n"
    for threat in threats.threats:
        threats_text += f"### {threat.name}\n"
        threats_text += f"- **Category**: {threat.stride_category}\n"
        threats_text += f"- **Target**: {threat.target}\n"
        threats_text += f"- **Description**: {threat.description}\n"
        threats_text += f"- **Impact**: {threat.impact}\n"
        threats_text += f"- **Likelihood**: {threat.likelihood}\n\n"
    prompt_parts.append(build_xml_tag("threats", threats_text))

    # Add previous gaps if present
    if previous_gaps:
        previous_gaps_text = "\n".join(f"- {gap}" for gap in previous_gaps)
        prompt_parts.append(build_xml_tag("previous_gap", previous_gaps_text))

    # Add code summary if available
    if code_summary:
        code_summary_text = format_code_summary(code_summary)
        prompt_parts.append(build_xml_tag("code_summary", code_summary_text))

    user_prompt = "".join(prompt_parts)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    # Build images list for vision API (PNG/JPG only)
    images = None
    if diagram_data and diagram_data.format in (DiagramFormat.PNG, DiagramFormat.JPEG):
        # Add placeholder tag to satisfy prompt instruction enumeration
        # (actual image arrives via vision API content block)
        prompt_parts.insert(
            0,
            build_xml_tag(
                "architecture_diagram", "[Architecture diagram provided as vision image]"
            ),
        )
        user_prompt = "".join(prompt_parts)
        full_prompt = f"{system_prompt}\n\n{user_prompt}"

        images = [
            ImageContent(
                data=diagram_data.base64_data,
                media_type=diagram_data.media_type,
                source=diagram_data.source_path,
            )
        ]

    # Generate structured output
    response = await provider.generate_structured(
        prompt=full_prompt,
        response_model=GapAnalysis,
        temperature=temperature,
        images=images,
    )

    return response
