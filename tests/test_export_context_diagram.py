"""The context diagram generated for exports (Phase 2 B1, BB-69)."""

from itertools import permutations

from backend.export._common import mermaid_label
from backend.export.context_diagram import context_to_mermaid


ASSETS = [
    {"id": "a-db", "name": "User DB", "type": "Asset", "description": "Postgres"},
    {"id": "a-api", "name": "API", "type": "Asset", "description": "REST"},
    {"id": "a-user", "name": "Customer", "type": "Entity", "description": "A browser"},
]
FLOWS = [
    {"source_entity": "Customer", "target_entity": "API", "flow_description": "Logs in over HTTPS"},
    {
        "source_entity": "api",  # different case, same asset
        "target_entity": "Users",  # renamed since; the link wins
        "target_asset_id": "a-db",
        "flow_description": "Reads profiles",
    },
    {"source_entity": "API", "target_entity": "Stripe", "flow_description": "Charges cards"},
]
BOUNDARIES = [
    {"source_entity": "Customer", "target_entity": "API", "purpose": "Internet edge"},
    {
        "source_entity": "API",
        "target_entity": "Customer",
        "purpose": "Internet edge",
    },  # same crossing
]

GOLDEN = """flowchart LR
    n1["API"]
    n2(["Customer"])
    n3["Stripe"]
    n4["User DB"]
    n1 -->|"Charges cards"| n3
    n1 -->|"Reads profiles"| n4
    n2 -->|"Logs in over HTTPS"| n1
    n1 -.-|"Internet edge"| n2
    linkStyle 3 stroke:#d97706,stroke-width:2px,stroke-dasharray:5 4
"""


def test_the_generated_diagram_matches_the_snapshot():
    assert context_to_mermaid(ASSETS, FLOWS, BOUNDARIES) == GOLDEN


def test_input_order_does_not_change_the_output():
    """Stable text, so two exports of one model diff cleanly."""
    for assets, flows, boundaries in zip(
        permutations(ASSETS), permutations(FLOWS), [BOUNDARIES, BOUNDARIES[::-1]] * 3, strict=True
    ):
        assert context_to_mermaid(list(assets), list(flows), boundaries) == GOLDEN


def test_an_empty_context_gives_no_diagram():
    assert context_to_mermaid(None, None, None) == ""
    assert context_to_mermaid([], [], []) == ""
    assert context_to_mermaid([{"name": "   ", "type": "Asset"}], [], []) == ""


def test_flow_endpoints_with_no_asset_become_nodes():
    out = context_to_mermaid([], [{"source_entity": "A", "target_entity": "B"}], [])
    assert out == 'flowchart LR\n    n1["A"]\n    n2["B"]\n    n1 --> n2\n'


def test_no_link_style_without_boundaries():
    assert "linkStyle" not in context_to_mermaid(ASSETS, FLOWS, [])


def test_a_hostile_name_cannot_break_out_of_its_label():
    """LLM- or user-written names reach the diagram; one must not add nodes or links."""
    hostile = 'DB"] --> evil["pwn'
    out = context_to_mermaid(
        [{"name": hostile, "type": "Asset"}],
        [{"source_entity": hostile, "target_entity": "X", "flow_description": 'a|"b"<img>'}],
        [],
    )
    lines = out.splitlines()
    assert lines[1] == '    n1["DB#34;] --#62; evil[#34;pwn"]'
    assert lines[3] == '    n1 -->|"a#124;#34;b#34;#60;img#62;"| n2'
    assert len(lines) == 4  # header, two nodes, one link: nothing injected
    for line in lines[1:]:
        # Only the label delimiters themselves are raw quotes.
        assert line.count('"') == 2


def test_mermaid_label_escapes_collapses_and_truncates():
    assert mermaid_label('a "b"\n<c>|`d` #1') == "a #34;b#34; #60;c#62;#124;#96;d#96; #35;1"
    assert mermaid_label("x" * 100, max_length=10) == "xxxxxxxxx…"
    # "#" is escaped first, so an escape never gets escaped again.
    assert mermaid_label("#34;") == "#35;34;"
