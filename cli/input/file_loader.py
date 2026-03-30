"""File loading and validation for CLI input.

Loads .txt and .md files, validates size and content, detects structured templates.
"""

import logging
from pathlib import Path

from backend.models.enums import Framework


logger = logging.getLogger(__name__)
from backend.pipeline.input_parser import (
    detect_input_format,
    format_structured_assumptions_for_prompt,
    format_structured_description_for_prompt,
    parse_maestro_assumptions,
    parse_maestro_component_description,
    parse_stride_assumptions,
    parse_stride_component_description,
)
from cli.errors import InputFileError


# Maximum input file size (1MB)
MAX_FILE_SIZE = 1024 * 1024


def load_input_file(file_path: Path) -> str:
    """Load and validate input file.

    Args:
        file_path: Path to input file (.txt or .md)

    Returns:
        File contents as string

    Raises:
        InputFileError: File doesn't exist, is empty, or too large
    """
    # Check file exists
    if not file_path.exists():
        raise InputFileError(
            f"Input file not found: {file_path}\n\n"
            f"Make sure the file path is correct and the file exists."
        )

    # Check file is readable
    if not file_path.is_file():
        raise InputFileError(
            f"Path is not a file: {file_path}\n\n"
            f"Please provide a path to a .txt or .md file."
        )

    # Check file size
    file_size = file_path.stat().st_size
    if file_size == 0:
        raise InputFileError(
            f"Input file is empty: {file_path}\n\n"
            f"Please provide a file with system description content."
        )

    if file_size > MAX_FILE_SIZE:
        raise InputFileError(
            f"Input file too large: {file_size / 1024:.1f} KB (max: {MAX_FILE_SIZE / 1024:.0f} KB)\n\n"
            f"Please reduce file size or split into multiple threat models."
        )

    # Load file content
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise InputFileError(
            f"Failed to read file (encoding error): {file_path}\n\n"
            f"Make sure the file is UTF-8 encoded text.\n"
            f"Error: {e}"
        ) from e
    except Exception as e:
        raise InputFileError(
            f"Failed to read file: {file_path}\n\nError: {e}"
        ) from e

    # Validate content is not just whitespace
    if not content.strip():
        raise InputFileError(
            f"Input file contains only whitespace: {file_path}\n\n"
            f"Please provide a file with meaningful content."
        )

    return content


def detect_framework_from_input(content: str) -> Framework:
    """Detect threat modeling framework from input content.

    Args:
        content: File content to analyze

    Returns:
        Framework.STRIDE for STRIDE templates or plain text (default)
        Framework.MAESTRO for MAESTRO templates

    Note:
        Plain text files default to STRIDE framework
    """
    input_format = detect_input_format(content)

    if input_format == "maestro_structured":
        return Framework.MAESTRO
    # Both "stride_structured" and "plain" default to STRIDE
    return Framework.STRIDE


def parse_structured_input(content: str) -> tuple[str, list[str] | None]:
    """Parse structured XML-tagged input and extract description + assumptions.

    Args:
        content: File content with potential XML tags

    Returns:
        Tuple of (description, assumptions_list)
        - description: Formatted component description for prompts
        - assumptions_list: List of assumption strings, or None for plain text

    Note:
        For plain text, returns (content, None)
        For structured templates, parses XML and formats for prompts
    """
    input_format = detect_input_format(content)

    if input_format == "plain":
        # Plain text - return as-is
        return (content, None)

    # Parse structured input
    if input_format == "stride_structured":
        component_desc = parse_stride_component_description(content)
        assumptions_obj = parse_stride_assumptions(content)

        if not component_desc:
            logger.warning(
                "STRIDE structured template detected but failed to parse. "
                "Falling back to plain text input."
            )
            return (content, None)

        # Format description for prompt
        description = format_structured_description_for_prompt(component_desc)

        # Format assumptions as list of strings
        assumptions = None
        if assumptions_obj:
            formatted = format_structured_assumptions_for_prompt(assumptions_obj)
            # Convert formatted text back to list (split by section)
            assumptions = [line.strip() for line in formatted.split("\n") if line.strip()]
        else:
            logger.warning("STRIDE assumptions section not found or failed to parse")

        return (description, assumptions)

    if input_format == "maestro_structured":
        component_desc = parse_maestro_component_description(content)
        assumptions_obj = parse_maestro_assumptions(content)

        if not component_desc:
            logger.warning(
                "MAESTRO structured template detected but failed to parse. "
                "Falling back to plain text input."
            )
            return (content, None)

        # Format description for prompt
        description = format_structured_description_for_prompt(component_desc)

        # Format assumptions as list of strings
        assumptions = None
        if assumptions_obj:
            formatted = format_structured_assumptions_for_prompt(assumptions_obj)
            assumptions = [line.strip() for line in formatted.split("\n") if line.strip()]
        else:
            logger.warning("MAESTRO assumptions section not found or failed to parse")

        return (description, assumptions)

    # Should never reach here, but fallback to plain text
    return (content, None)
