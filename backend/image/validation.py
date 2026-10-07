"""Diagram file validation (size, format, and image content).

Images are validated with Pillow (header check, format match, our own
pixel-dimension/decompression-bomb guard, then a full decode) rather than a
hand-written magic-byte check. Mermaid/text files are validated by size and
UTF-8 decodability. Callers that run this from an event loop (the web route)
should wrap calls in `asyncio.to_thread` since Pillow decoding is CPU-bound.
"""

import re
import unicodedata
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from backend.image.errors import DiagramValidationError
from backend.models.enums import DiagramFormat
from backend.models.extended import DiagramData


# Per-diagram and per-set limits. Constants, not env vars (keep the scope
# basic). See .claude/tasks/week5a-plan.md S5 for the provider-limit
# derivation behind each number.
MAX_DIAGRAMS = 5
# 3.75MB raw -> exactly 5MB once base64-encoded (3_932_160 * 4 / 3 ==
# 5_242_880), matching Anthropic's Bedrock/GCP per-image cap with no margin.
# If that documented limit ever tightens, this constant must drop with it.
MAX_IMAGE_SIZE_BYTES = 3_932_160
MAX_MERMAID_SIZE_BYTES = 100 * 1024  # 100KB (text file limit, unchanged)
MAX_TOTAL_IMAGE_BYTES = 15 * 1024 * 1024  # 15MB raw across all images in a set
MAX_TOTAL_MERMAID_BYTES = 200 * 1024  # 200KB across all Mermaid diagrams in a set
MAX_IMAGE_DIMENSION = 8000  # px per side (Anthropic's documented hard limit)
MAX_IMAGE_PIXELS_TOTAL = 40_000_000  # 40MP; our own decompression-bomb guard

_EXTENSION_FORMATS: dict[str, DiagramFormat] = {
    ".png": DiagramFormat.PNG,
    ".jpg": DiagramFormat.JPEG,
    ".jpeg": DiagramFormat.JPEG,
    ".mmd": DiagramFormat.MERMAID,
    ".txt": DiagramFormat.MERMAID,
}

_PIL_FORMAT_BY_DIAGRAM_FORMAT = {
    DiagramFormat.PNG: "PNG",
    DiagramFormat.JPEG: "JPEG",
}


def format_for_extension(filename: str) -> DiagramFormat:
    ext = Path(filename).suffix.lower()
    diagram_format = _EXTENSION_FORMATS.get(ext)
    if diagram_format is None:
        raise DiagramValidationError(
            f"Unsupported diagram format: {ext}\n\n"
            f"Supported formats: .png, .jpg, .jpeg, .mmd/.txt (Mermaid)"
        )
    return diagram_format


def _validate_mermaid_bytes(raw: bytes) -> None:
    if len(raw) > MAX_MERMAID_SIZE_BYTES:
        raise DiagramValidationError(
            f"Mermaid file too large: {len(raw) / 1024:.0f}KB "
            f"(max {MAX_MERMAID_SIZE_BYTES / 1024:.0f}KB)\n\n"
            f"Simplify the diagram or split into multiple threat models."
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise DiagramValidationError(f"Mermaid file is not valid UTF-8: {e}") from e
    if not text.strip():
        raise DiagramValidationError("Mermaid file is empty")


def _validate_image_bytes(raw: bytes, diagram_format: DiagramFormat) -> None:
    if len(raw) > MAX_IMAGE_SIZE_BYTES:
        raise DiagramValidationError(
            f"Image too large: {len(raw) / 1024 / 1024:.1f}MB "
            f"(max {MAX_IMAGE_SIZE_BYTES / 1024 / 1024:.2f}MB)\n\n"
            f"Compress the image or use a lower resolution.\n"
            f"Recommended: Use PNG with optimization or JPEG with 80% quality."
        )

    expected_pil_format = _PIL_FORMAT_BY_DIAGRAM_FORMAT[diagram_format]
    try:
        img = Image.open(BytesIO(raw))

        if img.format != expected_pil_format:
            raise DiagramValidationError(
                f"File extension suggests {expected_pil_format} but content is "
                f"{img.format or 'unrecognized'}"
            )

        width, height = img.size
        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            raise DiagramValidationError(
                f"Image dimensions {width}x{height}px exceed the "
                f"{MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION}px limit"
            )
        if width * height > MAX_IMAGE_PIXELS_TOTAL:
            raise DiagramValidationError(
                f"Image has {width * height:,} pixels, exceeding the "
                f"{MAX_IMAGE_PIXELS_TOTAL:,}-pixel limit"
            )

        # Full decode (not verify() - verify() passes a truncated JPEG).
        # Safe from decompression bombs because the pixel check above runs first.
        img.load()
    except UnidentifiedImageError as e:
        raise DiagramValidationError(f"Not a valid {expected_pil_format} image: {e}") from e
    except Image.DecompressionBombError as e:
        raise DiagramValidationError(f"Image rejected as a decompression bomb: {e}") from e
    except OSError as e:
        raise DiagramValidationError(f"Image file is truncated or corrupt: {e}") from e


def validate_diagram_bytes(filename: str, raw: bytes) -> DiagramFormat:
    """Validate diagram content and return its format.

    This is the shared rule set for both the web upload path and the CLI
    path (`validate_diagram_file` delegates here). Images are checked with
    Pillow: header read, format-matches-extension, our own pixel limit
    (checked before decoding), then a full decode. CPU-bound — callers in
    an event loop should run this via `asyncio.to_thread`.

    Args:
        filename: Original filename (used only for its extension)
        raw: Full file content

    Returns:
        DiagramFormat enum value (png, jpeg, mermaid)

    Raises:
        DiagramValidationError: If content is invalid (unsupported format,
            too large, wrong format, corrupt/truncated, oversize dimensions)
    """
    diagram_format = format_for_extension(filename)

    if diagram_format == DiagramFormat.MERMAID:
        _validate_mermaid_bytes(raw)
    else:
        _validate_image_bytes(raw, diagram_format)

    return diagram_format


def validate_diagram_file(file_path: Path) -> DiagramFormat:
    """Validate a diagram file on disk and return its format.

    Thin wrapper around `validate_diagram_bytes` for the CLI path: checks
    existence/readability, then reads the file and delegates the content
    check so CLI and web share one rule set.

    Args:
        file_path: Path to diagram file

    Returns:
        DiagramFormat enum value (png, jpeg, mermaid)

    Raises:
        DiagramValidationError: If file is invalid (not found, unreadable,
            unsupported format, too large, corrupt, etc.)
    """
    if not file_path.exists():
        raise DiagramValidationError(f"Diagram file not found: {file_path}")
    if not file_path.is_file():
        raise DiagramValidationError(f"Diagram path is not a file: {file_path}")

    # Reject on size before reading the whole file — avoids pulling an
    # oversize file fully into memory just to discard it a moment later.
    diagram_format = format_for_extension(file_path.name)
    max_size = (
        MAX_MERMAID_SIZE_BYTES if diagram_format == DiagramFormat.MERMAID else MAX_IMAGE_SIZE_BYTES
    )
    try:
        stat_size = file_path.stat().st_size
    except OSError as e:
        raise DiagramValidationError(f"Cannot read diagram file: {e}") from e
    if stat_size > max_size:
        # Same message validate_diagram_bytes would raise; raising it here
        # (from the cheap stat, not a full read) is just an earlier exit.
        if diagram_format == DiagramFormat.MERMAID:
            raise DiagramValidationError(
                f"Mermaid file too large: {stat_size / 1024:.0f}KB "
                f"(max {MAX_MERMAID_SIZE_BYTES / 1024:.0f}KB)\n\n"
                f"Simplify the diagram or split into multiple threat models."
            )
        raise DiagramValidationError(
            f"Image too large: {stat_size / 1024 / 1024:.1f}MB "
            f"(max {MAX_IMAGE_SIZE_BYTES / 1024 / 1024:.2f}MB)\n\n"
            f"Compress the image or use a lower resolution.\n"
            f"Recommended: Use PNG with optimization or JPEG with 80% quality."
        )

    try:
        raw = file_path.read_bytes()
    except OSError as e:
        raise DiagramValidationError(f"Cannot read diagram file: {e}") from e

    return validate_diagram_bytes(file_path.name, raw)


def image_byte_length(diagram: DiagramData) -> int:
    """Raw byte length of an image diagram, used for the total-size budget.

    Prefers `size_bytes` (set by the encoder/CLI loader); falls back to
    decoding `base64_data`'s length so a diagram reconstructed without
    `size_bytes` (e.g. a stored row reconstructed for reuse on a re-run)
    still counts toward the total instead of silently contributing 0.
    """
    if diagram.size_bytes is not None:
        return diagram.size_bytes
    if diagram.base64_data:
        # base64 inflates size by ~4/3; this recovers the raw byte count
        # without actually decoding.
        padding = diagram.base64_data.count("=")
        return (len(diagram.base64_data) * 3) // 4 - padding
    return 0


def validate_diagram_set(diagrams: list[DiagramData]) -> list[DiagramData]:
    """Validate a set of diagrams as a whole and de-duplicate their names.

    Checks the total diagram count and the per-kind total byte budgets
    (these can only be checked once every diagram in the set is known).
    Duplicate names are resolved by appending " (2)", " (3)", etc. in list
    order, incrementing past any name already used so two diagrams never
    end up sharing a resolved name.

    Args:
        diagrams: Diagrams already individually validated/loaded

    Returns:
        A new list in the same order. Diagrams whose name didn't need to
        change are returned as-is; renamed diagrams are copies — the
        caller's own DiagramData objects are never mutated.

    Raises:
        DiagramValidationError: Too many diagrams, or a total byte budget
            is exceeded
    """
    if len(diagrams) > MAX_DIAGRAMS:
        raise DiagramValidationError(
            f"Too many diagrams: {len(diagrams)} provided; the limit is {MAX_DIAGRAMS}."
        )

    total_image_bytes = sum(
        image_byte_length(d)
        for d in diagrams
        if d.format in (DiagramFormat.PNG, DiagramFormat.JPEG)
    )
    if total_image_bytes > MAX_TOTAL_IMAGE_BYTES:
        raise DiagramValidationError(
            f"Total image size {total_image_bytes / 1024 / 1024:.1f}MB exceeds the "
            f"{MAX_TOTAL_IMAGE_BYTES / 1024 / 1024:.0f}MB limit across all diagrams."
        )

    total_mermaid_bytes = sum(
        len((d.mermaid_source or "").encode("utf-8"))
        for d in diagrams
        if d.format == DiagramFormat.MERMAID
    )
    if total_mermaid_bytes > MAX_TOTAL_MERMAID_BYTES:
        raise DiagramValidationError(
            f"Total Mermaid size {total_mermaid_bytes / 1024:.0f}KB exceeds the "
            f"{MAX_TOTAL_MERMAID_BYTES / 1024:.0f}KB limit across all diagrams."
        )

    seen: set[str] = set()
    result: list[DiagramData] = []
    for diagram in diagrams:
        name = diagram.name
        if name in seen:
            counter = 2
            candidate = f"{name} ({counter})"
            while candidate in seen:
                counter += 1
                candidate = f"{name} ({counter})"
            name = candidate
        seen.add(name)
        result.append(
            diagram if name == diagram.name else diagram.model_copy(update={"name": name})
        )

    return result


def sanitize_diagram_name(name: str | None, fallback_index: int = 1) -> str:
    """Sanitize a diagram display name for safe use in prompts and the UI.

    Strips angle brackets/quotes/ampersand, collapses whitespace (including
    control whitespace like newlines/tabs — collapsed to a single space,
    not deleted, so "a\\nb" becomes "a b" rather than "ab"), strips
    remaining non-whitespace control/format characters (Unicode categories
    Cc/Cf — covers zero-width characters and bidi overrides like U+202E),
    and caps length. Applied on the server to every name source:
    client-supplied `diagram_names`, CLI file stems, and names read back
    from stored rows (older rows may hold a raw filename).

    Args:
        name: Candidate name, possibly None/empty/unsafe
        fallback_index: Used to build "diagram-N" when name is unusable

    Returns:
        A sanitized, non-empty name of at most 80 characters
    """
    if not name:
        return f"diagram-{fallback_index}"
    cleaned = re.sub(r'[<>"&]', "", name)
    # Collapse whitespace (incl. \n/\t/\r/\f/\v) to a single space BEFORE
    # stripping other control characters, so a newline becomes a word
    # separator instead of vanishing and gluing words together.
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch) not in ("Cc", "Cf"))
    cleaned = cleaned.strip()
    if not cleaned:
        return f"diagram-{fallback_index}"
    return cleaned[:80]
