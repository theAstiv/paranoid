"""Diagrams in every export, and CLI export parity with the route (Phase 2 B1, BB-69)."""

import base64
import io
import json
import re

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image as PILImage
from pypdf import PdfReader

from backend.db import crud
from backend.export.markdown import export_markdown
from backend.export.pdf import export_pdf
from backend.main import app
from cli.commands.models import _export_model_async


def _png_base64(width: int = 40, height: int = 20) -> str:
    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), (200, 30, 30)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


MERMAID = "graph TD\n  Browser --> API\n  API --> DB"
DIAGRAMS = [
    {"name": "Architecture", "kind": "mermaid", "content": MERMAID},
    {"name": "Network [v2]", "kind": "png", "content": _png_base64()},
]
ASSETS = [{"name": "API", "type": "Asset", "description": "REST"}]
FLOWS = [{"source_entity": "Browser", "target_entity": "API", "flow_description": "HTTPS"}]


def _pdf_text(pdf: bytes) -> str:
    return " ".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def _pdf_image_count(pdf: bytes) -> int:
    return sum(len(page.images) for page in PdfReader(io.BytesIO(pdf)).pages)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def test_markdown_includes_uploaded_diagrams_and_the_context_diagram():
    md = export_markdown([], "m1", "STRIDE", diagrams=DIAGRAMS, assets=ASSETS, flows=FLOWS)

    assert "## Diagrams" in md
    assert f"### Architecture\n\n```mermaid\n{MERMAID}\n```" in md
    # Brackets in the name would end the alt text early.
    assert "![Network (v2)](data:image/png;base64," in md
    assert "### Context diagram (generated)" in md
    assert '```mermaid\nflowchart LR\n    n1["API"]' in md
    # Before the tables it is drawn from.
    assert md.index("## Diagrams") < md.index("## Assets")


def test_markdown_has_no_diagram_section_without_diagrams_or_context():
    assert "## Diagrams" not in export_markdown([], "m1", "STRIDE")


def test_markdown_rejects_an_image_that_is_not_base64():
    """A stored value must not close the data URI and add markup."""
    bad = [{"name": "x", "kind": "png", "content": "AAAA)<img src=x onerror=alert(1)>"}]
    md = export_markdown([], "m1", "STRIDE", diagrams=bad)
    assert "This image could not be included" in md
    assert "<img" not in md
    assert "data:image" not in md


def test_markdown_takes_the_media_type_from_the_kind():
    md = export_markdown(
        [],
        "m1",
        "STRIDE",
        diagrams=[{"name": "j", "kind": "jpeg", "content": "QUJD", "media_type": "text/html"}],
    )
    assert "(data:image/jpeg;base64,QUJD)" in md
    assert "text/html" not in md


def test_markdown_fence_outlasts_backticks_in_the_diagram():
    source = "graph TD\n  A[```] --> B"
    md = export_markdown(
        [], "m1", "STRIDE", diagrams=[{"name": "t", "kind": "mermaid", "content": source}]
    )
    assert f"````mermaid\n{source}\n````" in md


def test_markdown_escapes_a_diagram_name():
    md = export_markdown(
        [], "m1", "STRIDE", diagrams=[{"name": "<b>x</b>", "kind": "mermaid", "content": MERMAID}]
    )
    assert "### &lt;b&gt;x&lt;/b&gt;" in md


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def test_pdf_embeds_images_and_shows_mermaid_as_text():
    pdf = export_pdf([], "m1", "STRIDE", diagrams=DIAGRAMS, assets=ASSETS, flows=FLOWS)

    assert _pdf_image_count(pdf) == 1
    text = _pdf_text(pdf)
    assert "Architecture (Mermaid)" in text
    assert "Browser --> API" in text
    assert "Context diagram (generated, Mermaid)" in text
    assert "flowchart LR" in text


def test_pdf_scales_a_large_image_to_fit_and_keeps_its_shape():
    from backend.export.pdf import _MAX_IMAGE_HEIGHT, _image_flowable

    wide = _image_flowable(_png_base64(4000, 100), max_width=450)
    assert wide.drawWidth == pytest.approx(450)
    assert wide.drawHeight == pytest.approx(450 * 100 / 4000)

    tall = _image_flowable(_png_base64(100, 4000), max_width=450)
    assert tall.drawHeight == pytest.approx(_MAX_IMAGE_HEIGHT)
    assert tall.drawWidth == pytest.approx(_MAX_IMAGE_HEIGHT * 100 / 4000)

    small = _image_flowable(_png_base64(40, 20), max_width=450)
    assert (small.drawWidth, small.drawHeight) == (40, 20)  # never enlarged

    # And the wide one still embeds at full resolution, drawn smaller.
    pdf = export_pdf(
        [],
        "m1",
        "STRIDE",
        diagrams=[{"name": "w", "kind": "png", "content": _png_base64(4000, 100)}],
    )
    assert PdfReader(io.BytesIO(pdf)).pages[0].images[0].image.size == (4000, 100)


def test_pdf_survives_an_unreadable_image():
    bad = [{"name": "broken", "kind": "png", "content": base64.b64encode(b"not a png").decode()}]
    pdf = export_pdf([], "m1", "STRIDE", diagrams=bad)
    assert pdf[:4] == b"%PDF"
    assert _pdf_image_count(pdf) == 0
    assert "This image could not be included" in _pdf_text(pdf)


def test_pdf_escapes_markup_in_a_diagram_name():
    """reportlab's <img> tag fetches what it names (the SSRF the title escape fixed)."""
    name = '<img src="http://169.254.169.254/x"/>'
    pdf = export_pdf(
        [], "m1", "STRIDE", diagrams=[{"name": name, "kind": "mermaid", "content": MERMAID}]
    )
    assert '<img src="http://169.254.169.254/x"/> (Mermaid)' in _pdf_text(pdf)


# ---------------------------------------------------------------------------
# The route and the CLI over one seeded model
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def seeded(test_db) -> str:
    model_id = await crud.create_threat_model(
        title="Exports",
        description="A browser talks to an API.",
        provider="anthropic",
        model="claude-sonnet-4",
    )
    threat_id = await crud.create_threat(
        model_id=model_id,
        name="Token theft",
        description="Stolen session token.",
        target="API",
        impact="High",
        likelihood="Medium",
        mitigations=["[P] Short-lived tokens"],
        stride_category="Spoofing",
    )
    await crud.create_attack_tree(threat_id, "graph TD\n  Goal --> Steal")
    await crud.create_test_case(threat_id, "Feature: tokens\n  Scenario: expiry")
    await crud.create_asset(model_id, "Asset", "API", "REST service")
    await crud.create_flow(model_id, "data", "HTTPS", "Browser", "API")
    await crud.create_trust_boundary(model_id, "Internet edge", "Browser", "API")
    await crud.create_dependency_scan(model_id, "left-pad", "1.3.0", "npm", {"evidence": []})
    await crud.replace_model_diagrams(
        model_id,
        [
            {
                "name": "Architecture",
                "kind": "mermaid",
                "content": MERMAID,
                "size_bytes": len(MERMAID),
            },
            {
                "name": "Network",
                "kind": "png",
                "content": _png_base64(),
                "size_bytes": 100,
                "media_type": "image/png",
            },
        ],
    )
    return model_id


def _without_timestamp(md: str) -> str:
    return re.sub(r"\*\*Generated:\*\* [^\n]*", "", md)


@pytest.mark.asyncio
async def test_the_route_markdown_has_everything(client, seeded):
    md = (await client.get(f"/api/export/{seeded}?format=markdown")).text
    for expected in (
        "## Diagrams",
        "### Architecture",
        "data:image/png;base64,",
        "### Context diagram (generated)",
        "## Assets",
        "## Data Flows",
        "## Trust Boundaries",
        "## Dependency Findings",
        "**Attack Tree:**",
        "**Test Cases:**",
    ):
        assert expected in md, expected


@pytest.mark.asyncio
async def test_cli_markdown_matches_the_route(client, seeded, tmp_path):
    """The CLI used to drop the context, enrichment, dependencies and diagrams."""
    route_md = (await client.get(f"/api/export/{seeded}?format=markdown")).text
    out = tmp_path / "report.md"

    await _export_model_async(model_id=seeded, output_format="markdown", output=out)

    assert _without_timestamp(out.read_text(encoding="utf-8")) == _without_timestamp(route_md)


@pytest.mark.asyncio
async def test_cli_pdf_has_what_the_route_pdf_has(client, seeded, tmp_path):
    route_pdf = (await client.get(f"/api/export/{seeded}?format=pdf")).content
    out = tmp_path / "report.pdf"

    await _export_model_async(model_id=seeded, output_format="pdf", output=out)

    cli_pdf = out.read_bytes()
    assert _pdf_image_count(cli_pdf) == _pdf_image_count(route_pdf) == 1
    cli_text = _pdf_text(cli_pdf)
    for expected in (
        "Architecture (Mermaid)",
        "Trust Boundaries",
        "Dependency Findings",
        "Goal --> Steal",
    ):
        assert expected in cli_text, expected


@pytest.mark.asyncio
async def test_json_export_carries_the_diagrams(client, seeded):
    data = (await client.get(f"/api/export/{seeded}?format=json")).json()

    assert [d["name"] for d in data["diagrams"]] == ["Architecture", "Network"]
    assert data["diagrams"][0]["content"] == MERMAID
    assert data["diagrams"][1]["kind"] == "png"
    assert data["context_diagram"].startswith("flowchart LR\n")


@pytest.mark.asyncio
async def test_json_export_without_context_has_no_context_diagram(client, test_db):
    model_id = await crud.create_threat_model(
        title="Empty", description="x", provider="anthropic", model="claude-sonnet-4"
    )
    data = (await client.get(f"/api/export/{model_id}?format=json")).json()
    assert data["diagrams"] == []
    assert data["context_diagram"] is None


# ---------------------------------------------------------------------------
# SARIF --manifest-path
# ---------------------------------------------------------------------------


async def _dependency_threat_model() -> str:
    model_id = await crud.create_threat_model(
        title="Deps", description="x", provider="anthropic", model="claude-sonnet-4"
    )
    await crud.create_threat(
        model_id=model_id,
        name="Install script runs code",
        description="A postinstall hook.",
        target="left-pad",
        impact="High",
        likelihood="Medium",
        mitigations=["Pin"],
        stride_category="Tampering",
        source="dependency",
        dependency_ref={"package": "left-pad", "version": "1.3.0", "file": "install.js", "line": 3},
    )
    return model_id


def _dependency_uris(sarif: dict) -> set[str]:
    results = sarif["runs"][0]["results"]
    return {
        loc["physicalLocation"]["artifactLocation"]["uri"]
        for r in results
        for loc in r.get("locations", [])
    }


@pytest.mark.asyncio
async def test_sarif_anchors_dependency_findings_to_the_manifest_path(test_db, tmp_path):
    model_id = await _dependency_threat_model()
    out = tmp_path / "f.sarif"

    await _export_model_async(
        model_id=model_id, output_format="sarif", output=out, manifest_path="web/package.json"
    )

    assert _dependency_uris(json.loads(out.read_text(encoding="utf-8"))) == {"web/package.json"}


@pytest.mark.asyncio
async def test_sarif_manifest_path_defaults_to_package_json(test_db, tmp_path):
    model_id = await _dependency_threat_model()
    out = tmp_path / "f.sarif"

    await _export_model_async(model_id=model_id, output_format="sarif", output=out)

    assert _dependency_uris(json.loads(out.read_text(encoding="utf-8"))) == {"package.json"}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["../package.json", "/etc/package.json", "https://x/package.json"])
async def test_sarif_rejects_an_unsafe_manifest_path(test_db, tmp_path, bad):
    from cli.errors import CLIError

    model_id = await _dependency_threat_model()
    with pytest.raises(CLIError, match="--manifest-path"):
        await _export_model_async(
            model_id=model_id, output_format="sarif", output=tmp_path / "f.sarif", manifest_path=bad
        )


# ---------------------------------------------------------------------------
# `run`'s own Markdown/PDF
# ---------------------------------------------------------------------------


def test_run_reports_get_the_context_dependencies_and_diagrams():
    from pathlib import Path

    from backend.models.enums import DiagramFormat, Framework
    from backend.models.extended import DiagramData
    from backend.models.state import Asset, AssetsList, DataFlow, FlowsList, TrustBoundary
    from cli.commands.run import _report_context
    from cli.output.json_writer import JSONWriter

    writer = JSONWriter(model_id="m", input_file=Path("d.md"), framework=Framework.STRIDE)
    writer.assets = AssetsList(assets=[Asset(type="Asset", name="API", description="REST")])
    writer.flows = FlowsList(
        data_flows=[
            DataFlow(flow_description="HTTPS", source_entity="Browser", target_entity="API")
        ],
        trust_boundaries=[
            TrustBoundary(purpose="Edge", source_entity="Browser", target_entity="API")
        ],
        threat_sources=[],
    )
    diagram = DiagramData(
        format=DiagramFormat.MERMAID, source_path="a.mmd", mermaid_source=MERMAID, name="a"
    )

    context = _report_context(writer, [diagram])

    assert context["assets"][0]["name"] == "API"
    assert context["flows"][0]["source_entity"] == "Browser"
    assert context["trust_boundaries"][0]["purpose"] == "Edge"
    assert context["diagrams"][0]["kind"] == "mermaid"
    assert context["dependency_scans"] is None
    md = export_markdown([], "m", "STRIDE", **context)
    assert "### a" in md
    assert "### Context diagram (generated)" in md
    assert "## Trust Boundaries" in md


@pytest.mark.asyncio
@pytest.mark.parametrize("output_format", ["markdown", "pdf"])
async def test_run_writes_the_context_and_diagrams_into_its_report(
    tmp_path, monkeypatch, output_format
):
    """The wiring, not only the helper: `run -o` passes them to the exporter."""
    from backend.config import Settings
    from backend.models.api import (
        AnalyzeAssumptionsResponse,
        AnalyzeBundleResponse,
        AnalyzeDescriptionResponse,
    )
    from backend.models.enums import Framework
    from backend.pipeline.runner import PipelineEvent, PipelineStep
    from cli.commands import run as run_mod
    from tests.fixtures.pipeline import make_assets, make_flows, make_stride_threats

    assets, flows = make_assets(), make_flows()
    events = [
        PipelineEvent(PipelineStep.EXTRACT_ASSETS, "completed", "", data={"assets": assets}),
        PipelineEvent(PipelineStep.EXTRACT_FLOWS, "completed", "", data={"flows": flows}),
        PipelineEvent(
            PipelineStep.COMPLETE, "completed", "", data={"threats": make_stride_threats()}
        ),
    ]

    async def fake_pipeline(**_kwargs):
        for event in events:
            yield event

    async def fake_pre_flight(*_args):
        bundle = AnalyzeBundleResponse(
            description=AnalyzeDescriptionResponse(gaps=[], is_sufficient=True),
            assumptions=AnalyzeAssumptionsResponse(gaps=[], is_sufficient=True),
        )
        return bundle, None

    async def no_persist(**_kwargs):
        return None

    monkeypatch.setattr(run_mod, "run_pipeline_for_model", fake_pipeline)
    monkeypatch.setattr(run_mod, "_run_pre_flight", fake_pre_flight)
    monkeypatch.setattr("backend.db.persist.persist_pipeline_result", no_persist)

    diagram = tmp_path / "arch.mmd"
    diagram.write_text(MERMAID, encoding="utf-8")
    out = tmp_path / ("report.md" if output_format == "markdown" else "report.pdf")
    input_file = tmp_path / "system.md"

    await run_mod._run_pipeline_inside_provider(
        model_id="m",
        description="A system.",
        assumptions=None,
        framework=Framework.STRIDE,
        has_ai_components=False,
        settings=Settings(default_provider="anthropic", default_model="m", anthropic_api_key="k"),
        provider=None,
        fast_provider=None,
        renderer=None,
        input_file=input_file,
        output_path=out,
        output_format=output_format,
        quiet=True,
        code_path=None,
        diagram_paths=(diagram,),
        content="A system.",
        strict=False,
    )

    first_asset = assets.assets[0].name
    text = (
        out.read_text(encoding="utf-8")
        if output_format == "markdown"
        else _pdf_text(out.read_bytes())
    )
    for expected in ("Browser --> API", "Trust Boundaries", first_asset):
        assert expected in text, expected
    assert (
        "### Context diagram (generated)"
        if output_format == "markdown"
        else "Context diagram (generated, Mermaid)"
    ) in text
