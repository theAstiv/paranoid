"""Pipeline nodes — plain async functions for threat modeling.

Public API re-exports from submodules for backward compatibility.
Import directly from this package:

    from backend.pipeline.nodes import summarize, extract_assets, generate_threats

Internal module organization:
    - helpers: Shared formatting/parsing utilities (private)
    - summary: System and code summarization
    - extraction: Asset and flow extraction
    - threats: Threat generation and gap analysis
    - enrichment: Attack trees and test cases
"""

# Summary nodes
# Enrichment nodes
from backend.pipeline.nodes.enrichment import generate_attack_tree, generate_test_cases

# Extraction nodes
from backend.pipeline.nodes.extraction import extract_assets, extract_flows
from backend.pipeline.nodes.summary import summarize, summarize_code

# Threat nodes
from backend.pipeline.nodes.threats import gap_analysis, generate_threats


__all__ = [
    # Summary
    "summarize",
    "summarize_code",
    # Extraction
    "extract_assets",
    "extract_flows",
    # Threats
    "generate_threats",
    "gap_analysis",
    # Enrichment
    "generate_attack_tree",
    "generate_test_cases",
]
