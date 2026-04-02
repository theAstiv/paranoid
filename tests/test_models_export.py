"""Tests for `paranoid models export` (_export_model_async).

Covers the riskiest logic: SARIF reconstruction via model_construct,
MAESTRO skip behaviour, JSON shaping from raw DB rows, and default output paths.
"""

import json
from pathlib import Path

import pytest

from backend.db import crud
from cli.commands.models import _export_model_async


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_stride_model(title: str = "Stride Test") -> str:
    return await crud.create_threat_model(
        title=title,
        description="A test system description",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
        iteration_count=1,
    )


async def _make_maestro_model(title: str = "Maestro Test") -> str:
    return await crud.create_threat_model(
        title=title,
        description="An ML system description",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="MAESTRO",
        iteration_count=1,
    )


async def _add_stride_threat(model_id: str, *, with_dread: bool = False) -> str:
    kwargs = {}
    if with_dread:
        kwargs = {
            "dread_score": 7.5,
            "dread_damage": 8,
            "dread_reproducibility": 7,
            "dread_exploitability": 8,
            "dread_affected_users": 6,
            "dread_discoverability": 7,
        }
    return await crud.create_threat(
        model_id=model_id,
        name="SQL Injection",
        description="An attacker exploits unparameterized queries to read arbitrary data.",
        target="Database",
        impact="Data breach",
        likelihood="High",
        mitigations=["[P] Use parameterized queries", "[D] Enable query logging"],
        stride_category="Tampering",
        iteration_number=1,
        **kwargs,
    )


async def _add_maestro_threat(model_id: str) -> str:
    return await crud.create_threat(
        model_id=model_id,
        name="Prompt Injection",
        description="Attacker overrides system instructions via crafted user input.",
        target="LLM Pipeline",
        impact="Data exfiltration",
        likelihood="Medium",
        mitigations=["[D] Validate and sanitize model outputs"],
        maestro_category="LLM Security",
        iteration_number=1,
    )


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_markdown_export_from_db(test_db, tmp_path: Path) -> None:
    """Markdown export from DB rows produces valid .md with threat content."""
    model_id = await _make_stride_model()
    await _add_stride_threat(model_id, with_dread=True)
    await crud.update_threat_model_status(model_id, "completed")

    out = tmp_path / "report.md"
    await _export_model_async(model_id=model_id, output_format="markdown", output=out)

    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "# Threat Model: Stride Test" in content
    assert "SQL Injection" in content
    assert "Tampering" in content
    assert "[P] Use parameterized queries" in content


@pytest.mark.asyncio
async def test_markdown_export_maestro_threats(test_db, tmp_path: Path) -> None:
    """Markdown export works for MAESTRO models (no stride_category in rows)."""
    model_id = await _make_maestro_model()
    await _add_maestro_threat(model_id)

    out = tmp_path / "maestro.md"
    await _export_model_async(model_id=model_id, output_format="markdown", output=out)

    content = out.read_text(encoding="utf-8")
    assert "Prompt Injection" in content
    assert "LLM Security" in content


# ---------------------------------------------------------------------------
# SARIF export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sarif_export_stride_threats(test_db, tmp_path: Path) -> None:
    """SARIF export from DB rows uses model_construct, writes valid SARIF."""
    model_id = await _make_stride_model()
    await _add_stride_threat(model_id)
    await crud.update_threat_model_status(model_id, "completed")

    out = tmp_path / "findings.sarif"
    await _export_model_async(model_id=model_id, output_format="sarif", output=out)

    assert out.exists()
    sarif = json.loads(out.read_text(encoding="utf-8"))

    assert sarif["version"] == "2.1.0"
    results = sarif["runs"][0]["results"]
    assert len(results) == 1
    assert results[0]["partialFingerprints"]["threatName"] == "SQL Injection"

    # Mitigations flow through as fixes
    fixes = results[0]["fixes"]
    assert len(fixes) == 2
    assert "parameterized queries" in fixes[0]["description"]["text"]


@pytest.mark.asyncio
async def test_sarif_export_maestro_only_model(test_db, tmp_path: Path, capsys) -> None:
    """MAESTRO-only model: SARIF skips all threats and writes a valid empty SARIF."""
    model_id = await _make_maestro_model()
    await _add_maestro_threat(model_id)

    out = tmp_path / "empty.sarif"
    await _export_model_async(model_id=model_id, output_format="sarif", output=out)

    # File still written — valid but empty
    assert out.exists()
    sarif = json.loads(out.read_text(encoding="utf-8"))
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["results"] == []

    # Warning printed to stdout about skipped threats
    captured = capsys.readouterr()
    assert "Skipping" in captured.out
    assert "MAESTRO" in captured.out


@pytest.mark.asyncio
async def test_sarif_export_none_mitigations_does_not_crash(test_db, tmp_path: Path) -> None:
    """SARIF export handles a threat with empty mitigations list without crashing."""
    model_id = await _make_stride_model()
    await crud.create_threat(
        model_id=model_id,
        name="No Mitigations Threat",
        description="Short description of a threat with no mitigations recorded.",
        target="Service",
        impact="Low",
        likelihood="Low",
        mitigations=[],  # empty — crud stores as "[]", list_threats returns []
        stride_category="Repudiation",
    )

    out = tmp_path / "no-mit.sarif"
    await _export_model_async(model_id=model_id, output_format="sarif", output=out)

    sarif = json.loads(out.read_text(encoding="utf-8"))
    results = sarif["runs"][0]["results"]
    assert len(results) == 1
    assert "fixes" not in results[0]  # no fixes key when mitigations is empty


# ---------------------------------------------------------------------------
# Simple JSON export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simple_json_shape(test_db, tmp_path: Path) -> None:
    """Simple JSON export produces expected keys and correct mitigation_count."""
    model_id = await _make_stride_model("JSON Test")
    await _add_stride_threat(model_id, with_dread=True)

    out = tmp_path / "simple.json"
    await _export_model_async(model_id=model_id, output_format="simple", output=out)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["model_id"] == model_id
    assert data["framework"] == "STRIDE"
    assert len(data["threats"]) == 1

    t = data["threats"][0]
    assert t["name"] == "SQL Injection"
    assert t["category"] == "Tampering"
    assert t["dread_score"] == 7.5
    assert t["mitigation_count"] == 2


@pytest.mark.asyncio
async def test_simple_json_none_mitigations(test_db, tmp_path: Path) -> None:
    """Simple JSON: mitigation_count is 0 when mitigations list is empty."""
    model_id = await _make_stride_model()
    await crud.create_threat(
        model_id=model_id,
        name="Bare Threat",
        description="Threat with no mitigations.",
        target="API",
        impact="Low",
        likelihood="Low",
        mitigations=[],
        stride_category="Repudiation",
    )

    out = tmp_path / "bare.json"
    await _export_model_async(model_id=model_id, output_format="simple", output=out)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["threats"][0]["mitigation_count"] == 0


# ---------------------------------------------------------------------------
# Full JSON export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_json_shape(test_db, tmp_path: Path) -> None:
    """Full JSON export contains raw model dict and threats list."""
    model_id = await _make_stride_model("Full JSON Test")
    await _add_stride_threat(model_id)

    out = tmp_path / "full.json"
    await _export_model_async(model_id=model_id, output_format="full", output=out)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert "model" in data
    assert "threats" in data
    assert data["model"]["title"] == "Full JSON Test"
    assert len(data["threats"]) == 1
    # Full format preserves raw mitigations as list
    assert isinstance(data["threats"][0]["mitigations"], list)


# ---------------------------------------------------------------------------
# Default output path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_output_path_markdown(test_db, tmp_path: Path, monkeypatch) -> None:
    """No --output flag: file created as {model_id[:8]}_markdown.md in cwd."""
    monkeypatch.chdir(tmp_path)

    model_id = await _make_stride_model()
    await _add_stride_threat(model_id)

    await _export_model_async(model_id=model_id, output_format="markdown", output=None)

    expected = tmp_path / f"{model_id[:8]}_markdown.md"
    assert expected.exists()
    assert "SQL Injection" in expected.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_default_output_path_sarif(test_db, tmp_path: Path, monkeypatch) -> None:
    """No --output flag: file created as {model_id[:8]}_sarif.sarif in cwd."""
    monkeypatch.chdir(tmp_path)

    model_id = await _make_stride_model()
    await _add_stride_threat(model_id)

    await _export_model_async(model_id=model_id, output_format="sarif", output=None)

    expected = tmp_path / f"{model_id[:8]}_sarif.sarif"
    assert expected.exists()
    sarif = json.loads(expected.read_text(encoding="utf-8"))
    assert sarif["version"] == "2.1.0"


@pytest.mark.asyncio
async def test_output_path_auto_suffix(test_db, tmp_path: Path) -> None:
    """Output path with no extension gets the correct suffix added."""
    model_id = await _make_stride_model()
    await _add_stride_threat(model_id)

    out_no_ext = tmp_path / "report"  # no .md suffix
    await _export_model_async(model_id=model_id, output_format="markdown", output=out_no_ext)

    # _export_model_async adds .md when suffix is absent
    assert (tmp_path / "report.md").exists()
