"""Tests for GET /api/export/{model_id}.

Covers all four export formats and edge cases (404, empty threats, status filter).
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from backend.db import crud
from backend.main import app


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def model_with_threats(test_db):
    """Saved model with one STRIDE threat and one MAESTRO-only threat."""
    model_id = await crud.create_threat_model(
        title="Payment API",
        description="Stripe-backed payment processor with PCI-DSS scope",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
    )

    await crud.create_threat(
        model_id=model_id,
        name="SQL Injection",
        description=(
            "Attacker injects malicious SQL into payment query parameters "
            "to exfiltrate cardholder data from the payments database table"
        ),
        target="Database",
        impact="Critical",
        likelihood="High",
        mitigations=["Parameterized queries", "Input validation", "WAF rules"],
        stride_category="Tampering",
        dread_damage=9.0,
        dread_reproducibility=8.0,
        dread_exploitability=7.0,
        dread_affected_users=9.0,
        dread_discoverability=6.0,
        dread_score=7.8,
    )

    # MAESTRO-only threat (no stride_category)
    await crud.create_threat(
        model_id=model_id,
        name="Model Inversion",
        description=(
            "Adversary queries the fraud-detection ML model repeatedly to reconstruct "
            "training data and infer sensitive transaction patterns from API responses"
        ),
        target="Fraud Model",
        impact="High",
        likelihood="Low",
        mitigations=["Rate limiting", "Output perturbation"],
        maestro_category="Model Security",
    )

    model = await crud.get_threat_model(model_id)
    return model


# ---------------------------------------------------------------------------
# 404 on unknown model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_404(client):
    resp = await client.get("/api/export/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_markdown_default_format(client, model_with_threats):
    resp = await client.get(f"/api/export/{model_with_threats['id']}")
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    body = resp.text
    assert "SQL Injection" in body
    assert "Tampering" in body


@pytest.mark.asyncio
async def test_export_markdown_explicit_format(client, model_with_threats):
    resp = await client.get(f"/api/export/{model_with_threats['id']}?format=markdown")
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "content-disposition" in resp.headers
    assert resp.headers["content-disposition"].endswith('.md"')


@pytest.mark.asyncio
async def test_export_markdown_empty_threats(client, test_db):
    model_id = await crud.create_threat_model(
        title="Empty",
        description="Service with no threats yet identified by the system",
        provider="anthropic",
        model="m",
    )
    resp = await client.get(f"/api/export/{model_id}?format=markdown")
    assert resp.status_code == 200
    # Should produce valid (possibly header-only) markdown without crashing
    assert isinstance(resp.text, str)


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_pdf_content_type(client, model_with_threats):
    resp = await client.get(f"/api/export/{model_with_threats['id']}?format=pdf")
    assert resp.status_code == 200
    assert "application/pdf" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_export_pdf_magic_bytes(client, model_with_threats):
    resp = await client.get(f"/api/export/{model_with_threats['id']}?format=pdf")
    assert resp.content[:4] == b"%PDF"


@pytest.mark.asyncio
async def test_export_pdf_disposition_header(client, model_with_threats):
    resp = await client.get(f"/api/export/{model_with_threats['id']}?format=pdf")
    assert resp.headers["content-disposition"].endswith('.pdf"')


# ---------------------------------------------------------------------------
# SARIF export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_sarif_valid_structure(client, model_with_threats):
    resp = await client.get(f"/api/export/{model_with_threats['id']}?format=sarif")
    assert resp.status_code == 200
    data = json.loads(resp.content)
    assert data["version"] == "2.1.0"
    assert "$schema" in data
    assert "runs" in data


@pytest.mark.asyncio
async def test_export_sarif_maestro_only_produces_empty_runs(client, test_db):
    """MAESTRO-only threats produce a valid but empty SARIF result."""
    model_id = await crud.create_threat_model(
        title="AI Pipeline",
        description="ML training pipeline with model versioning and data lake",
        provider="anthropic",
        model="m",
        framework="MAESTRO",
    )
    await crud.create_threat(
        model_id=model_id,
        name="Data Poisoning",
        description=(
            "Adversary inserts malicious training samples into the data pipeline "
            "to corrupt model weights and degrade prediction accuracy at inference time"
        ),
        target="Training Set",
        impact="High",
        likelihood="Medium",
        mitigations=["Input validation", "Anomaly detection"],
        maestro_category="Data Security",
    )
    resp = await client.get(f"/api/export/{model_id}?format=sarif")
    assert resp.status_code == 200
    data = json.loads(resp.content)
    # Valid SARIF structure even if results are empty
    assert "runs" in data


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_json_structure(client, model_with_threats):
    resp = await client.get(f"/api/export/{model_with_threats['id']}?format=json")
    assert resp.status_code == 200
    data = resp.json()
    assert "model" in data
    assert "threats" in data
    assert data["model"]["id"] == model_with_threats["id"]
    assert len(data["threats"]) == 2


# ---------------------------------------------------------------------------
# Status filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_status_filter(client, model_with_threats, test_db):
    # Approve only the first threat
    threats = await crud.list_threats(model_with_threats["id"])
    await crud.update_threat_status(threats[0]["id"], "approved")

    resp = await client.get(
        f"/api/export/{model_with_threats['id']}?format=json&status_filter=approved"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["threats"]) == 1
    assert data["threats"][0]["status"] == "approved"
