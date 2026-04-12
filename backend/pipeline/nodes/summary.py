"""System and code summarization nodes.

Contains summarize() for generating system summaries from descriptions/diagrams,
and summarize_code() for condensing code context into security-focused summaries.
"""

import logging
import re
from pathlib import Path

from backend.models.enums import DiagramFormat
from backend.models.extended import CodeContext, CodeSummary, DiagramData, ImageContent
from backend.models.state import SummaryState
from backend.pipeline.nodes.helpers import build_xml_tag, format_assumptions, format_code_context
from backend.pipeline.prompts import code_summary_prompt, stride_summary_prompt
from backend.providers.base import LLMProvider, ProviderError


logger = logging.getLogger(__name__)


async def summarize(
    description: str,
    architecture_diagram: str | None,
    assumptions: list[str] | None,
    code_context: CodeContext | None,
    provider: LLMProvider,
    diagram_data: DiagramData | None = None,
    temperature: float = 0.2,
) -> SummaryState:
    """Generate system summary from description and optional diagram/code context.

    Args:
        description: User-provided system description
        architecture_diagram: DEPRECATED - use diagram_data instead
        assumptions: Optional list of assumptions about the system
        code_context: Optional code context from MCP server
        provider: LLM provider for generation
        diagram_data: Optional diagram data (PNG/JPG/Mermaid)
        temperature: Sampling temperature

    Returns:
        SummaryState with generated summary
    """
    system_prompt = stride_summary_prompt()

    # Build prompt with XML tags
    prompt_parts = []

    # Handle diagrams: Mermaid goes in prompt, PNG/JPG goes via vision API
    if diagram_data and diagram_data.format == DiagramFormat.MERMAID:
        prompt_parts.append(build_xml_tag("architecture_diagram", diagram_data.mermaid_source))
    elif architecture_diagram:  # Legacy support
        prompt_parts.append(build_xml_tag("architecture_diagram", architecture_diagram))

    prompt_parts.append(build_xml_tag("description", description))

    if assumptions:
        assumptions_text = format_assumptions(assumptions)
        prompt_parts.append(build_xml_tag("assumptions", assumptions_text))

    if code_context:
        code_text = format_code_context(code_context)
        prompt_parts.append(build_xml_tag("code_context", code_text))

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
        response_model=SummaryState,
        temperature=temperature,
        max_tokens=512,
        images=images,
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
            security_observations.append(
                "WARNING: subprocess with shell=True (command injection risk)"
            )
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
        external_dependencies=external_dependencies
        if external_dependencies
        else ["No external dependencies detected"],
        security_observations=security_observations
        if security_observations
        else ["No security issues detected in automated scan"],
        raw_summary=raw_summary,
    )


# NOTE: The pipeline runner calls _deterministic_code_summary() directly instead of
# summarize_code() to save one LLM API call per run. This function is intentionally
# kept as an upgrade path for when LLM-quality code summarization is needed (e.g.,
# when code context is too ambiguous for pattern-matching heuristics alone).
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
    code_text = format_code_context(code_context)
    user_prompt = build_xml_tag("code_context", code_text)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    try:
        response = await provider.generate_structured(
            prompt=full_prompt,
            response_model=CodeSummary,
            temperature=temperature,
            max_tokens=1500,
        )
        return response
    except ProviderError as e:
        logger.warning(f"LLM code summarization failed: {e}. Using deterministic fallback.")
        return _deterministic_code_summary(code_context)
