"""Tests for backend/export/markdown.py."""

from backend.export.markdown import export_markdown


# Reusable threat fixtures

_STRIDE_THREAT_FLAT = {
    "name": "SQL Injection",
    "stride_category": "Tampering",
    "maestro_category": None,
    "target": "Database",
    "likelihood": "High",
    "impact": "Data loss and corruption",
    "description": "An attacker exploits unparameterized queries to read or modify arbitrary data.",
    "mitigations": [
        "[P] Use parameterized queries / prepared statements",
        "[D] Enable database query anomaly logging",
        "[C] Restrict DB user to minimum required privileges",
    ],
    # Flat DREAD shape (DB row)
    "dread_score": 7.5,
    "dread_damage": 8,
    "dread_reproducibility": 7,
    "dread_exploitability": 8,
    "dread_affected_users": 6,
    "dread_discoverability": 7,
}

_MAESTRO_THREAT_NO_DREAD = {
    "name": "Prompt Injection",
    "stride_category": None,
    "maestro_category": "LLM Security",
    "target": "LLM Pipeline",
    "likelihood": "Medium",
    "impact": "Data exfiltration via crafted prompts",
    "description": "An attacker crafts adversarial inputs to override system prompt instructions.",
    "mitigations": ["[D] Validate and sanitize model outputs before returning to caller"],
    # No DREAD data at all
    "dread_score": None,
    "dread_damage": None,
    "dread_reproducibility": None,
    "dread_exploitability": None,
    "dread_affected_users": None,
    "dread_discoverability": None,
}

_STRIDE_THREAT_NESTED_DREAD = {
    "name": "Cross-Site Scripting",
    "stride_category": "Tampering",
    "maestro_category": None,
    "target": "Web Frontend",
    "likelihood": "High",
    "impact": "Session hijacking",
    "description": "An attacker injects malicious scripts into pages viewed by other users.",
    "mitigations": ["[P] Encode all user-supplied output"],
    # Nested model_dump shape — no "score" key (it's a @property, not a field)
    "dread": {
        "damage": 6,
        "reproducibility": 8,
        "exploitability": 7,
        "affected_users": 5,
        "discoverability": 6,
    },
}


def test_stride_with_dread_flat() -> None:
    """STRIDE threat with flat DB-row DREAD fields renders correctly."""
    md = export_markdown([_STRIDE_THREAT_FLAT], "test-model-id", "STRIDE", title="Test Model")

    assert "# Threat Model: Test Model" in md
    assert "STRIDE" in md
    assert "test-mo" in md  # model_id[:8] in header

    # Summary table
    assert "SQL Injection" in md
    assert "Tampering" in md
    assert "**7.5**" in md  # DREAD score cell

    # Detail section
    assert "D:8" in md
    assert "R:7" in md
    assert "E:8" in md
    assert "A:6" in md
    assert "Di:7" in md
    assert "7.5/10" in md

    # Mitigations with parsed labels
    assert "[P] Use parameterized queries" in md
    assert "[D] Enable database query anomaly logging" in md
    assert "[C] Restrict DB user" in md


def test_maestro_without_dread() -> None:
    """MAESTRO threat with no DREAD data omits DREAD section entirely."""
    md = export_markdown([_MAESTRO_THREAT_NO_DREAD], "test-model-id", "MAESTRO")

    assert "LLM Security" in md
    assert "Prompt Injection" in md
    assert "Medium" in md

    # No DREAD detail line in threat body
    assert "**DREAD:**" not in md
    assert "—" in md  # DREAD column in summary table shows dash


def test_empty_threats() -> None:
    """Empty threat list renders header and a 'no threats' message."""
    md = export_markdown([], "test-model-id", "STRIDE", title="Empty Model")

    assert "# Threat Model: Empty Model" in md
    assert "No threats recorded" in md
    # Summary table header is still present
    assert "| # | Threat |" in md


def test_include_header_false() -> None:
    """include_header=False omits the H1 title and metadata block."""
    md = export_markdown(
        [_STRIDE_THREAT_FLAT],
        "test-model-id",
        "STRIDE",
        title="Should Not Appear",
        include_header=False,
    )

    assert "# Threat Model:" not in md
    assert "Should Not Appear" not in md
    # Content sections are still present
    assert "## Summary" in md
    assert "SQL Injection" in md


def test_dread_nested_model_dump() -> None:
    """Nested model_dump DREAD dict computes score correctly (sum/5, no score key)."""
    md = export_markdown([_STRIDE_THREAT_NESTED_DREAD], "test-model-id", "STRIDE")

    # Score: (6+8+7+5+6)/5 = 32/5 = 6.4
    assert "6.4" in md
    assert "D:6" in md
    assert "R:8" in md
    assert "E:7" in md
    assert "A:5" in md
    assert "Di:6" in md


def test_source_file_shown_when_provided() -> None:
    """Source file path appears in header when provided."""
    md = export_markdown(
        [_STRIDE_THREAT_FLAT],
        "test-model-id",
        "STRIDE",
        source_file="/path/to/system.md",
    )
    assert "/path/to/system.md" in md


def test_source_file_omitted_when_not_provided() -> None:
    """Source file line is absent when source_file is None."""
    md = export_markdown([_STRIDE_THREAT_FLAT], "test-model-id", "STRIDE")
    assert "**Source:**" not in md


def test_threats_grouped_by_category() -> None:
    """Multiple threats are grouped under their respective category headings."""
    spoofing = {**_STRIDE_THREAT_FLAT, "name": "Token Replay", "stride_category": "Spoofing"}
    tampering = {**_STRIDE_THREAT_FLAT, "name": "SQL Injection", "stride_category": "Tampering"}

    md = export_markdown([spoofing, tampering], "test-model-id", "STRIDE")

    assert "### Spoofing" in md
    assert "### Tampering" in md
    # Spoofing section appears before Tampering (first-seen order)
    assert md.index("### Spoofing") < md.index("### Tampering")


def test_untagged_mitigations_render_without_label() -> None:
    """Mitigations without [P]/[D]/[C] tags render as plain list items."""
    threat = {**_STRIDE_THREAT_FLAT, "mitigations": ["Apply input validation"]}
    md = export_markdown([threat], "test-model-id", "STRIDE")

    assert "- Apply input validation" in md
    assert "[M]" not in md  # no spurious tag


# ---------------------------------------------------------------------------
# Assets / Flows / Trust Boundaries sections
# ---------------------------------------------------------------------------

_ASSET = {"name": "User DB", "type": "Asset", "description": "Stores user records"}
_FLOW = {
    "source_entity": "API",
    "target_entity": "DB",
    "flow_type": "data",
    "flow_description": "Reads user records",
}
_BOUNDARY = {"source_entity": "Internet", "target_entity": "DMZ", "purpose": "Perimeter"}


def test_assets_section_renders_table() -> None:
    """Assets list produces a Markdown table with name/type/description columns."""
    md = export_markdown(
        [_STRIDE_THREAT_FLAT], "mid", "STRIDE", assets=[_ASSET]
    )
    assert "## Assets" in md
    assert "| Name |" in md
    assert "User DB" in md
    assert "Asset" in md
    assert "Stores user records" in md


def test_assets_section_absent_when_empty() -> None:
    """No assets → no Assets section in output."""
    md = export_markdown([_STRIDE_THREAT_FLAT], "mid", "STRIDE", assets=[])
    assert "## Assets" not in md


def test_flows_section_renders_table() -> None:
    """Data flows list produces a Markdown table with source/target/type/description columns."""
    md = export_markdown(
        [_STRIDE_THREAT_FLAT], "mid", "STRIDE", flows=[_FLOW]
    )
    assert "## Data Flows" in md
    assert "| Source |" in md
    assert "Reads user records" in md
    assert "| data |" in md


def test_flows_section_absent_when_empty() -> None:
    md = export_markdown([_STRIDE_THREAT_FLAT], "mid", "STRIDE", flows=[])
    assert "## Data Flows" not in md


def test_markdown_pipe_characters_escaped_in_cells() -> None:
    """Pipe chars in field values are escaped so they don't break the Markdown table."""
    flow_with_pipe = {
        "source_entity": "User | Database",
        "target_entity": "API",
        "flow_type": "data",
        "flow_description": "Multi-step | operation",
    }
    md = export_markdown([_STRIDE_THREAT_FLAT], "mid", "STRIDE", flows=[flow_with_pipe])
    assert "User \\| Database" in md
    assert "Multi-step \\| operation" in md


def test_trust_boundaries_section_renders_table() -> None:
    """Trust boundaries list produces a Markdown table with source/target/purpose columns."""
    md = export_markdown(
        [_STRIDE_THREAT_FLAT], "mid", "STRIDE", trust_boundaries=[_BOUNDARY]
    )
    assert "## Trust Boundaries" in md
    assert "| Source |" in md
    assert "Perimeter" in md
    assert "Internet" in md
    assert "DMZ" in md


def test_trust_boundaries_section_absent_when_empty() -> None:
    md = export_markdown([_STRIDE_THREAT_FLAT], "mid", "STRIDE", trust_boundaries=[])
    assert "## Trust Boundaries" not in md


def test_all_sections_appear_before_summary() -> None:
    """Assets / Flows / Trust Boundaries sections come before the Summary table."""
    md = export_markdown(
        [_STRIDE_THREAT_FLAT],
        "mid",
        "STRIDE",
        assets=[_ASSET],
        flows=[_FLOW],
        trust_boundaries=[_BOUNDARY],
    )
    assets_pos = md.index("## Assets")
    flows_pos = md.index("## Data Flows")
    tb_pos = md.index("## Trust Boundaries")
    summary_pos = md.index("## Summary")
    assert assets_pos < summary_pos
    assert flows_pos < summary_pos
    assert tb_pos < summary_pos
