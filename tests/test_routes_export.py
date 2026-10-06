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
async def test_export_sarif_with_persisted_dependency_threat(client, test_db):
    """A threat with a persisted dependency_ref must not crash SARIF export.

    crud.list_threats() decodes dependency_ref from its stored JSON into a
    plain dict; _build_threats_list() previously passed that dict straight
    into Threat.model_construct() unconverted, and sarif.py's
    dependency_ref.package attribute access then raised AttributeError —
    a 500 on GET /api/export/{id}?format=sarif for any model that had run
    with a manifest. Route-level so it exercises the real DB round trip."""
    model_id = await crud.create_threat_model(
        title="Node Service",
        description="A Node.js service with npm dependencies for threat modeling",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
    )
    await crud.create_threat(
        model_id=model_id,
        name="Install-time code execution",
        description=(
            "A malicious postinstall script in a transitive dependency executes "
            "arbitrary code during npm install, compromising the build environment"
        ),
        target="lodash",
        impact="Critical",
        likelihood="Low",
        mitigations=["Pin exact versions", "npm ci --ignore-scripts"],
        stride_category="Elevation of Privilege",
        source="dependency",
        dependency_ref={
            "package": "lodash",
            "version": "4.17.21",
            "file": "lib/index.js",
            "line": 42,
            "rule_id": "dynamic_code",
        },
    )

    resp = await client.get(f"/api/export/{model_id}?format=sarif")
    assert resp.status_code == 200
    data = json.loads(resp.content)
    results = data["runs"][0]["results"]
    assert len(results) == 1
    assert results[0]["properties"]["dependencyRef"]["package"] == "lodash"


@pytest.mark.asyncio
async def test_export_sarif_with_persisted_attack_techniques(client, test_db):
    """A threat with persisted attack_techniques must not crash SARIF export.

    Same bug class as test_export_sarif_with_persisted_dependency_threat:
    crud.list_threats() decodes attack_techniques from its stored JSON into
    plain dicts; _build_threats_list() must convert them to TechniqueRef
    before sarif.py's `t.id` attribute access runs, or every SARIF export of
    a model with technique matches raises AttributeError."""
    model_id = await crud.create_threat_model(
        title="Node Service",
        description="A Node.js service with npm dependencies for threat modeling",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
    )
    await crud.create_threat(
        model_id=model_id,
        name="Compromise Software Supply Chain",
        description=(
            "A tarball-only file in evil-pkg@1.0.0 ships code not present in its "
            "public source repository, indicating possible supply-chain tampering"
        ),
        target="evil-pkg@1.0.0",
        impact="High",
        likelihood="Medium",
        mitigations=["Pin the exact version", "Review the capability diff"],
        stride_category="Tampering",
        attack_techniques=[
            {
                "id": "T1195.002",
                "name": "Compromise Software Supply Chain",
                "url": "https://attack.mitre.org/techniques/T1195/002",
                "confidence": 0.9,
                "method": "table",
            }
        ],
    )

    resp = await client.get(f"/api/export/{model_id}?format=sarif")
    assert resp.status_code == 200
    data = json.loads(resp.content)
    results = data["runs"][0]["results"]
    assert len(results) == 1
    assert results[0]["properties"]["tags"] == ["attack/T1195.002"]


@pytest.mark.asyncio
async def test_export_sarif_with_persisted_cvss_score(client, test_db):
    """A threat with a persisted cvss_vector must not lose the vector string
    in SARIF export. `cvss_vector` is a DB column, not a Threat model field
    — _build_threats_list()'s model_construct() silently drops unknown
    kwargs, so without re-parsing it into `cvss`, properties.cvss.vector
    would be None even though cvss_score/cvss_severity survive."""
    model_id = await crud.create_threat_model(
        title="API Service",
        description="A REST API service with unauthenticated deserialization",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
    )
    await crud.create_threat(
        model_id=model_id,
        name="Remote Code Execution",
        description=(
            "An attacker sends a crafted payload to the deserialization endpoint "
            "to execute arbitrary code on the server"
        ),
        target="API Gateway",
        impact="High",
        likelihood="High",
        mitigations=["Disable unsafe deserialization", "Validate input schema"],
        stride_category="Tampering",
        cvss_vector="AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        cvss_score=9.8,
        cvss_severity="critical",
    )

    resp = await client.get(f"/api/export/{model_id}?format=sarif")
    assert resp.status_code == 200
    data = json.loads(resp.content)
    results = data["runs"][0]["results"]
    assert len(results) == 1
    assert results[0]["properties"]["cvss"] == {
        "vector": "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        "score": 9.8,
        "severity": "critical",
    }
    assert results[0]["level"] == "error"
    # security-severity lives on the rule, not the result — GitHub code
    # scanning only reads it from tool.driver.rules[].properties.
    rules = data["runs"][0]["tool"]["driver"]["rules"]
    tampering_rule = next(r for r in rules if r["id"] == results[0]["ruleId"])
    assert tampering_rule["properties"]["security-severity"] == "9.8"


@pytest.mark.asyncio
async def test_export_sarif_with_persisted_dread(client, test_db):
    """A threat's persisted DREAD must reach SARIF. DREAD is stored as five
    flat dread_* columns, but sarif.py reads a nested `dread` — before
    threat_from_row() rebuilt it, every web SARIF export carried no DREAD at
    all and `level` silently fell back to likelihood."""
    model_id = await crud.create_threat_model(
        title="API Service",
        description="A REST API service",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
    )
    await crud.create_threat(
        model_id=model_id,
        name="Token Forgery",
        description="An attacker forges a session token to impersonate an administrator",
        target="Auth Service",
        impact="High",
        # Likelihood "Low" would map to `note`; DREAD 8.0 must win and map to `error`.
        likelihood="Low",
        mitigations=["Sign tokens with a rotated key"],
        stride_category="Spoofing",
        dread_damage=9.0,
        dread_reproducibility=8.0,
        dread_exploitability=7.0,
        dread_affected_users=8.0,
        dread_discoverability=8.0,
        dread_score=8.0,
    )

    resp = await client.get(f"/api/export/{model_id}?format=sarif")
    assert resp.status_code == 200
    results = json.loads(resp.content)["runs"][0]["results"]
    assert len(results) == 1
    assert results[0]["properties"]["dread"] == {
        "damage": 9.0,
        "reproducibility": 8.0,
        "exploitability": 7.0,
        "affected_users": 8.0,
        "discoverability": 8.0,
        "score": 8.0,
    }
    assert results[0]["level"] == "error"


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
