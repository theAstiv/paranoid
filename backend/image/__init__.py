"""Image and diagram handling for vision API integration.

This package provides:
- validation.py: File size and format validation
- encoder.py: PNG/JPG → base64 encoding for vision APIs
- mermaid.py: Mermaid .mmd text file loading

Mirrors backend/mcp/ pattern (optional feature, clear boundaries).
"""

from backend.image.encoder import load_image_as_diagram_data
from backend.image.mermaid import load_mermaid_as_diagram_data
from backend.image.validation import (
    MAX_DIAGRAMS,
    sanitize_diagram_name,
    validate_diagram_bytes,
    validate_diagram_file,
    validate_diagram_set,
)


__all__ = [
    "MAX_DIAGRAMS",
    "load_image_as_diagram_data",
    "load_mermaid_as_diagram_data",
    "sanitize_diagram_name",
    "validate_diagram_bytes",
    "validate_diagram_file",
    "validate_diagram_set",
]
