"""Asset and flow extraction nodes.

Contains extract_assets() for identifying system assets and entities, and
extract_flows() for mapping data flows, trust boundaries, and threat sources.
"""

from backend.models.enums import DiagramFormat, Framework
from backend.models.extended import CodeSummary, DiagramData, ImageContent
from backend.models.state import AssetsList, FlowsList
from backend.pipeline.nodes.helpers import (
    build_assumptions_section,
    build_xml_tag,
    format_code_summary,
    format_structured_component_for_prompt,
    parse_structured_input,
)
from backend.pipeline.prompts import maestro_asset_prompt, stride_asset_prompt, stride_flow_prompt
from backend.providers.base import LLMProvider


async def extract_assets(
    summary: str,
    description: str,
    architecture_diagram: str | None,
    assumptions: list[str] | None,
    framework: Framework,
    provider: LLMProvider,
    temperature: float = 0.2,
    code_summary: CodeSummary | None = None,
    diagram_data: DiagramData | None = None,
) -> AssetsList:
    """Extract assets and entities from system description.

    Args:
        summary: Generated system summary
        description: Original system description (may contain structured XML-tagged input)
        architecture_diagram: DEPRECATED - use diagram_data instead
        assumptions: Optional assumptions (legacy list format)
        framework: STRIDE or MAESTRO framework
        provider: LLM provider
        temperature: Sampling temperature
        code_summary: Optional condensed code context for asset identification
        diagram_data: Optional diagram data (PNG/JPG/Mermaid)

    Returns:
        AssetsList with identified assets and entities
    """
    # Parse structured input if present
    component_desc, structured_assumptions, plain_description = parse_structured_input(
        description, framework
    )

    # Select prompt based on framework
    if framework == Framework.MAESTRO:
        system_prompt = maestro_asset_prompt()
    else:
        system_prompt = stride_asset_prompt()

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
        response_model=AssetsList,
        temperature=temperature,
        max_tokens=2048,
        images=images,
    )

    return response


async def extract_flows(
    summary: str,
    description: str,
    architecture_diagram: str | None,
    assumptions: list[str] | None,
    assets: AssetsList,
    provider: LLMProvider,
    temperature: float = 0.2,
    code_summary: CodeSummary | None = None,
    diagram_data: DiagramData | None = None,
) -> FlowsList:
    """Extract data flows, trust boundaries, and threat sources.

    Args:
        summary: Generated system summary
        description: Original system description (may contain structured XML-tagged input)
        architecture_diagram: DEPRECATED - use diagram_data instead
        assumptions: Optional assumptions (legacy list format)
        assets: Previously extracted assets
        provider: LLM provider
        temperature: Sampling temperature
        code_summary: Optional condensed code context for flow identification
        diagram_data: Optional diagram data (PNG/JPG/Mermaid)

    Returns:
        FlowsList with data flows, trust boundaries, and threat sources
    """
    # Parse structured input if present (use STRIDE framework for flow extraction)
    component_desc, structured_assumptions, plain_description = parse_structured_input(
        description, Framework.STRIDE
    )

    system_prompt = stride_flow_prompt()

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
        response_model=FlowsList,
        temperature=temperature,
        max_tokens=2560,
        images=images,
    )

    return response
