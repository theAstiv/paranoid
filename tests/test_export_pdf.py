"""Tests for backend/export/pdf.py and _export_model_async PDF format."""

from pathlib import Path

import pytest

from backend.db import crud
from backend.export.pdf import export_pdf
from cli.commands.models import _export_model_async


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STRIDE_FLAT = {
    "name": "SQL Injection",
    "stride_category": "Tampering",
    "maestro_category": None,
    "target": "Database",
    "likelihood": "High",
    "impact": "Data loss",
    "description": "An attacker exploits unparameterized queries to read or modify arbitrary data.",
    "mitigations": [
        "[P] Use parameterized queries",
        "[D] Enable query anomaly logging",
        "[C] Restrict DB user privileges",
    ],
    "dread_score": 7.5,
    "dread_damage": 8,
    "dread_reproducibility": 7,
    "dread_exploitability": 8,
    "dread_affected_users": 6,
    "dread_discoverability": 7,
}

_MAESTRO_NO_DREAD = {
    "name": "Prompt Injection",
    "stride_category": None,
    "maestro_category": "LLM Security",
    "target": "LLM Pipeline",
    "likelihood": "Medium",
    "impact": "Data exfiltration",
    "description": "Attacker crafts adversarial inputs to override system prompt instructions.",
    "mitigations": ["[D] Validate and sanitize model outputs"],
    "dread_score": None,
    "dread_damage": None,
    "dread_reproducibility": None,
    "dread_exploitability": None,
    "dread_affected_users": None,
    "dread_discoverability": None,
}

_NESTED_DREAD = {
    "name": "XSS",
    "stride_category": "Tampering",
    "maestro_category": None,
    "target": "Web Frontend",
    "likelihood": "High",
    "impact": "Session hijacking",
    "description": "An attacker injects malicious scripts into pages viewed by other users.",
    "mitigations": ["[P] Encode all user-supplied output"],
    "dread": {
        "damage": 6,
        "reproducibility": 8,
        "exploitability": 7,
        "affected_users": 5,
        "discoverability": 6,
    },
}


# ---------------------------------------------------------------------------
# Unit tests for export_pdf()
# ---------------------------------------------------------------------------


def test_pdf_returns_bytes_starting_with_pdf_header() -> None:
    """export_pdf() returns PDF bytes (starts with %PDF magic bytes)."""
    result = export_pdf([_STRIDE_FLAT], "test-model-id", "STRIDE", title="Test Model")

    assert isinstance(result, bytes)
    assert result[:4] == b"%PDF"


def test_pdf_non_empty_for_empty_threats() -> None:
    """export_pdf() with empty threat list still produces a valid PDF (not zero bytes)."""
    result = export_pdf([], "test-model-id", "STRIDE", title="Empty Model")

    assert isinstance(result, bytes)
    assert result[:4] == b"%PDF"
    assert len(result) > 500  # any real PDF is at least this large


def test_pdf_with_flat_dread() -> None:
    """export_pdf() completes without error for a threat with flat DREAD fields."""
    result = export_pdf([_STRIDE_FLAT], "test-model-id", "STRIDE", title="DREAD Test")

    assert isinstance(result, bytes)
    assert len(result) > 0


def test_pdf_with_nested_dread() -> None:
    """export_pdf() completes without error for a threat with nested model_dump DREAD."""
    result = export_pdf([_NESTED_DREAD], "test-model-id", "STRIDE")

    assert isinstance(result, bytes)
    assert len(result) > 0


def test_pdf_without_dread() -> None:
    """export_pdf() completes without error when threat has no DREAD data."""
    result = export_pdf([_MAESTRO_NO_DREAD], "test-model-id", "MAESTRO")

    assert isinstance(result, bytes)
    assert len(result) > 0


def test_pdf_with_source_file() -> None:
    """export_pdf() accepts an optional source_file parameter without error."""
    result = export_pdf(
        [_STRIDE_FLAT],
        "test-model-id",
        "STRIDE",
        source_file="/path/to/system.md",
    )

    assert isinstance(result, bytes)
    assert result[:4] == b"%PDF"


def test_pdf_multiple_categories() -> None:
    """export_pdf() groups multiple threats by category without error."""
    spoofing = {**_STRIDE_FLAT, "name": "Token Replay", "stride_category": "Spoofing"}
    result = export_pdf([_STRIDE_FLAT, spoofing], "test-model-id", "STRIDE")

    assert isinstance(result, bytes)
    assert result[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Assets / Flows / Trust Boundaries sections in PDF
# ---------------------------------------------------------------------------

_ASSET = {"name": "User DB", "type": "Asset", "description": "Stores user records"}
_FLOW = {
    "source_entity": "API",
    "target_entity": "DB",
    "flow_type": "data",
    "flow_description": "Reads user records",
}
_BOUNDARY = {"source_entity": "Internet", "target_entity": "DMZ", "purpose": "Perimeter"}


def test_pdf_with_assets_produces_valid_pdf() -> None:
    """export_pdf() renders an Assets table without error when assets provided."""
    result = export_pdf([_STRIDE_FLAT], "mid", "STRIDE", assets=[_ASSET])
    assert isinstance(result, bytes)
    assert result[:4] == b"%PDF"


def test_pdf_with_flows_produces_valid_pdf() -> None:
    """export_pdf() renders a Data Flows table without error when flows provided."""
    result = export_pdf([_STRIDE_FLAT], "mid", "STRIDE", flows=[_FLOW])
    assert isinstance(result, bytes)
    assert result[:4] == b"%PDF"


def test_pdf_with_trust_boundaries_produces_valid_pdf() -> None:
    """export_pdf() renders a Trust Boundaries table without error when boundaries provided."""
    result = export_pdf([_STRIDE_FLAT], "mid", "STRIDE", trust_boundaries=[_BOUNDARY])
    assert isinstance(result, bytes)
    assert result[:4] == b"%PDF"


def test_pdf_with_all_supplementary_sections() -> None:
    """export_pdf() accepts all three supplementary sections together without error."""
    result = export_pdf(
        [_STRIDE_FLAT],
        "mid",
        "STRIDE",
        assets=[_ASSET],
        flows=[_FLOW],
        trust_boundaries=[_BOUNDARY],
    )
    assert isinstance(result, bytes)
    assert result[:4] == b"%PDF"


def test_pdf_empty_supplementary_sections_no_error() -> None:
    """Explicitly passing empty lists for supplementary sections produces valid PDF."""
    result = export_pdf([_STRIDE_FLAT], "mid", "STRIDE", assets=[], flows=[], trust_boundaries=[])
    assert isinstance(result, bytes)
    assert result[:4] == b"%PDF"


def test_pdf_assets_section_adds_content() -> None:
    """A PDF with an Assets section is larger than one without — verifies the table is rendered."""
    pdf_without = export_pdf([_STRIDE_FLAT], "mid", "STRIDE")
    pdf_with = export_pdf([_STRIDE_FLAT], "mid", "STRIDE", assets=[_ASSET])
    assert len(pdf_with) > len(pdf_without)


def test_pdf_flows_section_adds_content() -> None:
    """A PDF with a Data Flows section is larger than one without."""
    pdf_without = export_pdf([_STRIDE_FLAT], "mid", "STRIDE")
    pdf_with = export_pdf([_STRIDE_FLAT], "mid", "STRIDE", flows=[_FLOW])
    assert len(pdf_with) > len(pdf_without)


def test_pdf_trust_boundaries_section_adds_content() -> None:
    """A PDF with a Trust Boundaries section is larger than one without."""
    pdf_without = export_pdf([_STRIDE_FLAT], "mid", "STRIDE")
    pdf_with = export_pdf([_STRIDE_FLAT], "mid", "STRIDE", trust_boundaries=[_BOUNDARY])
    assert len(pdf_with) > len(pdf_without)


def test_pdf_includes_gap_analysis() -> None:
    """Gap summaries produce a non-empty PDF; the section adds bytes vs baseline."""
    pdf_without = export_pdf([_STRIDE_FLAT], "mid", "STRIDE")
    pdf_with = export_pdf(
        [_STRIDE_FLAT],
        "mid",
        "STRIDE",
        gap_summaries=["Missing Information Disclosure on database.", "OAuth flow gap."],
    )
    assert isinstance(pdf_with, bytes)
    assert pdf_with[:4] == b"%PDF"
    assert len(pdf_with) > len(pdf_without)


def test_pdf_gap_analysis_omitted_when_empty() -> None:
    """Empty / None gap_summaries produces same baseline output."""
    pdf_baseline = export_pdf([_STRIDE_FLAT], "mid", "STRIDE")
    pdf_none = export_pdf([_STRIDE_FLAT], "mid", "STRIDE", gap_summaries=None)
    pdf_empty = export_pdf([_STRIDE_FLAT], "mid", "STRIDE", gap_summaries=[])
    # Sizes will be near-identical (PDF metadata varies by timestamp, so allow small delta)
    assert abs(len(pdf_none) - len(pdf_baseline)) < 200
    assert abs(len(pdf_empty) - len(pdf_baseline)) < 200


def test_pdf_realistic_size_is_non_trivial() -> None:
    """A realistic 3-threat PDF with long fields and gaps is well over the 'blank PDF' floor.

    Catches regressions where rendering silently drops content (e.g. paragraph
    escaping breaks and reportlab outputs only the header).
    """
    threats = [
        {**_STRIDE_FLAT, "name": "SQL Injection via Unparameterized Query on /search endpoint"},
        {
            **_STRIDE_FLAT,
            "name": "CSRF token reuse across privilege escalation",
            "stride_category": "Spoofing",
        },
        {
            **_STRIDE_FLAT,
            "name": "Verbose error reveals stack trace",
            "stride_category": "Information Disclosure",
        },
    ]
    pdf = export_pdf(
        threats=threats,
        model_id="realistic-mid",
        framework="STRIDE",
        title="Realistic Demo",
        gap_summaries=[
            "First iteration covered Tampering. Spoofing on admin paths was not examined.",
            "Second iteration filled in Spoofing. Elevation of Privilege remains uncovered.",
        ],
    )
    assert pdf[:4] == b"%PDF"
    # 4 KB is the empirically observed floor for a 3-threat + gap-section PDF.
    # A blank-page bug typically produces a < 2 KB output.
    assert len(pdf) > 4_000
    # And it spans more than one page (Pages /Count 2 in the trailer).
    assert b"/Count 2" in pdf or b"/Count 3" in pdf


# ---------------------------------------------------------------------------
# Integration test: _export_model_async PDF format
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_model_async_pdf_writes_file(test_db, tmp_path: Path) -> None:
    """_export_model_async with pdf format writes a valid PDF to disk."""
    model_id = await crud.create_threat_model(
        title="PDF Export Test",
        description="A system description.",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
        iteration_count=1,
    )
    await crud.create_threat(
        model_id=model_id,
        name="SQL Injection",
        description="An attacker exploits unparameterized queries to read arbitrary data.",
        target="Database",
        impact="Data breach",
        likelihood="High",
        mitigations=["[P] Use parameterized queries"],
        stride_category="Tampering",
        dread_score=7.5,
        dread_damage=8,
        dread_reproducibility=7,
        dread_exploitability=8,
        dread_affected_users=6,
        dread_discoverability=7,
    )

    out = tmp_path / "report.pdf"
    await _export_model_async(model_id=model_id, output_format="pdf", output=out)

    assert out.exists()
    content = out.read_bytes()
    assert content[:4] == b"%PDF"
    assert len(content) > 500


@pytest.mark.asyncio
async def test_export_model_async_pdf_auto_suffix(test_db, tmp_path: Path) -> None:
    """Output path with no extension gets .pdf suffix added."""
    model_id = await crud.create_threat_model(
        title="Auto Suffix Test",
        description="desc",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
        iteration_count=1,
    )

    out_no_ext = tmp_path / "report"
    await _export_model_async(model_id=model_id, output_format="pdf", output=out_no_ext)

    assert (tmp_path / "report.pdf").exists()


@pytest.mark.asyncio
async def test_export_model_async_pdf_default_path(test_db, tmp_path: Path, monkeypatch) -> None:
    """No --output flag: file created as {model_id[:8]}_pdf.pdf in cwd."""
    monkeypatch.chdir(tmp_path)

    model_id = await crud.create_threat_model(
        title="Default Path Test",
        description="desc",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
        iteration_count=1,
    )

    await _export_model_async(model_id=model_id, output_format="pdf", output=None)

    expected = tmp_path / f"{model_id[:8]}_pdf.pdf"
    assert expected.exists()
    assert expected.read_bytes()[:4] == b"%PDF"
