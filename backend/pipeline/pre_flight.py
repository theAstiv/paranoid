"""Pre-flight checks run before the main pipeline.

Two public entry points:
  analyze_description_gaps()  — inspects the system description for completeness
  analyze_assumptions_gaps()  — inspects the assumptions list for completeness
  analyze_bundle()            — runs both in parallel, returns AnalyzeBundleResponse

Both run fast deterministic checks first and optionally call the LLM for a deeper
pass. Both fall back gracefully to deterministic-only on provider error.
"""

import asyncio
import logging
import re

from backend.models.api import (
    AnalyzeAssumptionsResponse,
    AnalyzeBundleResponse,
    AnalyzeDescriptionResponse,
    AssumptionsGap,
    DescriptionGap,
)
from backend.providers.base import LLMProvider, ProviderError


logger = logging.getLogger(__name__)


# ── Deterministic gap checks ──────────────────────────────────────────────────

_AUTH_TERMS = re.compile(
    r"\b(auth(?:entication|orization)?|oauth|jwt|token|saml|sso|password|credential|"
    r"api.?key|bearer|session|login|mfa|2fa)\b",
    re.IGNORECASE,
)

_BOUNDARY_TERMS = re.compile(
    r"\b(trust.?boundary|network.?segment|dmz|firewall|vlan|subnet|vpc|perimeter|"
    r"internet.?facing|internal|external|public|private)\b",
    re.IGNORECASE,
)

_FLOW_TERMS = re.compile(
    r"\b(sends?|receives?|transfers?|communicates?|calls?|requests?|responses?|"
    r"reads?|writes?|stores?|fetches?|connects?|publishes?|subscribes?)\b",
    re.IGNORECASE,
)

_EXTERNAL_TERMS = re.compile(
    r"\b(third.?party|external|vendor|api|webhook|integration|partner|upstream|"
    r"downstream|database|db|queue|broker|cache|cdn|dns|smtp|email)\b",
    re.IGNORECASE,
)

_MIN_DESCRIPTION_LENGTH = 80


def _deterministic_gaps(description: str) -> list[DescriptionGap]:
    """Fast keyword-based gap detection — runs without an LLM call."""
    gaps: list[DescriptionGap] = []

    if len(description.strip()) < _MIN_DESCRIPTION_LENGTH:
        gaps.append(
            DescriptionGap(
                field="description",
                severity="error",
                message=(
                    f"Description is too short ({len(description.strip())} chars). "
                    "Provide at least 80 characters describing the system's components, "
                    "data flows, and trust boundaries."
                ),
            )
        )
        # Short description → the term checks below would produce noise, not signal
        return gaps

    if not _AUTH_TERMS.search(description):
        gaps.append(
            DescriptionGap(
                field="authentication",
                severity="warning",
                message=(
                    "No authentication or authorization mechanism is mentioned. "
                    "Describe how users and services prove their identity (e.g. OAuth, JWT, API keys)."
                ),
            )
        )

    if not _BOUNDARY_TERMS.search(description):
        gaps.append(
            DescriptionGap(
                field="trust_boundaries",
                severity="warning",
                message=(
                    "No trust boundaries are described. "
                    "Indicate which components are internet-facing, internal, or separated by network segments."
                ),
            )
        )

    if not _FLOW_TERMS.search(description):
        gaps.append(
            DescriptionGap(
                field="data_flows",
                severity="warning",
                message=(
                    "No data flows are mentioned. "
                    "Describe how data moves between components (e.g. 'the API sends user data to the database')."
                ),
            )
        )

    if not _EXTERNAL_TERMS.search(description):
        gaps.append(
            DescriptionGap(
                field="external_integrations",
                severity="warning",
                message=(
                    "No external systems or integrations are mentioned. "
                    "If the system interacts with databases, queues, or third-party APIs, name them."
                ),
            )
        )

    return gaps


# ── LLM-backed gap analysis ───────────────────────────────────────────────────

_ANALYZE_SYSTEM_PROMPT = """\
You are a security architect reviewing a system description before threat modeling.
Your task is to identify gaps that would prevent a thorough STRIDE threat analysis.

Return a JSON object with this exact shape:
{
  "gaps": [
    { "field": "<topic>", "severity": "warning" | "error", "message": "<what is missing and why it matters>" }
  ],
  "is_sufficient": true | false
}

Identify gaps in these categories (only report genuine gaps, not minor omissions):
- description: Is the overall description too vague or too short to threat-model?
- authentication: How do users/services authenticate? What mechanism is in place?
- trust_boundaries: Which components are internet-facing vs internal? Any network separation?
- data_flows: How does data move between components? What data is sensitive?
- external_integrations: Third-party APIs, databases, queues, CDNs the system depends on?
- data_storage: Where is data persisted? What is stored and for how long?

severity=error means the gap makes threat modeling unreliable.
severity=warning means the gap will reduce coverage but analysis can still proceed.

is_sufficient=true when there are no error-severity gaps.\
"""


async def analyze_description_gaps(
    description: str,
    provider: LLMProvider,
    temperature: float = 0.1,
) -> AnalyzeDescriptionResponse:
    """Analyze the system description for completeness gaps.

    Runs deterministic checks first. If no blocking issues are found, also
    calls the LLM for nuanced gap detection. Falls back gracefully to
    deterministic-only results on provider error.

    Args:
        description: The user-provided system description.
        provider: LLM provider for enhanced analysis.
        temperature: Sampling temperature (low for consistent gap detection).

    Returns:
        AnalyzeDescriptionResponse with gaps list and is_sufficient flag.
    """
    det_gaps = _deterministic_gaps(description)

    # Skip the LLM call when deterministic checks have already surfaced enough
    # signal: either a blocking error, or ≥3 warning-level gaps (out of 4 possible).
    # Running the LLM in those cases just pays token cost to restate what the user
    # already sees, and most such descriptions need rewriting before analysis helps.
    has_errors = any(g.severity == "error" for g in det_gaps)
    if has_errors or len(det_gaps) >= 3:
        return AnalyzeDescriptionResponse(gaps=det_gaps, is_sufficient=not has_errors)

    try:
        result = await provider.generate_structured(
            prompt=f"<description>{description}</description>",
            response_model=AnalyzeDescriptionResponse,
            temperature=temperature,
            shared_context=_ANALYZE_SYSTEM_PROMPT,
        )
        # Merge: keep LLM gaps, deduplicate against deterministic ones by field+severity
        det_fields = {(g.field, g.severity) for g in det_gaps}
        merged = list(det_gaps)
        for g in result.gaps:
            if (g.field, g.severity) not in det_fields:
                merged.append(g)
        is_sufficient = not any(g.severity == "error" for g in merged)
        return AnalyzeDescriptionResponse(gaps=merged, is_sufficient=is_sufficient)

    except ProviderError as e:
        logger.warning(f"LLM gap analysis failed, using deterministic results only: {e}")
        is_sufficient = not has_errors
        return AnalyzeDescriptionResponse(gaps=det_gaps, is_sufficient=is_sufficient)


# ── Assumptions gap checks ────────────────────────────────────────────────────

_CONTROLS_TERMS = re.compile(
    r"\b(tls|ssl|https|encryption|encrypt|auth(?:entication|orization)?|"
    r"jwt|oauth|api.?key|rate.?limit|waf|firewall|mfa|2fa|rbac|acl|"
    r"secret|vault|kms|hsm|signed|signature|certificate|control)\b",
    re.IGNORECASE,
)

_OUT_OF_SCOPE_TERMS = re.compile(
    r"\b(out.?of.?scope|not.?in.?scope|excluded|exclude|"
    r"outside.?scope|does.?not.?cover|not.?covered|beyond.?scope|"
    r"third.?party|assumed.?secure|assumed secure)\b",
    re.IGNORECASE,
)

_FOCUS_TERMS = re.compile(
    r"\b(focus|prioriti[sz]e?|key.?risk|key risk|concern|threat.?vector|"
    r"attack.?surface|attack surface|emphasis|highlight)\b",
    re.IGNORECASE,
)

_SCOPE_TERMS = re.compile(
    r"\b(in.?scope|in scope|scope|covers?|includes?|modell?ing)\b",
    re.IGNORECASE,
)

_MIN_ASSUMPTIONS = 2
_MIN_ASSUMPTION_CHARS = 30  # flag if every entry is a one-liner stub


def _deterministic_assumptions_gaps(
    assumptions: list[str],
) -> list[AssumptionsGap]:
    """Fast keyword-based assumptions gap detection — no LLM call."""
    gaps: list[AssumptionsGap] = []
    joined = " ".join(assumptions)

    if len(assumptions) == 0:
        gaps.append(
            AssumptionsGap(
                field="assumptions",
                severity="warning",
                message=(
                    "No assumptions provided. Adding assumptions helps the pipeline focus on "
                    "genuine risks and avoid suggesting controls that are already in place. "
                    "Include existing security controls, scope boundaries, and known constraints."
                ),
            )
        )
        # No point running further checks on an empty list
        return gaps

    if len(assumptions) < _MIN_ASSUMPTIONS:
        gaps.append(
            AssumptionsGap(
                field="assumptions",
                severity="info",
                message=(
                    f"Only {len(assumptions)} assumption provided. "
                    "Consider adding security controls in place, in-scope areas, "
                    "out-of-scope areas, and threat-modeling focus areas."
                ),
            )
        )

    # All entries are very short (stub list like ["TLS", "yes"])
    if assumptions and all(len(a.strip()) < _MIN_ASSUMPTION_CHARS for a in assumptions):
        gaps.append(
            AssumptionsGap(
                field="assumptions",
                severity="warning",
                message=(
                    "All assumptions are very short (under 30 chars each). "
                    "Expand them with specific details — e.g. 'TLS 1.3 enforced on all "
                    "client-to-server connections' rather than just 'TLS'."
                ),
            )
        )

    if not _CONTROLS_TERMS.search(joined):
        gaps.append(
            AssumptionsGap(
                field="controls",
                severity="warning",
                message=(
                    "No existing security controls are mentioned (e.g. TLS, WAF, rate limiting, "
                    "encryption, MFA). Listing these prevents the pipeline from suggesting "
                    "threats that are already mitigated."
                ),
            )
        )

    if not _OUT_OF_SCOPE_TERMS.search(joined):
        gaps.append(
            AssumptionsGap(
                field="out_of_scope",
                severity="info",
                message=(
                    "No out-of-scope declarations found. Explicitly marking what is out of scope "
                    "(e.g. 'AWS shared-responsibility infrastructure', 'third-party payment processor') "
                    "prevents the pipeline from generating threats you can't act on."
                ),
            )
        )

    if not _FOCUS_TERMS.search(joined):
        gaps.append(
            AssumptionsGap(
                field="focus_areas",
                severity="info",
                message=(
                    "No threat-modeling focus areas specified. Adding focus areas "
                    "(e.g. 'authentication bypass vectors', 'data exfiltration through model outputs') "
                    "guides the pipeline to prioritise the attack surfaces that matter most."
                ),
            )
        )

    return gaps


_ASSUMPTIONS_SYSTEM_PROMPT = """\
You are a security architect reviewing a set of threat-modeling assumptions.
Your task is to identify gaps that reduce the quality of a STRIDE or MAESTRO analysis.

Return a JSON object with this exact shape:
{
  "gaps": [
    {
      "field": "controls" | "in_scope" | "out_of_scope" | "focus_areas" | "constraints" | "coverage" | "assumptions",
      "severity": "warning" | "error" | "info",
      "message": "<what is missing and why it matters, 1-2 sentences>"
    }
  ],
  "is_sufficient": true | false
}

Evaluate only genuine gaps — do not repeat issues that are clearly covered.
Identify gaps in:
- controls: Are existing security controls listed? Without them the pipeline suggests redundant mitigations.
- in_scope: Are the areas being modeled clearly bounded?
- out_of_scope: Are third-party or infrastructure components explicitly excluded?
- focus_areas: Are specific threat vectors or attack surfaces called out?
- constraints: Are regulatory, operational, or architectural constraints mentioned?
- coverage: Are there threat categories (e.g. repudiation, denial of service) with no assumptions at all?

severity=error: the gap materially degrades threat model quality.
severity=warning: coverage will be reduced but analysis can still proceed.
severity=info: minor improvement opportunity.

is_sufficient=true when there are no error-severity gaps.\
"""


async def _llm_assumptions_gaps(
    assumptions: list[str],
    description: str,
    provider: LLMProvider,
    temperature: float = 0.1,
) -> AnalyzeAssumptionsResponse:
    """LLM-backed assumptions gap analysis."""
    assumptions_text = "\n".join(f"- {a}" for a in assumptions) if assumptions else "(none)"
    prompt = (
        f"<description>{description}</description>\n"
        f"<assumptions>\n{assumptions_text}\n</assumptions>"
    )
    return await provider.generate_structured(
        prompt=prompt,
        response_model=AnalyzeAssumptionsResponse,
        temperature=temperature,
        shared_context=_ASSUMPTIONS_SYSTEM_PROMPT,
    )


async def analyze_assumptions_gaps(
    assumptions: list[str],
    description: str,
    provider: LLMProvider,
    temperature: float = 0.1,
) -> AnalyzeAssumptionsResponse:
    """Analyze the assumptions list for completeness gaps.

    Runs deterministic checks first. Calls the LLM for nuanced analysis when
    the deterministic pass doesn't already surface enough signal. Falls back
    gracefully to deterministic-only results on provider error.

    Args:
        assumptions: List of user-provided assumption strings.
        description: The system description (for context in the LLM prompt).
        provider: LLM provider for enhanced analysis.
        temperature: Sampling temperature.

    Returns:
        AnalyzeAssumptionsResponse with gaps list and is_sufficient flag.
    """
    det_gaps = _deterministic_assumptions_gaps(assumptions)
    has_errors = any(g.severity == "error" for g in det_gaps)

    # Skip LLM when deterministic already has enough signal or nothing to work with
    if has_errors or not assumptions or len(det_gaps) >= 4:
        return AnalyzeAssumptionsResponse(gaps=det_gaps, is_sufficient=not has_errors)

    try:
        result = await _llm_assumptions_gaps(assumptions, description, provider, temperature)
        # Merge: deduplicate by (field, severity)
        det_keys = {(g.field, g.severity) for g in det_gaps}
        merged = list(det_gaps)
        for g in result.gaps:
            if (g.field, g.severity) not in det_keys:
                merged.append(g)
        is_sufficient = not any(g.severity == "error" for g in merged)
        return AnalyzeAssumptionsResponse(gaps=merged, is_sufficient=is_sufficient)

    except ProviderError as e:
        logger.warning(f"LLM assumptions gap analysis failed, using deterministic results: {e}")
        return AnalyzeAssumptionsResponse(gaps=det_gaps, is_sufficient=not has_errors)


async def analyze_bundle(
    description: str,
    assumptions: list[str],
    provider: LLMProvider,
) -> AnalyzeBundleResponse:
    """Run description and assumptions gap analysis concurrently.

    Args:
        description: System description text.
        assumptions: List of assumption strings.
        provider: LLM provider instance.

    Returns:
        AnalyzeBundleResponse combining both analyses.
    """
    desc_task = asyncio.create_task(
        analyze_description_gaps(description=description, provider=provider)
    )
    asmp_task = asyncio.create_task(
        analyze_assumptions_gaps(
            assumptions=assumptions, description=description, provider=provider
        )
    )
    desc_result, asmp_result = await asyncio.gather(desc_task, asmp_task)
    return AnalyzeBundleResponse(description=desc_result, assumptions=asmp_result)
