"""Image encoding for vision APIs (PNG/JPG → base64).

Per RULES.md: All file I/O is async. Uses aiofiles for non-blocking reads.
"""

import base64
from pathlib import Path

import aiofiles

from backend.models.enums import DiagramFormat
from backend.models.extended import DiagramData


async def load_image_as_diagram_data(
    file_path: Path,
    diagram_format: DiagramFormat,
) -> DiagramData:
    """Load PNG/JPG image and encode as base64 for vision APIs.

    Args:
        file_path: Path to image file
        diagram_format: DiagramFormat.PNG or DiagramFormat.JPEG

    Returns:
        DiagramData with base64_data, media_type, and size_bytes populated

    Raises:
        OSError: If file cannot be read
    """
    # Read file asynchronously (RULES.md: async for all file I/O)
    async with aiofiles.open(file_path, "rb") as f:
        image_bytes = await f.read()

    # Encode to base64
    base64_data = base64.b64encode(image_bytes).decode("ascii")

    # Determine MIME type
    if diagram_format == DiagramFormat.PNG:
        media_type = "image/png"
    elif diagram_format == DiagramFormat.JPEG:
        media_type = "image/jpeg"
    else:
        raise ValueError(f"Unsupported image format for encoding: {diagram_format}")

    return DiagramData(
        format=diagram_format,
        source_path=str(file_path),
        base64_data=base64_data,
        media_type=media_type,
        size_bytes=len(image_bytes),
    )
