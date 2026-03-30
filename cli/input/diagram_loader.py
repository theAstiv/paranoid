"""Async diagram file loading for CLI (validation + encoding/parsing)."""

from pathlib import Path

from backend.image import (
    load_image_as_diagram_data,
    load_mermaid_as_diagram_data,
    validate_diagram_file,
)
from backend.image.errors import DiagramValidationError
from backend.models.enums import DiagramFormat
from backend.models.extended import DiagramData
from cli.errors import InputFileError


async def load_diagram_file(file_path: str | Path) -> DiagramData:
    """Load and validate diagram file (PNG/JPG/Mermaid).

    This is the CLI entry point for diagram loading. It validates the file,
    then loads/encodes it based on format.

    Args:
        file_path: Path to diagram file (.png, .jpg, .jpeg, .mmd)

    Returns:
        DiagramData with format-appropriate fields populated

    Raises:
        InputFileError: If file is invalid (not found, too large, unsupported format)
    """
    path = Path(file_path).resolve()

    # Step 1: Validate file (sync metadata checks)
    try:
        diagram_format = validate_diagram_file(path)
    except DiagramValidationError as e:
        # Re-raise as InputFileError for CLI layer
        raise InputFileError(str(e)) from e

    # Step 2: Load/encode based on format (async data reading)
    try:
        if diagram_format in (DiagramFormat.PNG, DiagramFormat.JPEG):
            # PNG/JPG: Load and base64 encode for vision API
            return await load_image_as_diagram_data(path, diagram_format)
        elif diagram_format == DiagramFormat.MERMAID:
            # Mermaid: Load as text (no encoding needed)
            return await load_mermaid_as_diagram_data(path)
        else:
            # Should never reach here (validation ensures supported format)
            raise InputFileError(f"Unsupported diagram format: {diagram_format}")
    except ValueError as e:
        # Catch ValueError from empty Mermaid files and re-raise as InputFileError
        raise InputFileError(str(e)) from e
