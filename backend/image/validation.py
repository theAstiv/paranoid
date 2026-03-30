"""Diagram file validation (size, format).

Validation is synchronous (metadata only, no data reading). Keeps layer separation
clean — backend/image/ does not depend on cli/.
"""

from pathlib import Path

from backend.image.errors import DiagramValidationError
from backend.models.enums import DiagramFormat


# File size limits (per vision API requirements)
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB (safe for Claude/OpenAI)
MAX_MERMAID_SIZE_BYTES = 100 * 1024  # 100KB (text file limit)


def validate_diagram_file(file_path: Path) -> DiagramFormat:
    """Validate diagram file and return its format (sync metadata checks only).

    This is a plain def (not async) because it only checks metadata
    (file existence, size, extension) without reading file data.
    The async loading happens in encoder.py and mermaid.py.

    Args:
        file_path: Path to diagram file

    Returns:
        DiagramFormat enum value (png, jpeg, mermaid)

    Raises:
        DiagramValidationError: If file is invalid (unsupported format, too large, etc.)
    """
    # Check file exists
    if not file_path.exists():
        raise DiagramValidationError(f"Diagram file not found: {file_path}")

    if not file_path.is_file():
        raise DiagramValidationError(f"Diagram path is not a file: {file_path}")

    # Detect format from extension
    ext = file_path.suffix.lower()
    if ext == ".png":
        diagram_format = DiagramFormat.PNG
        max_size = MAX_IMAGE_SIZE_BYTES
    elif ext in (".jpg", ".jpeg"):
        diagram_format = DiagramFormat.JPEG
        max_size = MAX_IMAGE_SIZE_BYTES
    elif ext == ".mmd":
        diagram_format = DiagramFormat.MERMAID
        max_size = MAX_MERMAID_SIZE_BYTES
    else:
        raise DiagramValidationError(
            f"Unsupported diagram format: {ext}\n\n"
            f"Supported formats: .png, .jpg, .jpeg, .mmd (Mermaid)"
        )

    # Check file size
    size = file_path.stat().st_size
    if size > max_size:
        if diagram_format == DiagramFormat.MERMAID:
            raise DiagramValidationError(
                f"Mermaid file too large: {size / 1024:.0f}KB (max {max_size / 1024:.0f}KB)\n\n"
                f"Simplify the diagram or split into multiple threat models."
            )
        raise DiagramValidationError(
            f"Image too large: {size / 1024 / 1024:.1f}MB (max {max_size / 1024 / 1024:.0f}MB)\n\n"
            f"Compress the image or use a lower resolution.\n"
            f"Recommended: Use PNG with optimization or JPEG with 80% quality."
        )

    # Validate file is readable
    try:
        file_path.open("rb").close()
    except OSError as e:
        raise DiagramValidationError(f"Cannot read diagram file: {e}")

    return diagram_format
