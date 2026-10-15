"""Golden-set precision check for backend.rules.techniques' embedding match.

Requires the real fastembed/bge-small model (downloaded from HuggingFace on
first use) and is excluded by default (`-m "not live"` in pyproject.toml).
Run explicitly:

    pytest -m live tests/live/test_attack_mapping_golden.py -v

No LLM/API key needed — this exercises the deterministic map_techniques
matcher only, not the pipeline. It is "live" because it needs network access
for the embedding model, not an LLM provider.

The expected technique per threat was drafted by Claude from the threat's
description and reviewed by a human with security judgment on 2026-10-15
(see arsenal-plan.md decision 4). The bar is 0.6 (precision@3): below it,
the UI labels matches "suggested" rather than treating them as confident.

KNOWN STATE (human label review + re-run, 2026-10-15):
- All 10 labels kept after review against seeds/techniques/*.json
  (ATT&CK v19.2 + ATLAS). The 2026-10-05 corrections stand: case 9's label
  is AML.T0024.002 (AML.T0048 was wrong), parent-technique credit is
  flagged `(parent)` in the failure message, and `accept_alternates` is
  reviewed case by case.
- precision@3 = 0.70 (7/10): 5 exact, 2 credited to the parent technique,
  3 misses. 0.50 counting exact matches only. n = 10, so each case moves
  the number 10 points.
- The three misses are matcher weaknesses, not label errors:
  case 1 (stolen cloud credentials) -> T1606/T1606.001/T1535, expected
  T1078.004; case 6 (npm tarball-only file) -> AML.T0109 only, expected
  T1195.002; case 8 (crafted adversarial inputs) -> AML.T0048.004/
  AML.T0080.001/AML.T0031, expected AML.T0043 (the AML.T0015 alternate is
  no longer returned). Case 2 (SSRF to instance metadata) is a hit now.
- Catalog gap: T1195.001 (Compromise Software Dependencies and Development
  Tools) is not in the catalog (only cloud-tagged techniques plus an
  include list), so case 6 can't get the more precise label yet.
- Every embedding-sourced match ships as "suggested"
  (TechniqueRef.method == "embedding") regardless of this score, so a miss
  here is a quality gap, not a trust/labeling one.
"""

from dataclasses import dataclass, field

import pytest

from backend.models.state import Threat
from backend.rules.techniques import TOP_K, match_techniques


PRECISION_BAR = 0.6


def _parent_id(technique_id: str) -> str | None:
    """T1496.001 -> T1496, AML.T0010.003 -> AML.T0010; None if already top-level."""
    base, _, sub = technique_id.rpartition(".")
    return base if base and sub.isdigit() else None


@dataclass
class GoldenCase:
    threat: Threat
    expected_id: str
    # Alternate technique IDs accepted as correct for this specific threat
    # (a defensible different-but-reasonable read of the same description),
    # reviewed case by case — not a general escape hatch.
    accept_alternates: tuple[str, ...] = field(default_factory=tuple)


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
# seed's own embedded ID). Labels reviewed by a human on 2026-10-15.
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
        # AML.T0058 "Publish Poisoned Models" also fits: the attacker publishes
        # the backdoored model to the hub (reviewed 2026-10-15).
        accept_alternates=("AML.T0058",),
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
        # AML.T0015 "Evade AI Model" is a defensible read of the same
        # description (evasion vs. crafting the adversarial input itself) —
        # reviewed and accepted, not a blanket excuse.
        accept_alternates=("AML.T0015",),
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
        # AML.T0024.002 "Extract AI Model" is model extraction/cloning via
        # repeated queries. AML.T0048 is "External Harms" — unrelated; the
        # original label here was simply wrong (found in review).
        "AML.T0024.002",
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
            continue

        parent = _parent_id(case.expected_id)
        if parent is not None and parent in matched_ids:
            hits += 1
            misses.append(
                f"{case.threat.name!r}: expected {case.expected_id}, "
                f"got parent {parent} (credited) — got {matched_ids}"
            )
            continue

        accepted = set(case.accept_alternates) & set(matched_ids)
        if accepted:
            hits += 1
            misses.append(
                f"{case.threat.name!r}: expected {case.expected_id}, "
                f"got accepted alternate {sorted(accepted)} — got {matched_ids}"
            )
            continue

        misses.append(f"{case.threat.name!r}: expected {case.expected_id}, got {matched_ids}")

    precision = hits / len(GOLDEN_SET)
    message = (
        f"precision@{TOP_K} = {precision:.2f} ({hits}/{len(GOLDEN_SET)}); "
        f"bar = {PRECISION_BAR}. Notes/misses:\n" + "\n".join(misses)
    )
    print(message)
    assert precision >= PRECISION_BAR, message
