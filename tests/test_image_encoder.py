"""Tests for image encoding and validation (backend/image/).

Tests diagram file loading (PNG/JPG/Mermaid) with minimal test files.
"""

import base64
from pathlib import Path

import pytest

from backend.image.encoder import load_image_as_diagram_data
from backend.image.errors import DiagramValidationError
from backend.image.mermaid import load_mermaid_as_diagram_data
from backend.image.validation import validate_diagram_file
from backend.models.enums import DiagramFormat


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


def test_validate_diagram_file_png(tmp_path):
    """Test PNG file validation."""
    png_file = tmp_path / "diagram.png"
    # Create minimal 1x1 PNG (67 bytes)
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    png_file.write_bytes(png_data)

    format = validate_diagram_file(png_file)
    assert format == DiagramFormat.PNG


def test_validate_diagram_file_jpeg(tmp_path):
    """Test JPEG file validation (.jpg and .jpeg extensions)."""
    for ext in [".jpg", ".jpeg"]:
        jpeg_file = tmp_path / f"diagram{ext}"
        # Create minimal JPEG (134 bytes) - 1x1 red pixel
        jpeg_data = base64.b64decode(
            "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
            "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIy"
            "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIA"
            "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEB"
            "AQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwAB//2Q=="
        )
        jpeg_file.write_bytes(jpeg_data)

        format = validate_diagram_file(jpeg_file)
        assert format == DiagramFormat.JPEG


def test_validate_diagram_file_mermaid(tmp_path):
    """Test Mermaid file validation."""
    mmd_file = tmp_path / "diagram.mmd"
    mmd_file.write_text("graph TD\n  A-->B")

    format = validate_diagram_file(mmd_file)
    assert format == DiagramFormat.MERMAID


def test_validate_diagram_file_not_found():
    """Test validation fails for nonexistent file."""
    with pytest.raises(DiagramValidationError, match="not found"):
        validate_diagram_file(Path("/nonexistent/file.png"))


def test_validate_diagram_file_is_directory(tmp_path):
    """Test validation fails for directory path."""
    with pytest.raises(DiagramValidationError, match="not a file"):
        validate_diagram_file(tmp_path)


def test_validate_diagram_file_unsupported_format(tmp_path):
    """Test validation fails for unsupported file format."""
    svg_file = tmp_path / "diagram.svg"
    svg_file.write_text("<svg></svg>")

    with pytest.raises(DiagramValidationError, match="Unsupported diagram format"):
        validate_diagram_file(svg_file)


def test_validate_diagram_file_image_too_large(tmp_path):
    """Test validation fails for oversized image (>5MB)."""
    large_png = tmp_path / "large.png"
    # Create 6MB file (exceeds 5MB limit)
    large_png.write_bytes(b"\x89PNG" + b"x" * (6 * 1024 * 1024))

    with pytest.raises(DiagramValidationError, match="Image too large.*6.0MB"):
        validate_diagram_file(large_png)


def test_validate_diagram_file_mermaid_too_large(tmp_path):
    """Test validation fails for oversized Mermaid file (>100KB)."""
    large_mmd = tmp_path / "large.mmd"
    # Create 105KB file (exceeds 100KB limit = 102,400 bytes)
    # Each line is ~8 bytes, so 13,500 * 8 = 108,000 bytes
    large_mmd.write_text("graph TD\n" + "  A-->B\n" * 13_500)

    with pytest.raises(DiagramValidationError, match="Mermaid file too large.*10[0-9]KB"):
        validate_diagram_file(large_mmd)


# ---------------------------------------------------------------------------
# PNG/JPG encoding tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_image_as_diagram_data_png(tmp_path):
    """Test PNG loading and base64 encoding."""
    png_file = tmp_path / "diagram.png"
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    png_file.write_bytes(png_data)

    diagram_data = await load_image_as_diagram_data(png_file, DiagramFormat.PNG)

    assert diagram_data.format == DiagramFormat.PNG
    assert diagram_data.source_path == str(png_file)
    assert diagram_data.media_type == "image/png"
    assert diagram_data.size_bytes == len(png_data)
    # Verify base64 can be decoded back to original
    assert base64.b64decode(diagram_data.base64_data) == png_data
    # Mermaid fields should be None for images
    assert diagram_data.mermaid_source is None


@pytest.mark.asyncio
async def test_load_image_as_diagram_data_jpeg(tmp_path):
    """Test JPEG loading and base64 encoding."""
    jpeg_file = tmp_path / "diagram.jpg"
    jpeg_data = base64.b64decode(
        "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
        "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIy"
        "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIA"
        "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEB"
        "AQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwAB//2Q=="
    )
    jpeg_file.write_bytes(jpeg_data)

    diagram_data = await load_image_as_diagram_data(jpeg_file, DiagramFormat.JPEG)

    assert diagram_data.format == DiagramFormat.JPEG
    assert diagram_data.media_type == "image/jpeg"
    assert diagram_data.size_bytes == len(jpeg_data)
    assert base64.b64decode(diagram_data.base64_data) == jpeg_data


# ---------------------------------------------------------------------------
# Mermaid loading tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_mermaid_as_diagram_data(tmp_path):
    """Test Mermaid file loading."""
    mmd_file = tmp_path / "flow.mmd"
    mermaid_source = "graph TD\n  A[User] -->|Request| B[API]\n  B -->|Response| A"
    mmd_file.write_text(mermaid_source)

    diagram_data = await load_mermaid_as_diagram_data(mmd_file)

    assert diagram_data.format == DiagramFormat.MERMAID
    assert diagram_data.source_path == str(mmd_file)
    assert diagram_data.mermaid_source == mermaid_source
    # Image fields should be None for Mermaid
    assert diagram_data.base64_data is None
    assert diagram_data.media_type is None
    assert diagram_data.size_bytes is None


@pytest.mark.asyncio
async def test_load_mermaid_strips_whitespace(tmp_path):
    """Test Mermaid loader strips leading/trailing whitespace."""
    mmd_file = tmp_path / "flow.mmd"
    mmd_file.write_text("\n\n  graph TD\n  A-->B  \n\n")

    diagram_data = await load_mermaid_as_diagram_data(mmd_file)

    assert diagram_data.mermaid_source == "graph TD\n  A-->B"


@pytest.mark.asyncio
async def test_load_mermaid_empty_file_fails(tmp_path):
    """Test Mermaid loader rejects empty files."""
    mmd_file = tmp_path / "empty.mmd"
    mmd_file.write_text("   \n  \n  ")

    with pytest.raises(ValueError, match="empty"):
        await load_mermaid_as_diagram_data(mmd_file)


@pytest.mark.asyncio
async def test_load_mermaid_invalid_utf8_fails(tmp_path):
    """Test Mermaid loader rejects non-UTF-8 files."""
    mmd_file = tmp_path / "invalid.mmd"
    mmd_file.write_bytes(b"\xff\xfe Invalid UTF-8")

    with pytest.raises(UnicodeDecodeError):
        await load_mermaid_as_diagram_data(mmd_file)
