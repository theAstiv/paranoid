"""Integration tests for CLI --diagram flag (PNG/JPG/Mermaid input)."""

import base64
from pathlib import Path

import pytest

from backend.models.enums import DiagramFormat
from cli.errors import InputFileError
from cli.input.diagram_loader import load_diagram_file


# ---------------------------------------------------------------------------
# Diagram loader integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_diagram_file_png(tmp_path):
    """Test loading PNG diagram via CLI loader."""
    png_file = tmp_path / "arch.png"
    # Minimal 1x1 PNG (67 bytes)
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    png_file.write_bytes(png_data)

    diagram_data = await load_diagram_file(png_file)

    assert diagram_data.format == DiagramFormat.PNG
    assert diagram_data.media_type == "image/png"
    assert diagram_data.base64_data is not None
    assert diagram_data.mermaid_source is None


@pytest.mark.asyncio
async def test_load_diagram_file_jpeg(tmp_path):
    """Test loading JPEG diagram via CLI loader."""
    jpeg_file = tmp_path / "arch.jpg"
    # Minimal 1x1 JPEG
    jpeg_data = base64.b64decode(
        "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
        "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIy"
        "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIA"
        "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEB"
        "AQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwAB//2Q=="
    )
    jpeg_file.write_bytes(jpeg_data)

    diagram_data = await load_diagram_file(jpeg_file)

    assert diagram_data.format == DiagramFormat.JPEG
    assert diagram_data.media_type == "image/jpeg"
    assert diagram_data.base64_data is not None


@pytest.mark.asyncio
async def test_load_diagram_file_mermaid(tmp_path):
    """Test loading Mermaid diagram via CLI loader."""
    mmd_file = tmp_path / "flow.mmd"
    mermaid_source = "graph TD\n  A[User] --> B[API]"
    mmd_file.write_text(mermaid_source)

    diagram_data = await load_diagram_file(mmd_file)

    assert diagram_data.format == DiagramFormat.MERMAID
    assert diagram_data.mermaid_source == mermaid_source
    assert diagram_data.base64_data is None
    assert diagram_data.media_type is None


@pytest.mark.asyncio
async def test_load_diagram_file_not_found():
    """Test loader raises InputFileError for missing file."""
    with pytest.raises(InputFileError, match="not found"):
        await load_diagram_file(Path("/nonexistent/diagram.png"))


@pytest.mark.asyncio
async def test_load_diagram_file_too_large(tmp_path):
    """Test loader raises InputFileError for oversized image."""
    large_png = tmp_path / "huge.png"
    # Create 6MB file (exceeds 5MB limit)
    large_png.write_bytes(b"\x89PNG" + b"x" * (6 * 1024 * 1024))

    with pytest.raises(InputFileError, match="Image too large"):
        await load_diagram_file(large_png)


@pytest.mark.asyncio
async def test_load_diagram_file_unsupported_format(tmp_path):
    """Test loader raises InputFileError for unsupported format."""
    svg_file = tmp_path / "diagram.svg"
    svg_file.write_text("<svg></svg>")

    with pytest.raises(InputFileError, match="Unsupported diagram format"):
        await load_diagram_file(svg_file)


@pytest.mark.asyncio
async def test_load_diagram_file_mermaid_empty(tmp_path):
    """Test loader raises InputFileError for empty Mermaid file."""
    empty_mmd = tmp_path / "empty.mmd"
    empty_mmd.write_text("   \n  ")

    with pytest.raises(InputFileError, match="empty"):
        await load_diagram_file(empty_mmd)


# ---------------------------------------------------------------------------
# Error chain tests (DiagramValidationError → InputFileError)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagram_validation_error_chain(tmp_path):
    """Test DiagramValidationError is re-raised as InputFileError."""
    # Create invalid diagram (directory instead of file)
    invalid_path = tmp_path / "not_a_file"
    invalid_path.mkdir()

    with pytest.raises(InputFileError, match="not a file"):
        await load_diagram_file(invalid_path)


# ---------------------------------------------------------------------------
# Path resolution tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_diagram_file_accepts_string_path(tmp_path):
    """Test loader accepts string path (not just Path object)."""
    png_file = tmp_path / "test.png"
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    png_file.write_bytes(png_data)

    # Pass as string instead of Path
    diagram_data = await load_diagram_file(str(png_file))

    assert diagram_data.format == DiagramFormat.PNG
    assert Path(diagram_data.source_path).exists()


@pytest.mark.asyncio
async def test_load_diagram_file_resolves_relative_path(tmp_path):
    """Test loader resolves relative paths to absolute."""
    png_file = tmp_path / "relative.png"
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    png_file.write_bytes(png_data)

    # Load and verify path is resolved
    diagram_data = await load_diagram_file(png_file)

    assert Path(diagram_data.source_path).is_absolute()
