"""Pipeline nodes for threat modeling — plain async functions.

Each node is an independent async function that takes structured input and returns
structured output. No classes, no LangChain, no state management — just pure logic.
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from backend.models.enums import Framework
from backend.models.extended import (
    AttackTree,
    CodeContext,
    CodeSummary,
    MaestroAssumptions,
    MaestroComponentDescription,
    StrideAssumptions,
    StrideComponentDescription,
    TestSuite,
)
from backend.models.state import (
    AssetsList,
    ContinueThreatModeling,
    FlowsList,
    SummaryState,
    ThreatsList,
)
from backend.pipeline import input_parser
from backend.pipeline.prompts import (
    attack_tree_prompt,
    code_summary_prompt,
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
from backend.providers.base import LLMProvider, ProviderError

logger = logging.getLogger(__name__)


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


def _format_code_context(code_context: CodeContext) -> str:
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


def _format_code_summary(code_summary: CodeSummary) -> str:
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
        sections.append("**Technology Stack:**\n" + "\n".join(f"- {item}" for item in code_summary.tech_stack))

    if code_summary.entry_points:
        sections.append("**Entry Points:**\n" + "\n".join(f"- {item}" for item in code_summary.entry_points))

    if code_summary.auth_patterns:
        sections.append("**Authentication & Authorization:**\n" + "\n".join(f"- {item}" for item in code_summary.auth_patterns))

    if code_summary.data_stores:
        sections.append("**Data Stores:**\n" + "\n".join(f"- {item}" for item in code_summary.data_stores))

    if code_summary.external_dependencies:
        sections.append("**External Dependencies:**\n" + "\n".join(f"- {item}" for item in code_summary.external_dependencies))

    if code_summary.security_observations:
        sections.append("**Security Observations:**\n" + "\n".join(f"- {item}" for item in code_summary.security_observations))

    if code_summary.raw_summary:
        sections.append(f"**Summary:**\n{code_summary.raw_summary}")

    return "\n\n".join(sections)


def _parse_structured_input(
    description: str,
    framework: Framework,
) -> tuple[
    Optional[StrideComponentDescription | MaestroComponentDescription],
    Optional[StrideAssumptions | MaestroAssumptions],
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
    elif input_format == "maestro_structured":
        component_desc = input_parser.parse_maestro_component_description(description)
        assumptions_struct = input_parser.parse_maestro_assumptions(description)
        return component_desc, assumptions_struct, description
    else:
        # Plain text input - no structured parsing
        return None, None, description


def _format_structured_component_for_prompt(
    component_desc: Optional[StrideComponentDescription | MaestroComponentDescription],
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


def _format_structured_assumptions_for_prompt(
    assumptions_struct: Optional[StrideAssumptions | MaestroAssumptions],
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


def _build_assumptions_section(
    assumptions: Optional[list[str]],
    structured_assumptions: Optional[StrideAssumptions | MaestroAssumptions],
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
        return _format_structured_assumptions_for_prompt(structured_assumptions)
    elif assumptions:
        return _format_assumptions(assumptions)
    else:
        return ""


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
        code_text = _format_code_context(code_context)
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


def _deterministic_code_summary(code_context: CodeContext) -> CodeSummary:
    """Generate code summary from metadata when LLM unavailable.

    Fallback function that extracts CodeSummary from CodeContext metadata
    using pattern matching and heuristics. Used when summarize_code() fails.

    Args:
        code_context: Full code context with file contents

    Returns:
        CodeSummary extracted from file metadata and content patterns
    """
    tech_stack = []
    entry_points = []
    auth_patterns = []
    data_stores = []
    external_dependencies = []
    security_observations = []

    # Extract languages from file extensions
    extensions = set()
    for file in code_context.files:
        ext = Path(file.path).suffix.lower()
        if ext:
            extensions.add(ext)

    # Map extensions to languages/frameworks
    ext_map = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".go": "Go",
        ".java": "Java",
        ".rb": "Ruby",
        ".php": "PHP",
        ".rs": "Rust",
        ".cpp": "C++",
        ".c": "C",
        ".cs": "C#",
    }
    for ext, lang in ext_map.items():
        if ext in extensions:
            tech_stack.append(lang)

    # Scan content for framework imports and security patterns
    for file in code_context.files:
        content = file.content.lower()

        # Detect frameworks
        if "from fastapi" in content or "import fastapi" in content:
            if "FastAPI" not in tech_stack:
                tech_stack.append("FastAPI")
        if "from flask" in content or "import flask" in content:
            if "Flask" not in tech_stack:
                tech_stack.append("Flask")
        if "import express" in content or "require('express')" in content:
            if "Express.js" not in tech_stack:
                tech_stack.append("Express.js")
        if "import torch" in content or "from torch" in content:
            if "PyTorch" not in tech_stack:
                tech_stack.append("PyTorch")
        if "import tensorflow" in content or "from tensorflow" in content:
            if "TensorFlow" not in tech_stack:
                tech_stack.append("TensorFlow")

        # Detect HTTP routes
        route_patterns = [
            r"@app\.(get|post|put|delete|patch)\(['\"]([^'\"]+)",
            r"@router\.(get|post|put|delete|patch)\(['\"]([^'\"]+)",
            r"app\.(get|post|put|delete|patch)\(['\"]([^'\"]+)",
        ]
        for pattern in route_patterns:
            for match in re.finditer(pattern, content):
                method = match.group(1).upper()
                path = match.group(2)
                entry_points.append(f"{method} {path}")

        # Detect auth patterns
        auth_keywords = ["jwt", "bcrypt", "oauth", "session", "token", "password"]
        for keyword in auth_keywords:
            if keyword in content:
                auth_patterns.append(f"Uses {keyword}")

        # Detect data stores
        db_keywords = {
            "sqlite": "SQLite",
            "postgres": "PostgreSQL",
            "mysql": "MySQL",
            "redis": "Redis",
            "mongodb": "MongoDB",
            "create table": "SQL database",
        }
        for keyword, name in db_keywords.items():
            if keyword in content and name not in data_stores:
                data_stores.append(name)

        # Detect external HTTP clients
        http_keywords = ["httpx", "requests", "fetch(", "axios"]
        for keyword in http_keywords:
            if keyword in content:
                external_dependencies.append(f"HTTP client: {keyword}")

        # Detect security anti-patterns
        if "eval(" in content:
            security_observations.append("CRITICAL: eval() usage detected (code injection risk)")
        if "pickle.load" in content:
            security_observations.append("WARNING: pickle.load() without integrity checks")
        if "shell=true" in content:
            security_observations.append("WARNING: subprocess with shell=True (command injection risk)")
        if re.search(r"select.*\+.*\+", content):
            security_observations.append("WARNING: SQL string concatenation detected")

    # Deduplicate
    tech_stack = list(set(tech_stack))
    entry_points = list(set(entry_points))[:10]  # Limit to 10
    auth_patterns = list(set(auth_patterns))
    data_stores = list(set(data_stores))
    external_dependencies = list(set(external_dependencies))

    # Generate raw summary
    lang_list = ", ".join(tech_stack) if tech_stack else "unknown languages"
    file_count = len(code_context.files)
    raw_summary = (
        f"Codebase with {file_count} files in {lang_list}. "
        f"Found {len(entry_points)} entry points, {len(data_stores)} data stores, "
        f"and {len(security_observations)} security observations."
    )

    return CodeSummary(
        tech_stack=tech_stack if tech_stack else ["Unknown"],
        entry_points=entry_points if entry_points else ["No entry points detected"],
        auth_patterns=auth_patterns if auth_patterns else ["No auth patterns detected"],
        data_stores=data_stores if data_stores else ["No data stores detected"],
        external_dependencies=external_dependencies if external_dependencies else ["No external dependencies detected"],
        security_observations=security_observations if security_observations else ["No security issues detected in automated scan"],
        raw_summary=raw_summary,
    )


async def summarize_code(
    code_context: CodeContext,
    provider: LLMProvider,
    temperature: float = 0.2,
) -> CodeSummary:
    """Generate security-focused code summary from code context.

    Produces a condensed CodeSummary (~2KB) from full CodeContext for
    downstream pipeline nodes. Falls back to deterministic extraction if
    LLM fails.

    Args:
        code_context: Full code context from MCP extraction
        provider: LLM provider for generation
        temperature: Sampling temperature

    Returns:
        CodeSummary with structured security analysis
    """
    system_prompt = code_summary_prompt()
    code_text = _format_code_context(code_context)
    user_prompt = _build_xml_tag("code_context", code_text)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    try:
        response = await provider.generate_structured(
            prompt=full_prompt,
            response_model=CodeSummary,
            temperature=temperature,
        )
        return response
    except ProviderError as e:
        logger.warning(f"LLM code summarization failed: {e}. Using deterministic fallback.")
        return _deterministic_code_summary(code_context)


async def extract_assets(
    summary: str,
    description: str,
    architecture_diagram: Optional[str],
    assumptions: Optional[list[str]],
    framework: Framework,
    provider: LLMProvider,
    temperature: float = 0.2,
    code_summary: Optional[CodeSummary] = None,
) -> AssetsList:
    """Extract assets and entities from system description.

    Args:
        summary: Generated system summary
        description: Original system description (may contain structured XML-tagged input)
        architecture_diagram: Optional diagram data
        assumptions: Optional assumptions (legacy list format)
        framework: STRIDE or MAESTRO framework
        provider: LLM provider
        temperature: Sampling temperature
        code_summary: Optional condensed code context for asset identification

    Returns:
        AssetsList with identified assets and entities
    """
    # Parse structured input if present
    component_desc, structured_assumptions, plain_description = _parse_structured_input(
        description, framework
    )

    # Select prompt based on framework
    if framework == Framework.MAESTRO:
        system_prompt = maestro_asset_prompt()
    else:
        system_prompt = stride_asset_prompt()

    # Build prompt
    prompt_parts = []

    if architecture_diagram:
        prompt_parts.append(_build_xml_tag("architecture_diagram", architecture_diagram))

    # Add component description if structured input was parsed
    if component_desc:
        component_text = _format_structured_component_for_prompt(component_desc)
        prompt_parts.append(_build_xml_tag("component_description", component_text))

    prompt_parts.append(_build_xml_tag("description", plain_description))

    # Build assumptions section (prefer structured over legacy list)
    assumptions_text = _build_assumptions_section(assumptions, structured_assumptions)
    if assumptions_text:
        prompt_parts.append(_build_xml_tag("assumptions", assumptions_text))

    # Add code summary if available
    if code_summary:
        code_summary_text = _format_code_summary(code_summary)
        prompt_parts.append(_build_xml_tag("code_summary", code_summary_text))

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
    code_summary: Optional[CodeSummary] = None,
) -> FlowsList:
    """Extract data flows, trust boundaries, and threat sources.

    Args:
        summary: Generated system summary
        description: Original system description (may contain structured XML-tagged input)
        architecture_diagram: Optional diagram data
        assumptions: Optional assumptions (legacy list format)
        assets: Previously extracted assets
        provider: LLM provider
        temperature: Sampling temperature
        code_summary: Optional condensed code context for flow identification

    Returns:
        FlowsList with data flows, trust boundaries, and threat sources
    """
    # Parse structured input if present (use STRIDE framework for flow extraction)
    from backend.models.enums import Framework
    component_desc, structured_assumptions, plain_description = _parse_structured_input(
        description, Framework.STRIDE
    )

    system_prompt = stride_flow_prompt()

    # Build prompt
    prompt_parts = []

    if architecture_diagram:
        prompt_parts.append(_build_xml_tag("architecture_diagram", architecture_diagram))

    # Add component description if structured input was parsed
    if component_desc:
        component_text = _format_structured_component_for_prompt(component_desc)
        prompt_parts.append(_build_xml_tag("component_description", component_text))

    prompt_parts.append(_build_xml_tag("description", plain_description))

    # Build assumptions section (prefer structured over legacy list)
    assumptions_text = _build_assumptions_section(assumptions, structured_assumptions)
    if assumptions_text:
        prompt_parts.append(_build_xml_tag("assumptions", assumptions_text))

    # Add assets
    assets_text = "## Assets\n"
    for asset in assets.assets:
        assets_text += f"- **{asset.name}** ({asset.type}): {asset.description}\n"
    prompt_parts.append(_build_xml_tag("identified_assets_and_entities", assets_text))

    # Add code summary if available
    if code_summary:
        code_summary_text = _format_code_summary(code_summary)
        prompt_parts.append(_build_xml_tag("code_summary", code_summary_text))

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
    code_summary: Optional[CodeSummary] = None,
) -> ThreatsList:
    """Generate or improve threat catalog.

    Args:
        description: System description (may contain structured XML-tagged input)
        architecture_diagram: Optional diagram data
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

    Returns:
        ThreatsList with generated threats
    """
    # Parse structured input if present
    component_desc, structured_assumptions, plain_description = _parse_structured_input(
        description, framework
    )

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

    # Add component description if structured input was parsed
    if component_desc:
        component_text = _format_structured_component_for_prompt(component_desc)
        prompt_parts.append(_build_xml_tag("component_description", component_text))

    prompt_parts.append(_build_xml_tag("description", plain_description))

    # Build assumptions section (prefer structured over legacy list)
    assumptions_text = _build_assumptions_section(assumptions, structured_assumptions)
    if assumptions_text:
        prompt_parts.append(_build_xml_tag("assumptions", assumptions_text))

    # Add assets
    assets_text = "## Assets\n"
    for asset in assets.assets:
        assets_text += f"- **{asset.name}** ({asset.type}): {asset.description}\n"
    prompt_parts.append(_build_xml_tag("identified_assets_and_entities", assets_text))

    # Add flows
    flows_text = "## Data Flows\n"
    for flow in flows.data_flows:
        flows_text += f"- {flow.source_entity} → {flow.target_entity}: {flow.flow_description}\n"
    flows_text += "\n## Trust Boundaries\n"
    for boundary in flows.trust_boundaries:
        flows_text += f"- {boundary.source_entity} ↔ {boundary.target_entity}: {boundary.purpose}\n"
    prompt_parts.append(_build_xml_tag("data_flow", flows_text))

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

    # Add code summary if available
    if code_summary:
        code_summary_text = _format_code_summary(code_summary)
        prompt_parts.append(_build_xml_tag("code_summary", code_summary_text))

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
    code_summary: Optional[CodeSummary] = None,
) -> ContinueThreatModeling:
    """Analyze gaps in threat coverage.

    Args:
        description: System description (may contain structured XML-tagged input)
        architecture_diagram: Optional diagram data
        assumptions: Optional assumptions (legacy list format)
        assets: Identified assets
        flows: Identified flows
        threats: Generated threats
        framework: STRIDE or MAESTRO framework
        provider: LLM provider
        previous_gaps: Optional list of previously identified gaps
        temperature: Sampling temperature
        code_summary: Optional condensed code context for gap analysis

    Returns:
        ContinueThreatModeling with stop decision and gap description
    """
    # Parse structured input if present
    component_desc, structured_assumptions, plain_description = _parse_structured_input(
        description, framework
    )

    # Select prompt based on framework
    if framework == Framework.MAESTRO:
        system_prompt = maestro_gap_prompt()
    else:
        system_prompt = stride_gap_prompt()

    # Build prompt
    prompt_parts = []

    if architecture_diagram:
        prompt_parts.append(_build_xml_tag("architecture_diagram", architecture_diagram))

    # Add component description if structured input was parsed
    if component_desc:
        component_text = _format_structured_component_for_prompt(component_desc)
        prompt_parts.append(_build_xml_tag("component_description", component_text))

    prompt_parts.append(_build_xml_tag("description", plain_description))

    # Build assumptions section (prefer structured over legacy list)
    assumptions_text = _build_assumptions_section(assumptions, structured_assumptions)
    if assumptions_text:
        prompt_parts.append(_build_xml_tag("assumptions", assumptions_text))

    # Add assets
    assets_text = "## Assets\n"
    for asset in assets.assets:
        assets_text += f"- **{asset.name}** ({asset.type}): {asset.description}\n"
    prompt_parts.append(_build_xml_tag("identified_assets_and_entities", assets_text))

    # Add flows
    flows_text = "## Data Flows\n"
    for flow in flows.data_flows:
        flows_text += f"- {flow.source_entity} → {flow.target_entity}: {flow.flow_description}\n"
    flows_text += "\n## Trust Boundaries\n"
    for boundary in flows.trust_boundaries:
        flows_text += f"- {boundary.source_entity} ↔ {boundary.target_entity}: {boundary.purpose}\n"
    prompt_parts.append(_build_xml_tag("data_flow", flows_text))

    # Add threats
    threats_text = "## Generated Threats\n"
    for threat in threats.threats:
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

    # Add code summary if available
    if code_summary:
        code_summary_text = _format_code_summary(code_summary)
        prompt_parts.append(_build_xml_tag("code_summary", code_summary_text))

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
