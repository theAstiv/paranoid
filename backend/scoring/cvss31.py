"""CVSS v3.1 base-score calculator.

Pure implementation of the CVSS v3.1 base-metric formula from the
specification (https://www.first.org/cvss/v3.1/specification-document,
section 7.1). No third-party dependency — the formula is ~40 lines of
arithmetic and a well-defined rounding rule, and a vendored copy is easier
to audit and test against the published reference vectors than a package.

The LLM pipeline (and manual review editing) only ever produces/edits the
eight base metrics; the score and severity are always computed here, never
trusted from a provider response. See backend/models/state.py's
`Threat.cvss_score`/`cvss_severity` (SkipJsonSchema, force-computed in
generate_threats()) for how that boundary is enforced.
"""

import math
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


class Cvss31Error(ValueError):
    """Raised when a CVSS v3.1 vector string is malformed or incomplete."""


AttackVector = Literal["N", "A", "L", "P"]
AttackComplexity = Literal["L", "H"]
PrivilegesRequired = Literal["N", "L", "H"]
UserInteraction = Literal["N", "R"]
Scope = Literal["U", "C"]
ImpactMetric = Literal["N", "L", "H"]


class Cvss31Metrics(BaseModel):
    """The eight CVSS v3.1 base metrics.

    Field names are spelled out (matching `DreadScore`'s style of
    `damage`/`reproducibility`/... rather than single-letter names) so the
    provider-facing schema is self-describing; the single-letter codes are
    the values, not the field names, and are kept uppercase because they are
    an external, fixed industry standard (first.org / NVD) that the vector
    string, NVD, and every CVSS calculator already use verbatim — lowercasing
    them would contradict the spec rather than just restyle it.
    """

    attack_vector: AttackVector = Field(description="AV: Network/Adjacent/Local/Physical")
    attack_complexity: AttackComplexity = Field(description="AC: Low/High")
    privileges_required: PrivilegesRequired = Field(description="PR: None/Low/High")
    user_interaction: UserInteraction = Field(description="UI: None/Required")
    scope: Scope = Field(description="S: Unchanged/Changed")
    confidentiality: ImpactMetric = Field(description="C: None/Low/High")
    integrity: ImpactMetric = Field(description="I: None/Low/High")
    availability: ImpactMetric = Field(description="A: None/Low/High")


# Metric code -> field name, in the canonical vector-string order.
_METRIC_ORDER: list[tuple[str, str]] = [
    ("AV", "attack_vector"),
    ("AC", "attack_complexity"),
    ("PR", "privileges_required"),
    ("UI", "user_interaction"),
    ("S", "scope"),
    ("C", "confidentiality"),
    ("I", "integrity"),
    ("A", "availability"),
]
_FIELD_BY_CODE = dict(_METRIC_ORDER)

_VECTOR_RE = re.compile(r"^(?:CVSS:3\.1/)?([A-Z]{1,2}:[A-Za-z](?:/[A-Z]{1,2}:[A-Za-z])*)$")

_AV_WEIGHTS = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}
_AC_WEIGHTS = {"L": 0.77, "H": 0.44}
_UI_WEIGHTS = {"N": 0.85, "R": 0.62}
_PR_WEIGHTS_UNCHANGED = {"N": 0.85, "L": 0.62, "H": 0.27}
_PR_WEIGHTS_CHANGED = {"N": 0.85, "L": 0.68, "H": 0.50}
_IMPACT_WEIGHTS = {"H": 0.56, "L": 0.22, "N": 0.0}

_SEVERITY_BANDS: list[tuple[float, float, str]] = [
    (0.0, 0.0, "none"),
    (0.1, 3.9, "low"),
    (4.0, 6.9, "medium"),
    (7.0, 8.9, "high"),
    (9.0, 10.0, "critical"),
]


def parse_vector(vector: str) -> Cvss31Metrics:
    """Parse a CVSS v3.1 base vector string, e.g.
    ``"AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"`` (the optional ``CVSS:3.1/``
    prefix is accepted and ignored). Metric order is NOT enforced — the
    canonical order above is what `to_vector_string()` always produces, but
    a vector with the same 8 metrics in any order parses and scores
    identically. Raises Cvss31Error on anything malformed, an unknown or
    duplicate metric code, an invalid value, or a missing required metric.
    """
    if not vector or not isinstance(vector, str):
        raise Cvss31Error("CVSS vector must be a non-empty string")

    match = _VECTOR_RE.match(vector.strip())
    if not match:
        raise Cvss31Error(f"Malformed CVSS v3.1 vector: {vector!r}")

    pairs = match.group(1).split("/")
    values: dict[str, str] = {}
    for pair in pairs:
        code, _, value = pair.partition(":")
        if code not in _FIELD_BY_CODE:
            raise Cvss31Error(f"Unknown CVSS metric {code!r} in vector: {vector!r}")
        if code in values:
            raise Cvss31Error(f"Duplicate CVSS metric {code!r} in vector: {vector!r}")
        values[code] = value

    missing = [code for code, _ in _METRIC_ORDER if code not in values]
    if missing:
        raise Cvss31Error(f"Vector {vector!r} is missing required metric(s): {', '.join(missing)}")

    try:
        return Cvss31Metrics(**{field: values[code] for code, field in _METRIC_ORDER})
    except ValidationError as exc:
        raise Cvss31Error(f"Invalid CVSS metric value(s) in vector: {vector!r}") from exc


def to_vector_string(metrics: Cvss31Metrics) -> str:
    """Render metrics back to the canonical ``AV:N/AC:L/...`` form."""
    parts = []
    for code, field in _METRIC_ORDER:
        parts.append(f"{code}:{getattr(metrics, field)}")
    return "/".join(parts)


def _roundup(value: float) -> float:
    """The CVSS spec's custom round-up-to-1-decimal function (not plain
    Python rounding — see spec section 7.1)."""
    int_input = round(value * 100000)
    if int_input % 10000 == 0:
        return int_input / 100000
    return (math.floor(int_input / 10000) + 1) / 10


def compute_score(metrics: Cvss31Metrics) -> float:
    """CVSS v3.1 base score (0.0-10.0) per the published formula."""
    changed = metrics.scope == "C"
    pr_weights = _PR_WEIGHTS_CHANGED if changed else _PR_WEIGHTS_UNCHANGED

    av = _AV_WEIGHTS[metrics.attack_vector]
    ac = _AC_WEIGHTS[metrics.attack_complexity]
    pr = pr_weights[metrics.privileges_required]
    ui = _UI_WEIGHTS[metrics.user_interaction]
    c = _IMPACT_WEIGHTS[metrics.confidentiality]
    i = _IMPACT_WEIGHTS[metrics.integrity]
    a = _IMPACT_WEIGHTS[metrics.availability]

    iss = 1 - ((1 - c) * (1 - i) * (1 - a))
    exploitability = 8.22 * av * ac * pr * ui

    if changed:
        impact = 7.52 * (iss - 0.029) - 3.25 * ((iss - 0.02) ** 15)
    else:
        impact = 6.42 * iss

    if impact <= 0:
        return 0.0

    base = (impact + exploitability) * (1.08 if changed else 1.0)
    return _roundup(min(base, 10.0))


def severity_for_score(score: float) -> str:
    """Map a 0.0-10.0 base score to its CVSS v3.1 qualitative severity
    rating: none/low/medium/high/critical."""
    for low, high, label in _SEVERITY_BANDS:
        if low <= score <= high:
            return label
    raise Cvss31Error(f"CVSS score out of range: {score!r}")


def score_and_severity(vector: str) -> tuple[float, str]:
    """Parse a vector string and return (score, severity) — the one
    function callers outside this module should use."""
    metrics = parse_vector(vector)
    score = compute_score(metrics)
    return score, severity_for_score(score)


def score_and_severity_from_metrics(metrics: Cvss31Metrics) -> tuple[float, str]:
    """Same as score_and_severity(), for callers that already have parsed
    metrics (e.g. the pipeline, which receives Cvss31Metrics straight from
    the provider response)."""
    score = compute_score(metrics)
    return score, severity_for_score(score)
