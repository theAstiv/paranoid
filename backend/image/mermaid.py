"""Mermaid diagram loader (.mmd text files).

Per RULES.md: All file I/O is async. Claude/GPT-4 parse Mermaid syntax natively,
no rendering required for MVP.
"""

from pathlib import Path

import aiofiles

from backend.models.enums import DiagramFormat
from backend.models.extended import DiagramData


async def load_mermaid_as_diagram_data(file_path: Path) -> DiagramData:
    """Load Mermaid .mmd file as text (no rendering).

    Claude Sonnet 4 and GPT-4 understand Mermaid syntax natively. Text-only
    approach keeps dependencies minimal (no Node.js/mermaid-cli required).

    Args:
        file_path: Path to .mmd file

    Returns:
        DiagramData with mermaid_source populated

    Raises:
        OSError: If file cannot be read
        UnicodeDecodeError: If file is not valid UTF-8
    """
    # Read file asynchronously (RULES.md: async for all file I/O)
    async with aiofiles.open(file_path, encoding="utf-8") as f:
        mermaid_source = await f.read()

    # Basic validation: non-empty
    if not mermaid_source.strip():
        raise ValueError(f"Mermaid file is empty: {file_path}")

    return DiagramData(
        format=DiagramFormat.MERMAID,
        source_path=str(file_path),
        mermaid_source=mermaid_source.strip(),
    )
