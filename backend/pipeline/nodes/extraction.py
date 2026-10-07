"""Asset and flow extraction nodes.

Contains extract_assets() for identifying system assets and entities, and
extract_flows() for mapping data flows, trust boundaries, and threat sources.
"""

from backend.models.enums import Framework
from backend.models.extended import CodeSummary, DiagramData
from backend.models.state import AssetsList, FlowsList
from backend.pipeline.nodes.helpers import (
    build_assumptions_section,
    build_diagram_parts,
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
    diagrams: list[DiagramData] | None = None,
    with_images: bool = True,
) -> AssetsList:
    """Extract assets and entities from system description.

    Args:
        summary: Generated system summary
        description: Original system description (may contain structured XML-tagged input)
        architecture_diagram: DEPRECATED - use diagrams instead
        assumptions: Optional assumptions (legacy list format)
        framework: STRIDE or MAESTRO framework
        provider: LLM provider
        temperature: Sampling temperature
        code_summary: Optional condensed code context for asset identification
        diagrams: Optional diagrams (PNG/JPG/Mermaid), 1 or more
        with_images: Whether to send PNG/JPEG diagram bytes via the vision
            API (False for the Ollama degrade path)

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
    diagram_text, images = build_diagram_parts(diagrams, with_images=with_images)
    if diagram_text:
        prompt_parts.append(diagram_text)
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

    # Generate structured output
    response = await provider.generate_structured(
        prompt=full_prompt,
        response_model=AssetsList,
        temperature=temperature,
        max_tokens=8192,
        images=images or None,
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
    diagrams: list[DiagramData] | None = None,
    with_images: bool = True,
) -> FlowsList:
    """Extract data flows, trust boundaries, and threat sources.

    Args:
        summary: Generated system summary
        description: Original system description (may contain structured XML-tagged input)
        architecture_diagram: DEPRECATED - use diagrams instead
        assumptions: Optional assumptions (legacy list format)
        assets: Previously extracted assets
        provider: LLM provider
        temperature: Sampling temperature
        code_summary: Optional condensed code context for flow identification
        diagrams: Optional diagrams (PNG/JPG/Mermaid), 1 or more
        with_images: Whether to send PNG/JPEG diagram bytes via the vision
            API (False for the Ollama degrade path)

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
    diagram_text, images = build_diagram_parts(diagrams, with_images=with_images)
    if diagram_text:
        prompt_parts.append(diagram_text)
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

    # Generate structured output
    response = await provider.generate_structured(
        prompt=full_prompt,
        response_model=FlowsList,
        temperature=temperature,
        max_tokens=32768,
        images=images or None,
    )

    return response
