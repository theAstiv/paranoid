"""Image and diagram handling for vision API integration.

This package provides:
- validation.py: File size and format validation
- encoder.py: PNG/JPG → base64 encoding for vision APIs
- mermaid.py: Mermaid .mmd text file loading

Mirrors backend/mcp/ pattern (optional feature, clear boundaries).
"""

from backend.image.encoder import load_image_as_diagram_data
from backend.image.mermaid import load_mermaid_as_diagram_data
from backend.image.validation import validate_diagram_file


__all__ = [
    "load_image_as_diagram_data",
    "load_mermaid_as_diagram_data",
    "validate_diagram_file",
]
