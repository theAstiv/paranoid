"""Helper functions for prompt building and formatting.

Shared utilities for XML tag construction, assumption formatting, code context
formatting, and structured input parsing used across all pipeline nodes.
"""

from backend.models.enums import Framework
from backend.models.extended import (
    CodeContext,
    CodeSummary,
    MaestroAssumptions,
    MaestroComponentDescription,
    StrideAssumptions,
    StrideComponentDescription,
)
from backend.pipeline import input_parser


def build_xml_tag(tag: str, content: str) -> str:
    """Build an XML tag with content."""
    if not content or content.strip() == "":
        return ""
    return f"<{tag}>\n{content.strip()}\n</{tag}>\n\n"


def format_assumptions(assumptions: list[str] | None) -> str:
    """Format assumptions list as a string."""
    if not assumptions:
        return ""
    return "\n".join(f"- {assumption}" for assumption in assumptions)


def format_code_context(code_context: CodeContext) -> str:
    """Format CodeContext as XML-tagged text for inclusion in prompts.

    Extracts file paths and content from CodeContext and formats as a
    structured XML block for the full code context (used in summarize()).

    Args:
        code_context: Code context from MCP extraction

    Returns:
        Formatted XML string with repository and file contents
    """
    code_text = f"Repository: {code_context.repository}\n\n"
    for file in code_context.files:
        # Escape any XML special characters in content
        safe_content = file.content.replace("<", "&lt;").replace(">", "&gt;")
        code_text += f"## {file.path}\n{safe_content}\n\n"
    return code_text.strip()


def format_code_summary(code_summary: CodeSummary) -> str:
    """Format CodeSummary as XML-tagged text for downstream nodes.

    Formats the condensed code summary for asset extraction, flow analysis,
    threat generation, and gap analysis steps.

    Args:
        code_summary: Condensed security-focused code summary

    Returns:
        Formatted XML string with structured code summary
    """
    sections = []

    if code_summary.tech_stack:
        sections.append(
            "**Technology Stack:**\n" + "\n".join(f"- {item}" for item in code_summary.tech_stack)
        )

    if code_summary.entry_points:
        sections.append(
            "**Entry Points:**\n" + "\n".join(f"- {item}" for item in code_summary.entry_points)
        )

    if code_summary.auth_patterns:
        sections.append(
            "**Authentication & Authorization:**\n"
            + "\n".join(f"- {item}" for item in code_summary.auth_patterns)
        )

    if code_summary.data_stores:
        sections.append(
            "**Data Stores:**\n" + "\n".join(f"- {item}" for item in code_summary.data_stores)
        )

    if code_summary.external_dependencies:
        sections.append(
            "**External Dependencies:**\n"
            + "\n".join(f"- {item}" for item in code_summary.external_dependencies)
        )

    if code_summary.security_observations:
        sections.append(
            "**Security Observations:**\n"
            + "\n".join(f"- {item}" for item in code_summary.security_observations)
        )

    if code_summary.raw_summary:
        sections.append(f"**Summary:**\n{code_summary.raw_summary}")

    return "\n\n".join(sections)


def parse_structured_input(
    description: str,
    framework: Framework,
) -> tuple[
    StrideComponentDescription | MaestroComponentDescription | None,
    StrideAssumptions | MaestroAssumptions | None,
    str,
]:
    """Parse structured XML-tagged input if present.

    Args:
        description: Input text that may contain XML-tagged structured data
        framework: STRIDE or MAESTRO framework

    Returns:
        Tuple of (component_description, assumptions, plain_description)
        - component_description: Parsed structured component description if found
        - assumptions: Parsed structured assumptions if found
        - plain_description: Original description (for backward compatibility)
    """
    input_format = input_parser.detect_input_format(description)

    if input_format == "stride_structured":
        component_desc = input_parser.parse_stride_component_description(description)
        assumptions_struct = input_parser.parse_stride_assumptions(description)
        return component_desc, assumptions_struct, description
    if input_format == "maestro_structured":
        component_desc = input_parser.parse_maestro_component_description(description)
        assumptions_struct = input_parser.parse_maestro_assumptions(description)
        return component_desc, assumptions_struct, description
    # Plain text input - no structured parsing
    return None, None, description


def format_structured_component_for_prompt(
    component_desc: StrideComponentDescription | MaestroComponentDescription | None,
) -> str:
    """Format structured component description for prompt inclusion.

    Args:
        component_desc: Parsed component description

    Returns:
        Formatted string for prompt, or empty string if None
    """
    if component_desc is None:
        return ""
    return input_parser.format_structured_description_for_prompt(component_desc)


def format_structured_assumptions_for_prompt(
    assumptions_struct: StrideAssumptions | MaestroAssumptions | None,
) -> str:
    """Format structured assumptions for prompt inclusion.

    Args:
        assumptions_struct: Parsed structured assumptions

    Returns:
        Formatted string for prompt, or empty string if None
    """
    if assumptions_struct is None:
        return ""
    return input_parser.format_structured_assumptions_for_prompt(assumptions_struct)


def build_assumptions_section(
    assumptions: list[str] | None,
    structured_assumptions: StrideAssumptions | MaestroAssumptions | None,
) -> str:
    """Build assumptions section for prompt.

    Args:
        assumptions: Legacy list of assumption strings
        structured_assumptions: Structured assumptions from XML template

    Returns:
        Formatted assumptions text for prompt inclusion
    """
    # Prefer structured assumptions if available
    if structured_assumptions:
        return format_structured_assumptions_for_prompt(structured_assumptions)
    if assumptions:
        return format_assumptions(assumptions)
    return ""
