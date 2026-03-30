"""Input parser for XML-tagged component descriptions and assumptions.

This module parses structured input following the Input-template.md format,
extracting component descriptions and assumptions for STRIDE and MAESTRO frameworks.
"""

import logging
import re

from pydantic import ValidationError

from backend.models.extended import (
    MaestroAssumptions,
    MaestroComponentDescription,
    StrideAssumptions,
    StrideComponentDescription,
)


logger = logging.getLogger(__name__)


def _extract_xml_section(text: str, tag: str) -> str | None:
    """Extract content from XML tags.

    Args:
        text: Input text containing XML tags
        tag: Tag name to extract (without angle brackets)

    Returns:
        Content between opening and closing tags, or None if not found
    """
    pattern = rf"<{tag}>(.*?)</{tag}>"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _extract_bulleted_list(text: str, header: str) -> list[str]:
    """Extract bulleted list items under a header.

    Args:
        text: Text containing markdown-style lists
        header: Header text to search for (e.g., "Security Controls Already in Place:")

    Returns:
        List of items (without bullet markers)
    """
    items = []
    # Find the header
    pattern = rf"\*\*{re.escape(header)}\*\*"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return items

    # Extract text after header until next header or end
    remaining_text = text[match.end():]
    lines = remaining_text.split("\n")

    for raw_line in lines:
        line = raw_line.strip()
        # Stop at next header
        if line.startswith("**") and line.endswith("**"):
            break
        # Extract bulleted items
        if line.startswith("- ") or line.startswith("* "):
            items.append(line[2:].strip())

    return items


def _extract_key_value(text: str, key: str) -> str:
    """Extract value for a key-value pair.

    Args:
        text: Text containing key-value pairs
        key: Key to search for (e.g., "Name:", "Purpose:")

    Returns:
        Value associated with the key
    """
    pattern = rf"\*\*{re.escape(key)}\*\*\s*(.+?)(?=\n\*\*|\n\n|$)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _extract_subsections(text: str, header: str) -> dict[str, list[str]]:
    """Extract nested subsections under a header.

    Args:
        text: Text containing nested subsections
        header: Parent header to search for

    Returns:
        Dictionary mapping subsection names to their bulleted items
    """
    result = {}
    pattern = rf"\*\*{re.escape(header)}\*\*"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return result

    remaining_text = text[match.end():]
    lines = remaining_text.split("\n")

    current_subsection = None
    for line in lines:
        line_stripped = line.strip()
        # Stop at next top-level header
        if line_stripped.startswith("**") and line_stripped.endswith("**") and line.startswith("**"):
            break

        # Check for subsection headers (indented or prefixed with dash)
        if line_stripped.startswith("- **") and ":**" in line_stripped:
            # Extract subsection name
            subsection_match = re.search(r"- \*\*(.+?):\*\*", line_stripped)
            if subsection_match:
                current_subsection = subsection_match.group(1)
                result[current_subsection] = []
        elif current_subsection and line_stripped.startswith("- "):
            # Add item to current subsection (remove nested bullet markers)
            item = re.sub(r"^-\s+", "", line_stripped)
            result[current_subsection].append(item)

    return result


def parse_stride_component_description(text: str) -> StrideComponentDescription | None:
    """Parse STRIDE component description from XML-tagged template.

    Args:
        text: Input text containing <component_description> tags

    Returns:
        StrideComponentDescription model or None if parsing fails
    """
    content = _extract_xml_section(text, "component_description")
    if not content:
        return None

    try:
        name = _extract_key_value(content, "Name:")
        purpose = _extract_key_value(content, "Purpose:")

        # Extract technology stack
        technology_stack = _extract_subsections(content, "Technology Stack:")

        # Extract interfaces
        interfaces = _extract_subsections(content, "Interfaces and Protocols:")

        # Extract data handled
        data_handled = _extract_subsections(content, "Data Handled:")

        # Extract trust level
        _trust_level_section = _extract_xml_section(content, "trust_level") or content
        trust_level = {}
        # Extract inline key-values for trust level
        internal_external = _extract_key_value(content, "Internal/External:")
        if internal_external:
            trust_level["Internal/External"] = internal_external
        auth_authz = _extract_key_value(content, "Authentication / Authorization Used:")
        if auth_authz:
            trust_level["Authentication / Authorization Used"] = auth_authz

        # Extract dependencies
        dependencies = _extract_bulleted_list(content, "Dependencies:")

        return StrideComponentDescription(
            name=name,
            purpose=purpose,
            technology_stack=technology_stack,
            interfaces=interfaces,
            data_handled=data_handled,
            trust_level=trust_level,
            dependencies=dependencies,
        )
    except ValidationError as e:
        logger.warning("STRIDE component description failed validation: %s", e)
        return None
    except (AttributeError, TypeError, KeyError) as e:
        logger.warning("Failed to parse STRIDE component description: %s", e)
        return None


def parse_maestro_component_description(text: str) -> MaestroComponentDescription | None:
    """Parse MAESTRO component description from XML-tagged template.

    Args:
        text: Input text containing <maestro_component_description> tags

    Returns:
        MaestroComponentDescription model or None if parsing fails
    """
    content = _extract_xml_section(text, "maestro_component_description")
    if not content:
        return None

    try:
        name = _extract_key_value(content, "Name:")

        # Extract mission alignment
        mission_alignment = {}
        for key in ["Operational Mission:", "Autonomy Level:", "Decision Authority:"]:
            value = _extract_key_value(content, key)
            if value:
                mission_alignment[key.rstrip(":")] = value

        # Extract agent profile
        agent_profile = _extract_subsections(content, "Agent / Model Profile:")

        # Extract technology stack
        tech_stack = _extract_subsections(content, "Technology Stack:")

        # Extract assets
        assets = _extract_subsections(content, "Assets:")

        # Extract actors
        actors = _extract_subsections(content, "Actors:")

        # Extract interfaces
        interfaces = _extract_subsections(content, "Interfaces and Protocols:")

        # Extract trust boundaries
        trust_boundaries = {}
        trust_level_val = _extract_key_value(content, "Trust Level:")
        if trust_level_val:
            trust_boundaries["Trust Level"] = trust_level_val
        agent_trust = _extract_key_value(content, "Agent Trust Chain:")
        if agent_trust:
            trust_boundaries["Agent Trust Chain"] = agent_trust
        human_override = _extract_key_value(content, "Human Override Mechanism:")
        if human_override:
            trust_boundaries["Human Override Mechanism"] = human_override
        auth_authz = _extract_key_value(content, "Authentication / Authorization:")
        if auth_authz:
            trust_boundaries["Authentication / Authorization"] = auth_authz

        # Extract dependencies
        dependencies = _extract_bulleted_list(content, "Dependencies:")

        return MaestroComponentDescription(
            name=name,
            mission_alignment=mission_alignment,
            agent_profile=agent_profile,
            technology_stack=tech_stack,
            assets=assets,
            actors=actors,
            interfaces=interfaces,
            trust_boundaries=trust_boundaries,
            dependencies=dependencies,
        )
    except ValidationError as e:
        logger.warning("MAESTRO component description failed validation: %s", e)
        return None
    except (AttributeError, TypeError, KeyError) as e:
        logger.warning("Failed to parse MAESTRO component description: %s", e)
        return None


def parse_stride_assumptions(text: str) -> StrideAssumptions | None:
    """Parse STRIDE assumptions from XML-tagged template.

    Args:
        text: Input text containing <assumptions> tags

    Returns:
        StrideAssumptions model or None if parsing fails
    """
    content = _extract_xml_section(text, "assumptions")
    if not content:
        return None

    try:
        security_controls = _extract_bulleted_list(content, "Security Controls Already in Place:")
        in_scope = _extract_bulleted_list(content, "Areas Considered In-Scope:")
        out_of_scope = _extract_bulleted_list(content, "Areas Considered Out-of-Scope:")
        constraints = _extract_bulleted_list(content, "Known Constraints or Limitations:")
        operational_considerations = _extract_bulleted_list(
            content, "Development or Operational Considerations:"
        )
        focus_areas = _extract_bulleted_list(content, "Threat Modeling Focus Areas:")

        return StrideAssumptions(
            security_controls=security_controls,
            in_scope=in_scope,
            out_of_scope=out_of_scope,
            constraints=constraints,
            operational_considerations=operational_considerations,
            focus_areas=focus_areas,
        )
    except ValidationError as e:
        logger.warning("STRIDE assumptions failed validation: %s", e)
        return None
    except (AttributeError, TypeError, KeyError) as e:
        logger.warning("Failed to parse STRIDE assumptions: %s", e)
        return None


def parse_maestro_assumptions(text: str) -> MaestroAssumptions | None:
    """Parse MAESTRO assumptions from XML-tagged template.

    Args:
        text: Input text containing <maestro_assumptions> tags

    Returns:
        MaestroAssumptions model or None if parsing fails
    """
    content = _extract_xml_section(text, "maestro_assumptions")
    if not content:
        return None

    try:
        mission_constraints = _extract_bulleted_list(content, "Mission Constraints:")
        security_controls = _extract_bulleted_list(content, "Security Controls Already in Place:")
        ai_specific_controls = _extract_bulleted_list(content, "AI-Specific Controls in Place:")
        in_scope = _extract_bulleted_list(content, "Areas Considered In-Scope:")
        out_of_scope = _extract_bulleted_list(content, "Areas Considered Out-of-Scope:")
        constraints = _extract_bulleted_list(content, "Known Constraints or Limitations:")
        agentic_considerations = _extract_bulleted_list(
            content, "Agentic / AI-Specific Considerations:"
        )
        operational_considerations = _extract_bulleted_list(
            content, "Development or Operational Considerations:"
        )
        focus_areas = _extract_bulleted_list(content, "Threat Modeling Focus Areas:")

        return MaestroAssumptions(
            mission_constraints=mission_constraints,
            security_controls=security_controls,
            ai_specific_controls=ai_specific_controls,
            in_scope=in_scope,
            out_of_scope=out_of_scope,
            constraints=constraints,
            agentic_considerations=agentic_considerations,
            operational_considerations=operational_considerations,
            focus_areas=focus_areas,
        )
    except ValidationError as e:
        logger.warning("MAESTRO assumptions failed validation: %s", e)
        return None
    except (AttributeError, TypeError, KeyError) as e:
        logger.warning("Failed to parse MAESTRO assumptions: %s", e)
        return None


def detect_input_format(text: str) -> str:
    """Detect if input uses structured XML template format.

    Args:
        text: Input text to analyze

    Returns:
        "stride_structured", "maestro_structured", or "plain"
    """
    if "<component_description>" in text or "</component_description>" in text:
        return "stride_structured"
    if "<maestro_component_description>" in text or "</maestro_component_description>" in text:
        return "maestro_structured"
    return "plain"


def format_structured_description_for_prompt(
    component_desc: StrideComponentDescription | MaestroComponentDescription,
) -> str:
    """Format structured component description as human-readable text for prompts.

    Args:
        component_desc: Parsed component description

    Returns:
        Formatted string suitable for prompt inclusion
    """
    lines = [f"**Component Name:** {component_desc.name}"]

    if isinstance(component_desc, StrideComponentDescription):
        lines.append(f"**Purpose:** {component_desc.purpose}")
        lines.append("")
        lines.append("**Technology Stack:**")
        for key, values in component_desc.technology_stack.items():
            lines.append(f"  - {key}: {', '.join(values)}")
    elif isinstance(component_desc, MaestroComponentDescription):
        lines.append("")
        lines.append("**Mission Alignment:**")
        for key, value in component_desc.mission_alignment.items():
            lines.append(f"  - {key}: {value}")
        lines.append("")
        lines.append("**Agent/Model Profile:**")
        for key, values in component_desc.agent_profile.items():
            if isinstance(values, list):
                lines.append(f"  - {key}: {', '.join(values)}")
            else:
                lines.append(f"  - {key}: {values}")

    lines.append("")
    lines.append("**Interfaces:**")
    for key, values in component_desc.interfaces.items():
        lines.append(f"  - {key}:")
        for item in values:
            lines.append(f"    - {item}")

    lines.append("")
    lines.append("**Dependencies:**")
    for dep in component_desc.dependencies:
        lines.append(f"  - {dep}")

    return "\n".join(lines)


def format_structured_assumptions_for_prompt(
    assumptions: StrideAssumptions | MaestroAssumptions,
) -> str:
    """Format structured assumptions as human-readable text for prompts.

    Args:
        assumptions: Parsed assumptions

    Returns:
        Formatted string suitable for prompt inclusion
    """
    lines = []

    if isinstance(assumptions, StrideAssumptions):
        sections = [
            ("Security Controls Already in Place", assumptions.security_controls),
            ("Areas Considered In-Scope", assumptions.in_scope),
            ("Areas Considered Out-of-Scope", assumptions.out_of_scope),
            ("Known Constraints or Limitations", assumptions.constraints),
            ("Development or Operational Considerations", assumptions.operational_considerations),
            ("Threat Modeling Focus Areas", assumptions.focus_areas),
        ]
    else:  # MaestroAssumptions
        sections = [
            ("Mission Constraints", assumptions.mission_constraints),
            ("Security Controls Already in Place", assumptions.security_controls),
            ("AI-Specific Controls in Place", assumptions.ai_specific_controls),
            ("Areas Considered In-Scope", assumptions.in_scope),
            ("Areas Considered Out-of-Scope", assumptions.out_of_scope),
            ("Known Constraints or Limitations", assumptions.constraints),
            ("Agentic/AI-Specific Considerations", assumptions.agentic_considerations),
            ("Development or Operational Considerations", assumptions.operational_considerations),
            ("Threat Modeling Focus Areas", assumptions.focus_areas),
        ]

    for section_name, items in sections:
        if items:
            lines.append(f"**{section_name}:**")
            for item in items:
                lines.append(f"  - {item}")
            lines.append("")

    return "\n".join(lines)
