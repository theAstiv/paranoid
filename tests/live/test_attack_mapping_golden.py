"""Golden-set precision check for backend.rules.techniques' embedding match.

Requires the real fastembed/bge-small model (downloaded from HuggingFace on
first use) and is excluded by default (`-m "not live"` in pyproject.toml).
Run explicitly:

    pytest -m live tests/live/test_attack_mapping_golden.py -v

No LLM/API key needed — this exercises the deterministic map_techniques
matcher only, not the pipeline. It is "live" because it needs network access
for the embedding model, not an LLM provider.

The expected technique per threat was drafted by Claude from the threat's
description and MUST be reviewed by a human with security judgment before
the precision number here is trusted (see arsenal-plan.md decision 4). The
bar starts at 0.6 (precision@3): below it, the UI labels matches
"suggested" rather than treating them as confident.

KNOWN STATE (measured 2026-10-05): this test currently FAILS at
precision@3 = 0.30, even with the cosine+keyword hybrid score in
backend.rules.techniques._hybrid_score (pure cosine alone measured 0.0).
Inspecting raw similarity scores (see PR discussion) shows this is a real
bge-small limitation on fine-grained MITRE sub-technique disambiguation —
e.g. T1078.004 "Valid Accounts: Cloud Accounts" scores within ~0.04 cosine
of a dozen sibling "cloud X" techniques — not a bug in the matcher. Left
failing deliberately (not softened to pass) so the gap stays visible;
candidate follow-ups: a larger/better embedding model, partial credit for
a correct parent technique when the exact sub-technique is missed, or
heavier keyword weighting. Per the arsenal-plan decision, matches ship as
"suggested" in the UI until this clears the bar.
"""

from dataclasses import dataclass

import pytest

from backend.models.state import Threat
from backend.rules.techniques import TOP_K, match_techniques


PRECISION_BAR = 0.6


@dataclass
class GoldenCase:
    threat: Threat
    expected_id: str


def _threat(name: str, stride_category: str, description: str, target: str) -> Threat:
    return Threat(
        name=name,
        stride_category=stride_category,
        description=description,
        target=target,
        impact="High",
        likelihood="Medium",
        mitigations=["Review and remediate", "Monitor for recurrence"],
    )


# Drafted by Claude from seeds/attack_cloud_patterns.json and
# seeds/atlas_patterns.json descriptions (paraphrased, not verbatim, so this
# is a genuine held-out test of the matcher rather than round-tripping the
# seed's own embedded ID). NEEDS HUMAN REVIEW before the precision number is
# trusted.
GOLDEN_SET: list[GoldenCase] = [
    GoldenCase(
        _threat(
            "Stolen cloud credentials used to log in",
            "Spoofing",
            "An attacker who obtained valid cloud IAM credentials through phishing "
            "or a leaked git commit authenticates to the cloud console as the "
            "legitimate user, bypassing MFA-less session controls.",
            "Cloud IAM Identity",
        ),
        "T1078.004",
    ),
    GoldenCase(
        _threat(
            "SSRF used to steal instance metadata credentials",
            "Information Disclosure",
            "A server-side request forgery vulnerability in a web app is used to "
            "fetch temporary IAM credentials from the cloud instance metadata "
            "service, granting the attacker the instance's permissions.",
            "Cloud Instance Metadata Service",
        ),
        "T1552.005",
    ),
    GoldenCase(
        _threat(
            "Bulk download of S3 bucket contents",
            "Information Disclosure",
            "An attacker with read access to cloud object storage downloads the "
            "entire bucket contents at high speed, exfiltrating database backups "
            "and configuration files.",
            "Cloud Object Storage",
        ),
        "T1530",
    ),
    GoldenCase(
        _threat(
            "Attacker spins up GPU instances to mine cryptocurrency",
            "Denial of Service",
            "An attacker with compute launch permissions creates many large GPU "
            "instances to mine cryptocurrency on the victim's cloud bill.",
            "Cloud Compute Service",
        ),
        "T1496.001",
    ),
    GoldenCase(
        _threat(
            "Privileged role attached to a backdoor account",
            "Elevation of Privilege",
            "An attacker with IAM write access attaches an administrator policy "
            "to an identity they control, escalating from limited to full access.",
            "Cloud IAM Role Management",
        ),
        "T1098.003",
    ),
    GoldenCase(
        _threat(
            "Malicious npm package found only in the published tarball",
            "Tampering",
            "A dependency's published npm tarball contains a file that does not "
            "exist anywhere in its public GitHub source repository, suggesting "
            "the package was tampered with after being built from source.",
            "npm Dependency",
        ),
        "T1195.002",
    ),
    GoldenCase(
        _threat(
            "Backdoored model published under a typosquatted name",
            "Spoofing",
            "An attacker publishes a malicious pretrained model to a public model "
            "hub under a name nearly identical to a popular legitimate model, "
            "hoping developers download the look-alike by mistake.",
            "Public AI Model Repository",
        ),
        "AML.T0010.003",
    ),
    GoldenCase(
        _threat(
            "Crafted inputs cause the model to misclassify",
            "Tampering",
            "An attacker crafts inputs with small, carefully chosen perturbations "
            "that cause an image classifier to produce an incorrect prediction "
            "with high confidence.",
            "ML Inference API",
        ),
        "AML.T0043",
    ),
    GoldenCase(
        _threat(
            "Repeated querying used to clone a proprietary model",
            "Information Disclosure",
            "An attacker submits a large volume of queries to a model's "
            "prediction API and uses the input-output pairs to train a cheap "
            "surrogate model that approximates the original.",
            "ML Inference API",
        ),
        "AML.T0048",
    ),
    GoldenCase(
        _threat(
            "Jailbreak prompt reveals the hidden system prompt",
            "Information Disclosure",
            "An attacker uses role-play framing and multi-turn manipulation to "
            "get an LLM to reveal or paraphrase its confidential system prompt.",
            "LLM System Prompt",
        ),
        "AML.T0056",
    ),
]


@pytest.mark.live
def test_golden_set_precision_at_k():
    hits = 0
    misses: list[str] = []
    for case in GOLDEN_SET:
        matches = match_techniques(case.threat)
        matched_ids = [m.id for m in matches[:TOP_K]]
        if case.expected_id in matched_ids:
            hits += 1
        else:
            misses.append(f"{case.threat.name!r}: expected {case.expected_id}, got {matched_ids}")

    precision = hits / len(GOLDEN_SET)
    message = (
        f"precision@{TOP_K} = {precision:.2f} ({hits}/{len(GOLDEN_SET)}); "
        f"bar = {PRECISION_BAR}. Misses:\n" + "\n".join(misses)
    )
    print(message)
    assert precision >= PRECISION_BAR, message
