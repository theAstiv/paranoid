"""Pre-flight checks run before the main pipeline.

analyze_description_gaps() inspects the system description and extracted context
for common completeness problems so that users can fix them before committing to a
full pipeline run (which may cost LLM tokens and take several minutes).
"""

import logging
import re

from backend.models.api import AnalyzeDescriptionResponse, DescriptionGap
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
