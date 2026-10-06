"""Deterministic default CVSS v3.1 vectors for dependency-engine threats.

Mirrors `backend.rules.techniques.DEPENDENCY_RULE_TECHNIQUES`: a fixed table
keyed by the same `rule_id` strings `backend.deps.threats` already produces
for every finding. No LLM involved — the vector is a judgment call made once
here, and `backend.scoring.cvss31.score_and_severity()` derives the actual
score/severity from it deterministically (verified in
tests/test_pipeline_deps.py's TestDependencyThreatsCvssScoring against the
calculator, not asserted by hand).
"""

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
