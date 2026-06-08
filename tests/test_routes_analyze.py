"""Tests for POST /api/analyze/ route.

Uses FastAPI TestClient with create_provider + analyze_bundle patched so no
API keys or network access are required.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from backend.models.api import (
    AnalyzeAssumptionsResponse,
    AnalyzeBundleResponse,
    AnalyzeDescriptionResponse,
)


# ── Shared mocks ──────────────────────────────────────────────────────────────


class _MockProvider:
    """No-op provider — satisfies the async context manager protocol."""

    name = "mock"
    model = "mock"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def generate_structured(self, *a, **kw):
        raise RuntimeError("should not be called when analyze_bundle is mocked")


_CLEAN_RESPONSE = AnalyzeBundleResponse(
    description=AnalyzeDescriptionResponse(gaps=[], is_sufficient=True),
    assumptions=AnalyzeAssumptionsResponse(gaps=[], is_sufficient=True),
)


def _make_client(monkeypatch, tmp_path, *, bundle_mock=None):
    """Build a TestClient with provider + analyze_bundle mocked."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    if bundle_mock is None:
        bundle_mock = AsyncMock(return_value=_CLEAN_RESPONSE)
    return (
        bundle_mock,
        patch("backend.routes.analyze.create_provider", return_value=_MockProvider()),
        patch("backend.routes.analyze.analyze_bundle", new=bundle_mock),
    )


# ── Validation ────────────────────────────────────────────────────────────────


def test_post_analyze_rejects_empty_description(tmp_path, monkeypatch):
    _, p1, p2 = _make_client(monkeypatch, tmp_path)
    with p1, p2:
        from backend.main import app

        with TestClient(app) as c:
            res = c.post("/api/analyze/", json={"description": "", "assumptions": []})
    assert res.status_code == 422


def test_post_analyze_rejects_missing_description(tmp_path, monkeypatch):
    _, p1, p2 = _make_client(monkeypatch, tmp_path)
    with p1, p2:
        from backend.main import app

        with TestClient(app) as c:
            res = c.post("/api/analyze/", json={"assumptions": []})
    assert res.status_code == 422


def test_post_analyze_rejects_oversized_description(tmp_path, monkeypatch):
    _, p1, p2 = _make_client(monkeypatch, tmp_path)
    with p1, p2:
        from backend.main import app

        with TestClient(app) as c:
            res = c.post("/api/analyze/", json={"description": "x" * 50_001, "assumptions": []})
    assert res.status_code == 422


# ── Happy-path structure ──────────────────────────────────────────────────────


def test_post_analyze_returns_both_sections(tmp_path, monkeypatch):
    _, p1, p2 = _make_client(monkeypatch, tmp_path)
    with p1, p2:
        from backend.main import app

        with TestClient(app) as c:
            res = c.post(
                "/api/analyze/",
                json={
                    "description": "A payment API that authenticates via JWT.",
                    "assumptions": ["TLS enforced"],
                },
            )
    assert res.status_code == 200
    body = res.json()
    assert "description" in body
    assert "assumptions" in body
    assert "gaps" in body["description"]
    assert "is_sufficient" in body["description"]
    assert "gaps" in body["assumptions"]
    assert "is_sufficient" in body["assumptions"]


def test_post_analyze_default_assumptions_is_empty_list(tmp_path, monkeypatch):
    _, p1, p2 = _make_client(monkeypatch, tmp_path)
    with p1, p2:
        from backend.main import app

        with TestClient(app) as c:
            res = c.post(
                "/api/analyze/", json={"description": "A payment API that authenticates via JWT."}
            )
    assert res.status_code == 200


def test_post_analyze_passes_assumptions_to_analyzer(tmp_path, monkeypatch):
    """Verify assumptions forwarded to analyze_bundle via call-args inspection."""
    mock, p1, p2 = _make_client(monkeypatch, tmp_path)
    with p1, p2:
        from backend.main import app

        with TestClient(app) as c:
            c.post(
                "/api/analyze/",
                json={
                    "description": "Some description",
                    "assumptions": ["TLS enforced", "WAF in place"],
                },
            )
    assert mock.call_args.kwargs["assumptions"] == ["TLS enforced", "WAF in place"]


# ── Deterministic path (real pre_flight logic) ────────────────────────────────


def test_post_analyze_short_description_is_not_sufficient(tmp_path, monkeypatch):
    """Integration: real deterministic logic — short description returns is_sufficient=False."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    mock_provider = MagicMock()
    mock_provider.__aenter__ = AsyncMock(return_value=mock_provider)
    mock_provider.__aexit__ = AsyncMock(return_value=None)
    mock_provider.generate_structured = AsyncMock(
        side_effect=Exception("should not be called for short description")
    )
    with patch("backend.routes.analyze.create_provider", return_value=mock_provider):
        from backend.main import app

        with TestClient(app) as c:
            res = c.post("/api/analyze/", json={"description": "short", "assumptions": []})
    assert res.status_code == 200
    assert res.json()["description"]["is_sufficient"] is False


def test_post_analyze_empty_assumptions_flags_gap(tmp_path, monkeypatch):
    """Integration: real deterministic check — empty assumptions list returns a gap."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    mock_provider = MagicMock()
    mock_provider.__aenter__ = AsyncMock(return_value=mock_provider)
    mock_provider.__aexit__ = AsyncMock(return_value=None)
    mock_provider.generate_structured = AsyncMock(
        return_value=AnalyzeAssumptionsResponse(gaps=[], is_sufficient=True)
    )
    with patch("backend.routes.analyze.create_provider", return_value=mock_provider):
        from backend.main import app

        with TestClient(app) as c:
            res = c.post(
                "/api/analyze/",
                json={
                    "description": (
                        "A REST API gateway that authenticates via JWT. Sends data to "
                        "an external Postgres database inside a private VPC. The gateway "
                        "is internet-facing; all backend services are internal."
                    ),
                    "assumptions": [],
                },
            )
    assert res.status_code == 200
    asmp_gaps = res.json()["assumptions"]["gaps"]
    assert len(asmp_gaps) > 0
    assert any(g["field"] == "assumptions" for g in asmp_gaps)
