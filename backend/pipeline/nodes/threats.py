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
    shared_context: str | None = None,
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
        shared_context: Pre-built stable context from build_shared_context(). When
            provided, the stable parts (diagram/description/assets/flows/code_summary)
            are skipped in the prompt and sent as a cacheable prefix instead.

    Returns:
        ThreatsList with generated threats
    """
    # Parse structured input if present (needed regardless — may affect system prompt)
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

    # Build prompt parts.
    # When shared_context is provided, stable parts (diagram, description, assets,
    # flows, code_summary) are omitted here — they arrive via the cached prefix block.
    # Only iteration-specific content is built in the dynamic prompt.
    prompt_parts = []

    if not shared_context:
        # Stable parts — only needed when not using prompt caching
        if diagram_data and diagram_data.format == DiagramFormat.MERMAID:
            prompt_parts.append(build_xml_tag("architecture_diagram", diagram_data.mermaid_source))
        elif architecture_diagram:
            prompt_parts.append(build_xml_tag("architecture_diagram", architecture_diagram))

        if component_desc:
            component_text = format_structured_component_for_prompt(component_desc)
            prompt_parts.append(build_xml_tag("component_description", component_text))

        prompt_parts.append(build_xml_tag("description", plain_description))

        assumptions_text = build_assumptions_section(assumptions, structured_assumptions)
        if assumptions_text:
            prompt_parts.append(build_xml_tag("assumptions", assumptions_text))

        assets_text = "## Assets\n"
        for asset in assets.assets:
            assets_text += f"- **{asset.name}** ({asset.type}): {asset.description}\n"
        prompt_parts.append(build_xml_tag("identified_assets_and_entities", assets_text))

        flows_text = "## Data Flows\n"
        for flow in flows.data_flows:
            flows_text += (
                f"- {flow.source_entity} → {flow.target_entity}: {flow.flow_description}\n"
            )
        flows_text += "\n## Trust Boundaries\n"
        for boundary in flows.trust_boundaries:
            flows_text += (
                f"- {boundary.source_entity} ↔ {boundary.target_entity}: {boundary.purpose}\n"
            )
        prompt_parts.append(build_xml_tag("data_flow", flows_text))

        if code_summary:
            prompt_parts.append(build_xml_tag("code_summary", format_code_summary(code_summary)))

    # Iteration-specific parts (always built regardless of shared_context)

    # Existing threats in compact one-liner format (~30 tokens vs ~200 per threat)
    if existing_threats:
        threats_text = "## Existing Threats\n"
        for threat in existing_threats.threats:
            gist = (
                threat.description[:100] + "..."
                if len(threat.description) > 100
                else threat.description
            )
            threats_text += (
                f"- {threat.name} [{threat.stride_category.value} → {threat.target}]: {gist}\n"
            )
        prompt_parts.append(build_xml_tag("threats", threats_text))

    if gap_analysis:
        prompt_parts.append(build_xml_tag("gap", gap_analysis))

    if rag_context:
        rag_text = "## Similar Approved Threats (for reference)\n"
        for idx, threat_text in enumerate(rag_context, 1):
            rag_text += f"### Similar Threat {idx}\n{threat_text}\n\n"
        prompt_parts.append(build_xml_tag("similar_threats", rag_text))

    user_prompt = "".join(prompt_parts)
    full_prompt = f"{system_prompt}\n\n{user_prompt}" if user_prompt else system_prompt

    # Build images list for vision API (PNG/JPG only).
    # When shared_context is provided, the placeholder tag is already included there;
    # only add it to the dynamic prompt when building without shared_context.
    images = None
    if diagram_data and diagram_data.format in (DiagramFormat.PNG, DiagramFormat.JPEG):
        if not shared_context:
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
        max_tokens=4096,
        images=images,
        shared_context=shared_context,
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
    shared_context: str | None = None,
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
        shared_context: Pre-built stable context from build_shared_context(). When
            provided, the stable parts (diagram/description/assets/flows/code_summary)
            are skipped in the prompt and sent as a cacheable prefix instead.

    Returns:
        GapAnalysis with stop decision and gap description
    """
    # Parse structured input if present
    component_desc, structured_assumptions, plain_description = parse_structured_input(
        description, framework
    )

    # Select prompt based on framework
    system_prompt = maestro_gap_prompt() if framework == Framework.MAESTRO else stride_gap_prompt()

    # Build prompt parts.
    # When shared_context is provided, stable parts (diagram, description, assumptions,
    # assets, flows, code_summary) are omitted here — they arrive via the cached prefix.
    prompt_parts = []

    if not shared_context:
        # Stable parts — only needed when not using prompt caching
        if diagram_data and diagram_data.format == DiagramFormat.MERMAID:
            prompt_parts.append(build_xml_tag("architecture_diagram", diagram_data.mermaid_source))
        elif architecture_diagram:  # Legacy support
            prompt_parts.append(build_xml_tag("architecture_diagram", architecture_diagram))

        if component_desc:
            component_text = format_structured_component_for_prompt(component_desc)
            prompt_parts.append(build_xml_tag("component_description", component_text))

        prompt_parts.append(build_xml_tag("description", plain_description))

        assumptions_text = build_assumptions_section(assumptions, structured_assumptions)
        if assumptions_text:
            prompt_parts.append(build_xml_tag("assumptions", assumptions_text))

        assets_text = "## Assets\n"
        for asset in assets.assets:
            assets_text += f"- **{asset.name}** ({asset.type}): {asset.description}\n"
        prompt_parts.append(build_xml_tag("identified_assets_and_entities", assets_text))

        flows_text = "## Data Flows\n"
        for flow in flows.data_flows:
            flows_text += (
                f"- {flow.source_entity} → {flow.target_entity}: {flow.flow_description}\n"
            )
        flows_text += "\n## Trust Boundaries\n"
        for boundary in flows.trust_boundaries:
            flows_text += (
                f"- {boundary.source_entity} ↔ {boundary.target_entity}: {boundary.purpose}\n"
            )
        prompt_parts.append(build_xml_tag("data_flow", flows_text))

        if code_summary:
            prompt_parts.append(build_xml_tag("code_summary", format_code_summary(code_summary)))

    # Iteration-specific parts (always built regardless of shared_context)

    # Add threats in compact one-liner format (gap analysis only needs coverage
    # awareness, not the full mitigations list — saves ~120 tokens per threat).
    threats_text = "## Generated Threats\n"
    for threat in threats.threats:
        gist = (
            threat.description[:100] + "..."
            if len(threat.description) > 100
            else threat.description
        )
        threats_text += (
            f"- {threat.name} [{threat.stride_category.value} → {threat.target}]: {gist}\n"
        )
    prompt_parts.append(build_xml_tag("threats", threats_text))

    if previous_gaps:
        previous_gaps_text = "\n".join(f"- {gap}" for gap in previous_gaps)
        prompt_parts.append(build_xml_tag("previous_gap", previous_gaps_text))

    user_prompt = "".join(prompt_parts)
    full_prompt = f"{system_prompt}\n\n{user_prompt}" if user_prompt else system_prompt

    # Build images list for vision API (PNG/JPG only).
    # When shared_context is provided, the placeholder tag is already included there;
    # only add it to the dynamic prompt when building without shared_context.
    images = None
    if diagram_data and diagram_data.format in (DiagramFormat.PNG, DiagramFormat.JPEG):
        if not shared_context:
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
        max_tokens=1536,
        images=images,
        shared_context=shared_context,
    )

    return response
