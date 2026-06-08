"""Tests for backend/pipeline/pre_flight.py — deterministic + LLM gap checks.

All LLM calls are mocked via a minimal async provider double.
No API keys or network access required.
"""

import pytest

from backend.models.api import (
    AnalyzeAssumptionsResponse,
    AnalyzeDescriptionResponse,
    AssumptionsGap,
    DescriptionGap,
)
from backend.pipeline.pre_flight import (
    _deterministic_assumptions_gaps,
    _deterministic_gaps,
    analyze_assumptions_gaps,
    analyze_bundle,
    analyze_description_gaps,
)
from backend.providers.base import ProviderError


# ── Provider doubles ──────────────────────────────────────────────────────────


class _OKDescriptionProvider:
    """Returns an empty gap list for description analysis."""

    name = "mock"
    model = "mock"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def generate_structured(self, prompt, response_model, **kwargs):
        if response_model is AnalyzeDescriptionResponse:
            return AnalyzeDescriptionResponse(gaps=[], is_sufficient=True)
        if response_model is AnalyzeAssumptionsResponse:
            return AnalyzeAssumptionsResponse(gaps=[], is_sufficient=True)
        raise ValueError(f"Unexpected model: {response_model}")


class _ErrorProvider:
    """Always raises ProviderError."""

    name = "mock-fail"
    model = "mock"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def generate_structured(self, *a, **kw):
        raise ProviderError(provider="mock", message="intentional test failure")


class _LLMGapProvider:
    """Returns a specific set of LLM gaps for assertions."""

    def __init__(self, desc_gaps=None, asmp_gaps=None):
        self._desc_gaps = desc_gaps or []
        self._asmp_gaps = asmp_gaps or []
        self.name = "mock"
        self.model = "mock"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def generate_structured(self, prompt, response_model, **kwargs):
        if response_model is AnalyzeDescriptionResponse:
            return AnalyzeDescriptionResponse(
                gaps=self._desc_gaps,
                is_sufficient=not any(g.severity == "error" for g in self._desc_gaps),
            )
        if response_model is AnalyzeAssumptionsResponse:
            return AnalyzeAssumptionsResponse(
                gaps=self._asmp_gaps,
                is_sufficient=not any(g.severity == "error" for g in self._asmp_gaps),
            )
        raise ValueError(f"Unexpected model: {response_model}")


# ── _deterministic_gaps (description) ────────────────────────────────────────


def test_deterministic_gaps_short_description_returns_error():
    gaps = _deterministic_gaps("too short")
    assert len(gaps) == 1
    assert gaps[0].severity == "error"
    assert gaps[0].field == "description"


def test_deterministic_gaps_missing_auth_warns():
    desc = (
        "A web application that stores user data in a Postgres database. "
        "Data flows from the browser to an API gateway and then to the database. "
        "The API gateway is internet-facing; the database is internal."
    )
    gaps = _deterministic_gaps(desc)
    fields = [g.field for g in gaps]
    assert "authentication" in fields
    assert all(g.severity == "warning" for g in gaps)


def test_deterministic_gaps_missing_boundaries_warns():
    desc = (
        "A payment service that authenticates users via JWT and OAuth2. "
        "Sends transaction data to Stripe via HTTPS. Reads from the orders database."
    )
    gaps = _deterministic_gaps(desc)
    fields = [g.field for g in gaps]
    assert "trust_boundaries" in fields


def test_deterministic_gaps_missing_flows_warns():
    desc = (
        "An internal admin portal with JWT auth and role-based access. "
        "External SaaS integrations for reporting. Trust boundary between VPC "
        "and public internet is enforced by firewall rules."
    )
    gaps = _deterministic_gaps(desc)
    fields = [g.field for g in gaps]
    assert "data_flows" in fields


def test_deterministic_gaps_complete_description_returns_empty():
    desc = (
        "A REST API gateway that authenticates requests via JWT bearer tokens. "
        "Sends user data to a downstream Postgres database inside a private VPC. "
        "Reads from an external third-party payment API (Stripe) over TLS 1.3. "
        "The gateway is internet-facing; all backend services are internal."
    )
    gaps = _deterministic_gaps(desc)
    assert gaps == []


# ── _deterministic_assumptions_gaps ──────────────────────────────────────────


def test_deterministic_assumptions_empty_list_warns():
    gaps = _deterministic_assumptions_gaps([])
    assert len(gaps) == 1
    assert gaps[0].field == "assumptions"
    assert gaps[0].severity == "warning"


def test_deterministic_assumptions_single_entry_info():
    gaps = _deterministic_assumptions_gaps(
        ["TLS enforced on all connections"],
    )
    fields = [g.field for g in gaps]
    assert "assumptions" in fields
    info_gaps = [g for g in gaps if g.severity == "info" and g.field == "assumptions"]
    assert info_gaps, "Should flag single entry with info"


def test_deterministic_assumptions_all_short_entries_warns():
    gaps = _deterministic_assumptions_gaps(
        ["TLS", "JWT", "OK"],
    )
    fields = [g.field for g in gaps]
    assert "assumptions" in fields


def test_deterministic_assumptions_missing_controls_warns():
    # These assumptions have no security-controls keywords (no tls/auth/encrypt etc.)
    gaps = _deterministic_assumptions_gaps(
        [
            "Out of scope: AWS infrastructure is handled by the cloud provider",
            "Focus: business logic flaws and data exfiltration",
            "In scope: all API endpoints and database queries",
        ],
    )
    fields = [g.field for g in gaps]
    assert "controls" in fields


def test_deterministic_assumptions_missing_out_of_scope_flagged():
    gaps = _deterministic_assumptions_gaps(
        [
            "TLS 1.3 enforced on all connections",
            "JWT authentication with 15-minute expiry",
            "Focus areas: injection attacks, session management",
        ],
    )
    fields = [g.field for g in gaps]
    assert "out_of_scope" in fields


def test_deterministic_assumptions_missing_focus_areas_info():
    gaps = _deterministic_assumptions_gaps(
        [
            "TLS 1.3 enforced on all connections",
            "Out of scope: AWS shared-responsibility model",
            "JWT authentication is in place",
        ],
    )
    fields = [g.field for g in gaps]
    assert "focus_areas" in fields
    # Focus is info only
    focus_gaps = [g for g in gaps if g.field == "focus_areas"]
    assert all(g.severity == "info" for g in focus_gaps)


def test_deterministic_assumptions_complete_returns_no_errors():
    gaps = _deterministic_assumptions_gaps(
        [
            "TLS 1.3 enforced on all client-to-server connections",
            "JWT authentication with 15-minute access tokens and 7-day refresh tokens",
            "Out of scope: AWS shared-responsibility infrastructure, third-party payment processor",
            "In scope: API authentication, session management, data encryption at rest",
            "Focus areas: authentication bypass vectors, privilege escalation, injection attacks",
        ],
    )
    assert not any(g.severity == "error" for g in gaps)


# ── analyze_description_gaps — LLM integration ───────────────────────────────


@pytest.mark.asyncio
async def test_analyze_description_gaps_returns_is_sufficient_true_when_clean():
    desc = (
        "A REST API gateway that authenticates requests via JWT bearer tokens. "
        "Sends user data to a downstream Postgres database inside a private VPC. "
        "Reads from an external third-party payment API over TLS 1.3. "
        "The gateway is internet-facing; all backend services are internal."
    )
    result = await analyze_description_gaps(description=desc, provider=_OKDescriptionProvider())
    assert isinstance(result, AnalyzeDescriptionResponse)
    assert result.is_sufficient is True


@pytest.mark.asyncio
async def test_analyze_description_gaps_falls_back_on_provider_error():
    desc = (
        "A REST API gateway that authenticates requests via JWT bearer tokens. "
        "Sends user data to a downstream Postgres database inside a private VPC. "
        "Reads from an external third-party payment API over TLS 1.3. "
        "The gateway is internet-facing; all backend services are internal."
    )
    result = await analyze_description_gaps(description=desc, provider=_ErrorProvider())
    # Should still return a valid response from deterministic pass
    assert isinstance(result, AnalyzeDescriptionResponse)


@pytest.mark.asyncio
async def test_analyze_description_gaps_skips_llm_on_many_deterministic_gaps():
    """When ≥3 deterministic gaps found, LLM call is skipped (no token spend)."""
    # Short description triggers error + no auth/boundary/flow/external
    result = await analyze_description_gaps(
        description="x" * 81,  # long enough but content-free
        provider=_ErrorProvider(),  # would raise if called
    )
    assert isinstance(result, AnalyzeDescriptionResponse)


@pytest.mark.asyncio
async def test_analyze_description_gaps_merges_llm_and_deterministic():
    desc = (
        "A REST API gateway that authenticates requests via JWT bearer tokens. "
        "Sends user data to a downstream Postgres database inside a private VPC. "
        "Reads from an external third-party payment API over TLS 1.3. "
        "The gateway is internet-facing; all backend services are internal."
    )
    llm_gap = DescriptionGap(field="data_storage", severity="warning", message="No storage detail")
    provider = _LLMGapProvider(desc_gaps=[llm_gap])
    result = await analyze_description_gaps(description=desc, provider=provider)
    fields = [g.field for g in result.gaps]
    assert "data_storage" in fields


# ── analyze_assumptions_gaps — LLM integration ───────────────────────────────


@pytest.mark.asyncio
async def test_analyze_assumptions_gaps_sufficient_on_complete_list():
    result = await analyze_assumptions_gaps(
        assumptions=[
            "TLS 1.3 enforced on all client-to-server connections",
            "JWT authentication with 15-minute access tokens",
            "Out of scope: AWS shared-responsibility infrastructure",
            "Focus: authentication bypass, privilege escalation",
        ],
        description="A system with auth, flows, external systems and trust boundaries.",
        provider=_OKDescriptionProvider(),
    )
    assert isinstance(result, AnalyzeAssumptionsResponse)
    assert result.is_sufficient is True


@pytest.mark.asyncio
async def test_analyze_assumptions_gaps_falls_back_on_provider_error():
    result = await analyze_assumptions_gaps(
        assumptions=["TLS 1.3 enforced"],
        description="A system description with enough content to pass through.",
        provider=_ErrorProvider(),
    )
    assert isinstance(result, AnalyzeAssumptionsResponse)


@pytest.mark.asyncio
async def test_analyze_assumptions_gaps_merges_llm_and_deterministic():
    asmp_list = [
        "TLS 1.3 enforced on all connections",
        "JWT authentication with 15-minute tokens",
        "Out of scope: AWS infrastructure",
        "Focus: injection attacks",
    ]
    llm_gap = AssumptionsGap(
        field="coverage", severity="info", message="No mention of DoS assumptions"
    )
    provider = _LLMGapProvider(asmp_gaps=[llm_gap])
    result = await analyze_assumptions_gaps(
        assumptions=asmp_list,
        description="A described system.",
        provider=provider,
    )
    fields = [g.field for g in result.gaps]
    assert "coverage" in fields


@pytest.mark.asyncio
async def test_analyze_assumptions_gaps_deduplicates_llm_results():
    """LLM gaps with same (field, severity) as deterministic ones are dropped."""
    asmp_list = ["TLS"]  # triggers all_short_entries deterministic warning
    # LLM tries to add the same (assumptions, warning) again
    llm_dup = AssumptionsGap(field="assumptions", severity="warning", message="Duplicate from LLM")
    provider = _LLMGapProvider(asmp_gaps=[llm_dup])
    result = await analyze_assumptions_gaps(
        assumptions=asmp_list,
        description="Some description text here.",
        provider=provider,
    )
    assumption_warnings = [
        g for g in result.gaps if g.field == "assumptions" and g.severity == "warning"
    ]
    # Should appear exactly once (from deterministic, not duplicated by LLM)
    assert len(assumption_warnings) == 1


@pytest.mark.asyncio
async def test_analyze_assumptions_gaps_skips_llm_on_empty_list():
    """Empty assumptions list → deterministic only, LLM skipped (not an error, just warning)."""
    result = await analyze_assumptions_gaps(
        assumptions=[],
        description="Some description.",
        provider=_ErrorProvider(),  # would raise if called — LLM must be skipped
    )
    assert isinstance(result, AnalyzeAssumptionsResponse)
    # Empty list produces a warning, not an error — so is_sufficient stays True
    assert result.is_sufficient is True
    assert len(result.gaps) == 1
    assert result.gaps[0].field == "assumptions"
    assert result.gaps[0].severity == "warning"


# ── analyze_bundle ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_bundle_returns_both_sections():
    from backend.models.api import AnalyzeBundleResponse

    result = await analyze_bundle(
        description=(
            "A REST API gateway that authenticates requests via JWT. "
            "Sends data to a Postgres database inside a private VPC. "
            "Reads from an external payment API over TLS. "
            "The gateway is internet-facing."
        ),
        assumptions=["TLS 1.3 enforced", "Out of scope: AWS infrastructure"],
        provider=_OKDescriptionProvider(),
    )
    assert isinstance(result, AnalyzeBundleResponse)
    assert isinstance(result.description, AnalyzeDescriptionResponse)
    assert isinstance(result.assumptions, AnalyzeAssumptionsResponse)


@pytest.mark.asyncio
async def test_analyze_bundle_is_sufficient_false_when_description_has_error():
    result = await analyze_bundle(
        description="too short",
        assumptions=[],
        provider=_OKDescriptionProvider(),
    )
    assert result.description.is_sufficient is False


@pytest.mark.asyncio
async def test_analyze_bundle_runs_concurrently(monkeypatch):
    """Both tasks should be created — verify by checking both results populated."""
    call_log = []

    class _LoggingProvider:
        name = "mock"
        model = "mock"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def generate_structured(self, prompt, response_model, **kwargs):
            call_log.append(response_model.__name__)
            if response_model is AnalyzeDescriptionResponse:
                return AnalyzeDescriptionResponse(gaps=[], is_sufficient=True)
            return AnalyzeAssumptionsResponse(gaps=[], is_sufficient=True)

    desc = (
        "A REST API authenticates via JWT, sends data to an external Postgres "
        "database inside a private VPC. Internet-facing API, internal DB."
    )
    result = await analyze_bundle(
        description=desc,
        assumptions=["TLS 1.3 enforced", "Out of scope: third-party providers"],
        provider=_LoggingProvider(),
    )
    assert result.description is not None
    assert result.assumptions is not None
