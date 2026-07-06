"""Shared constants for PDF and Markdown export modules."""

# Mermaid diagram type prefixes used to distinguish diagram source from prose.
# Both pdf.py and markdown.py use this tuple — keep it here to avoid drift.
MERMAID_DIAGRAM_PREFIXES = (
    "graph ",
    "flowchart ",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "erDiagram",
    "gantt",
    "pie ",
    "mindmap",
    "journey",
)
