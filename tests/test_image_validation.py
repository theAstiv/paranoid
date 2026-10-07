"""Tests for the multi-diagram validation helpers (backend/image/validation.py).

Covers validate_diagram_bytes (Pillow-based image checks), validate_diagram_set
(count/total-size caps and name de-duplication), sanitize_diagram_name, and the
DiagramData per-format field validator. test_image_encoder.py covers the
single-diagram happy-path/legacy validate_diagram_file behavior; this file
covers what 5a-1 added.
"""

import io
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from backend.image.errors import DiagramValidationError
from backend.image.validation import (
    MAX_DIAGRAMS,
    MAX_IMAGE_PIXELS_TOTAL,
    MAX_TOTAL_IMAGE_BYTES,
    sanitize_diagram_name,
    validate_diagram_bytes,
    validate_diagram_set,
)
from backend.models.enums import DiagramFormat
from backend.models.extended import DiagramData


def _png_bytes(size: tuple[int, int] = (10, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(size: tuple[int, int] = (10, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size).save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# validate_diagram_bytes
# ---------------------------------------------------------------------------


def test_validate_diagram_bytes_valid_png():
    assert validate_diagram_bytes("diagram.png", _png_bytes()) == DiagramFormat.PNG


def test_validate_diagram_bytes_valid_jpeg():
    assert validate_diagram_bytes("diagram.jpg", _jpeg_bytes()) == DiagramFormat.JPEG


def test_validate_diagram_bytes_mermaid_txt_extension_accepted():
    """CLI/web both accept .txt as Mermaid (new in 5a-1)."""
    assert validate_diagram_bytes("diagram.txt", b"graph TD\n  A-->B") == DiagramFormat.MERMAID


def test_validate_diagram_bytes_unknown_extension_rejected():
    with pytest.raises(DiagramValidationError, match="Unsupported diagram format"):
        validate_diagram_bytes("diagram.exe", b"not a diagram")


def test_validate_diagram_bytes_format_mismatch():
    """Extension says PNG, content is actually a JPEG."""
    with pytest.raises(DiagramValidationError, match="but content is"):
        validate_diagram_bytes("diagram.png", _jpeg_bytes())


def test_validate_diagram_bytes_truncated_png_rejected():
    raw = _png_bytes(size=(64, 64))
    truncated = raw[: len(raw) // 2]
    with pytest.raises(DiagramValidationError):
        validate_diagram_bytes("diagram.png", truncated)


def test_validate_diagram_bytes_truncated_jpeg_rejected():
    """verify() passes a truncated JPEG; load() does not.

    A small enough JPEG can compress into so few MCU blocks that even a
    50% truncation still leaves a structurally complete image, which
    neither check would catch — so this uses a larger image and confirms
    the gap directly before relying on it.

    Mutation check: if validate_diagram_bytes's image check is switched
    from img.load() back to img.verify(), this test must start failing.
    """
    raw = _jpeg_bytes(size=(200, 200))
    truncated = raw[: int(len(raw) * 0.8)]

    # Confirms the premise this test relies on, so a future Pillow version
    # that changes this behavior fails loudly here rather than silently
    # making the test meaningless.
    with io.BytesIO(truncated) as buf:
        Image.open(buf).verify()  # must NOT raise

    with pytest.raises(DiagramValidationError):
        validate_diagram_bytes("diagram.jpg", truncated)


def test_validate_diagram_bytes_oversize_dimensions_rejected():
    mock_img = MagicMock()
    mock_img.format = "PNG"
    mock_img.size = (9000, 100)  # exceeds MAX_IMAGE_DIMENSION (8000) on one side

    with patch("backend.image.validation.Image.open", return_value=mock_img):
        with pytest.raises(DiagramValidationError, match="exceed the"):
            validate_diagram_bytes("diagram.png", b"fake-but-mocked")

    mock_img.load.assert_not_called()


def test_validate_diagram_bytes_decompression_bomb_under_pil_own_threshold():
    """Our own pixel-count guard is stricter than Pillow's, and runs first.

    8000x6000 fits within MAX_IMAGE_DIMENSION (8000px/side) on both sides —
    so this exercises the *pixel-total* check specifically, not the
    per-side dimension check — but its 48,000,000 total pixels exceed our
    MAX_IMAGE_PIXELS_TOTAL (40MP) while staying well under Pillow's own
    decompression-bomb threshold (Image.MAX_IMAGE_PIXELS, ~89.5MP), where
    Pillow itself would not even warn. That proves this is caught by our
    own guard, before img.load() (where Pillow's bomb logic lives) is ever
    reached — not by Pillow's.
    """
    width, height = 8000, 6000
    assert width <= 8000
    assert height <= 8000
    assert MAX_IMAGE_PIXELS_TOTAL < width * height < Image.MAX_IMAGE_PIXELS

    mock_img = MagicMock()
    mock_img.format = "PNG"
    mock_img.size = (width, height)

    with patch("backend.image.validation.Image.open", return_value=mock_img):
        with pytest.raises(DiagramValidationError, match="pixels"):
            validate_diagram_bytes("bomb.png", b"fake-but-mocked")

    mock_img.load.assert_not_called()


# ---------------------------------------------------------------------------
# validate_diagram_set
# ---------------------------------------------------------------------------


def _mermaid_diagram(name: str, source_path: str = "a.mmd") -> DiagramData:
    return DiagramData(
        format=DiagramFormat.MERMAID,
        source_path=source_path,
        mermaid_source="graph TD\n  A-->B",
        name=name,
    )


def _image_diagram(name: str, size_bytes: int = 1000) -> DiagramData:
    return DiagramData(
        format=DiagramFormat.PNG,
        source_path=f"{name}.png",
        base64_data="A" * 100,
        media_type="image/png",
        size_bytes=size_bytes,
        name=name,
    )


def test_validate_diagram_set_too_many_diagrams():
    diagrams = [_mermaid_diagram(f"d{i}") for i in range(MAX_DIAGRAMS + 1)]
    with pytest.raises(DiagramValidationError, match="Too many diagrams"):
        validate_diagram_set(diagrams)


def test_validate_diagram_set_total_image_bytes_over_cap():
    # Three images whose sizes sum over the cap, each individually fine.
    per_image = MAX_TOTAL_IMAGE_BYTES // 2
    diagrams = [_image_diagram(f"img{i}", size_bytes=per_image) for i in range(3)]
    with pytest.raises(DiagramValidationError, match="Total image size"):
        validate_diagram_set(diagrams)


def test_validate_diagram_set_dedupes_names_without_reusing_a_resolved_name():
    """["a", "a (2)", "a"] must not collapse two diagrams onto "a (2)"."""
    diagrams = [_mermaid_diagram("a"), _mermaid_diagram("a (2)"), _mermaid_diagram("a")]
    result = validate_diagram_set(diagrams)
    names = [d.name for d in result]
    assert names == ["a", "a (2)", "a (3)"]
    assert len(set(names)) == len(names)


def test_validate_diagram_set_does_not_mutate_caller_objects():
    original = _mermaid_diagram("a")
    diagrams = [original, _mermaid_diagram("a")]
    validate_diagram_set(diagrams)
    assert original.name == "a"


def test_validate_diagram_set_within_limits_passes_through():
    diagrams = [_mermaid_diagram("a"), _image_diagram("b")]
    result = validate_diagram_set(diagrams)
    assert [d.name for d in result] == ["a", "b"]


# ---------------------------------------------------------------------------
# sanitize_diagram_name
# ---------------------------------------------------------------------------


def test_sanitize_diagram_name_strips_forbidden_characters():
    assert sanitize_diagram_name('a<b>c"d&e') == "abcde"


def test_sanitize_diagram_name_newline_becomes_space_not_deleted():
    assert sanitize_diagram_name("a\nb") == "a b"


def test_sanitize_diagram_name_strips_bidi_override():
    bidi_override = chr(0x202E)  # constructed, not a literal, to avoid PLE2502
    assert bidi_override not in sanitize_diagram_name(f"a{bidi_override}b")


def test_sanitize_diagram_name_strips_zero_width():
    assert "\u200b" not in sanitize_diagram_name("a\u200bb")


def test_sanitize_diagram_name_caps_length():
    assert len(sanitize_diagram_name("x" * 200)) == 80


def test_sanitize_diagram_name_empty_falls_back():
    assert sanitize_diagram_name("") == "diagram-1"
    assert sanitize_diagram_name(None, fallback_index=3) == "diagram-3"


def test_sanitize_diagram_name_only_forbidden_chars_falls_back():
    assert sanitize_diagram_name("<<<>>>", fallback_index=2) == "diagram-2"


# ---------------------------------------------------------------------------
# DiagramData per-format validator
# ---------------------------------------------------------------------------


def test_diagram_data_png_requires_base64_and_media_type():
    with pytest.raises(ValueError, match="requires base64_data and media_type"):
        DiagramData(format=DiagramFormat.PNG, source_path="x.png")


def test_diagram_data_mermaid_requires_source():
    with pytest.raises(ValueError, match="requires a non-empty mermaid_source"):
        DiagramData(format=DiagramFormat.MERMAID, source_path="x.mmd")


def test_diagram_data_defaults_name_from_source_path_stem():
    d = DiagramData(
        format=DiagramFormat.MERMAID,
        source_path="/a/b/architecture.mmd",
        mermaid_source="graph TD",
    )
    assert d.name == "architecture"


def test_diagram_data_explicit_name_not_overridden():
    d = DiagramData(
        format=DiagramFormat.MERMAID,
        source_path="/a/b/architecture.mmd",
        mermaid_source="graph TD",
        name="My Diagram",
    )
    assert d.name == "My Diagram"
