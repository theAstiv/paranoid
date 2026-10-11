"""Deterministic default CVSS v3.1 vectors for dependency-engine and
rule-engine threats.

Mirrors `backend.rules.techniques.DEPENDENCY_RULE_TECHNIQUES`: a fixed table
keyed by the same `rule_id` strings `backend.deps.threats` already produces
for every finding. No LLM involved — the vector is a judgment call made once
here, and `backend.scoring.cvss31.score_and_severity()` derives the actual
score/severity from it deterministically (verified in
tests/test_pipeline_deps.py's TestDependencyThreatsCvssScoring against the
calculator, not asserted by hand).

Rule-engine threats (seed patterns) get a vector derived from the pattern's
own STRIDE category, `impact` and `likelihood` by `rule_pattern_cvss_vector()`
below, so a `cvss` run no longer leaves them unscored.
"""

from backend.models.enums import StrideCategory


# rule_id -> CVSS v3.1 base vector. Each vector reflects the worst-case
# interpretation of the capability signal (e.g. an install-time hook can run
# arbitrary code with the install user's privileges), not a specific CVE —
# these are reviewable starting points, editable per threat like any other
# CVSS vector.
DEPENDENCY_RULE_CVSS_VECTORS: dict[str, str] = {
    # Tarball ships code not present in the declared GitHub source. This is
    # a provenance/verifiability signal, not confirmed malicious behavior —
    # scored as a tampering risk with low-to-moderate confidentiality/
    # integrity impact, not the full-impact vector a confirmed hook gets.
    "drift_signal": "AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:L/A:N",
    # A lifecycle hook appeared only in the published artifact: arbitrary
    # code execution, network-reachable (registry install), low complexity,
    # no privileges — but UI:R, not UI:N: a person has to actually run
    # `npm install` to trigger it (per week4-plan.md §4b-3's own example).
    "install_hook_added": "AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H",
    # Same shape, but the hook isn't new — same impact, same vector.
    "install_hook_present": "AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H",
    # Dynamic code loading/eval — runtime payload substitution, but needs
    # the package to actually be exercised (higher complexity than a
    # straightforward install hook) and scope is typically contained to
    # confidentiality/integrity, not full availability.
    "dynamic_code": "AV:N/AC:H/PR:N/UI:N/S:U/C:L/I:L/A:N",
    # Reads env vars + makes network calls: a credential-exfiltration
    # *shape*, not a confirmed exfiltration — information disclosure only.
    "network_environment": "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
    # Native/FFI code escapes the JS sandbox but requires local execution of
    # the host process (not remotely triggerable on its own) and typically
    # needs the package already loaded with some privilege — scope changed
    # because it affects components beyond the vulnerable one.
    "native_ffi": "AV:L/AC:H/PR:L/UI:N/S:C/C:H/I:H/A:H",
}


# STRIDE category -> the CVSS impact metrics it touches. Exploitability
# defaults to the worst case for a pattern with no system-specific evidence
# (network-reachable, no user interaction), like the dependency table above.
# Elevation of Privilege needs some foothold first, hence PR:L.
_STRIDE_IMPACT_AXES: dict[StrideCategory, tuple[str, ...]] = {
    StrideCategory.SPOOFING: ("C", "I"),
    StrideCategory.TAMPERING: ("I",),
    StrideCategory.REPUDIATION: ("I",),
    StrideCategory.INFORMATION_DISCLOSURE: ("C",),
    StrideCategory.DENIAL_OF_SERVICE: ("A",),
    StrideCategory.ELEVATION_OF_PRIVILEGE: ("C", "I", "A"),
}

# Seed `impact` -> magnitude on the touched axes. Low still maps to L, not N:
# all-N impact scores 0.0, which reads as "not a threat".
_IMPACT_MAGNITUDE: dict[str, str] = {"critical": "H", "high": "H", "medium": "L", "low": "L"}


def rule_pattern_cvss_vector(stride_category: StrideCategory, impact: str, likelihood: str) -> str:
    """Default CVSS v3.1 base vector for a rule-engine seed pattern.

    The seed's STRIDE category picks the C/I/A axes, its `impact` sets their
    magnitude, and a `likelihood` of Low raises attack complexity to AC:H.
    Repudiation is capped at I:L: losing an audit trail rarely means full
    integrity loss. Scope is always unchanged: a generic pattern has no
    evidence of crossing a security boundary, so Critical scores like High
    rather than reaching 10.0. Unknown impact strings score as Medium. Like the dependency table, these are reviewable starting points,
    editable per threat.
    """
    axes = _STRIDE_IMPACT_AXES.get(stride_category, ("I",))
    impact_key = impact.strip().lower()
    magnitude = _IMPACT_MAGNITUDE.get(impact_key, "L")
    if stride_category == StrideCategory.REPUDIATION:
        magnitude = "L"
    attack_complexity = "H" if likelihood.strip().lower() == "low" else "L"
    privileges = "L" if stride_category == StrideCategory.ELEVATION_OF_PRIVILEGE else "N"
    cia = {axis: (magnitude if axis in axes else "N") for axis in ("C", "I", "A")}
    return (
        f"AV:N/AC:{attack_complexity}/PR:{privileges}/UI:N/S:U"
        f"/C:{cia['C']}/I:{cia['I']}/A:{cia['A']}"
    )
