"""SARIF 2.1.0 export for GitHub Security integration.

SARIF (Static Analysis Results Interchange Format) is the standard format
for security findings in GitHub, GitLab, VS Code, and most CI systems.
"""

from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any

from pydantic import ValidationError

from backend.models.state import DependencyRef, DreadScore, TechniqueRef, Threat, ThreatsList
from backend.scoring.cvss31 import Cvss31Error, parse_vector, to_vector_string


_DREAD_COLUMNS = (
    "dread_damage",
    "dread_reproducibility",
    "dread_exploitability",
    "dread_affected_users",
    "dread_discoverability",
)


def threat_from_row(row: dict[str, Any]) -> Threat:
    """Rebuild a Threat from a flat DB row (crud.list_threats()) for SARIF.

    Shared by the web export route and `paranoid models export` so the two
    can't drift. Uses model_construct to skip validation — persisted
    descriptions may not meet the word-count constraint enforced at
    generation time — which also means nested fields stay whatever the row
    holds and unknown keys are silently dropped. Each nested field export_sarif
    reads is therefore converted here:

    - dependency_ref / attack_techniques come back as plain dicts; sarif.py's
      attribute access (`.package`, `.id`) would raise AttributeError.
    - cvss_vector is a DB column, not a Threat field: parsed back into `cvss`
      or the vector string is lost while cvss_score/cvss_severity survive.
    - DREAD is stored as five flat dread_* columns, not a nested `dread`:
      rebuilt only when all five are present, otherwise left None (a partial
      DREAD has no meaningful average). A row whose values fail DreadScore's
      0-10 bounds is exported without DREAD rather than dropped.
    """
    fields = dict(row)
    if fields.get("dependency_ref") is not None:
        fields["dependency_ref"] = DependencyRef.model_validate(fields["dependency_ref"])
    if fields.get("attack_techniques"):
        fields["attack_techniques"] = [
            TechniqueRef.model_validate(t) for t in fields["attack_techniques"]
        ]
    if fields.get("cvss_vector"):
        try:
            fields["cvss"] = parse_vector(fields["cvss_vector"])
        except Cvss31Error:
            pass
    if all(fields.get(col) is not None for col in _DREAD_COLUMNS):
        try:
            fields["dread"] = DreadScore(
                damage=fields["dread_damage"],
                reproducibility=fields["dread_reproducibility"],
                exploitability=fields["dread_exploitability"],
                affected_users=fields["dread_affected_users"],
                discoverability=fields["dread_discoverability"],
            )
        except ValidationError:
            pass
    return Threat.model_construct(**fields)


def export_sarif(
    threats: ThreatsList,
    model_id: str,
    framework: str,
    source_file: str | None = None,
    dependency_manifest_path: str = "package.json",
) -> dict[str, Any]:
    """Export threats to SARIF 2.1.0 format for GitHub Security integration.

    Args:
        threats: ThreatsList containing all threats
        model_id: Unique identifier for this threat model run
        framework: Framework used (STRIDE or MAESTRO)
        source_file: Optional path to the input file analyzed
        dependency_manifest_path: Repo-relative path to the package.json a
            dependency-sourced threat's physical location points at (see
            _build_locations). Defaults to "package.json" (repo root) — pass
            the real path (e.g. "apps/web/package.json") when the caller
            knows it, such as the CLI's --manifest flag, so results resolve
            correctly for a package that isn't at the repo root.

    Returns:
        SARIF 2.1.0 compliant dict ready for JSON serialization
    """
    # Map STRIDE/MAESTRO categories to SARIF rule IDs
    rules = _generate_rules(threats, framework)

    # Convert threats to SARIF results
    results = _generate_results(threats, source_file, dependency_manifest_path)

    # Build SARIF document
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Paranoid Threat Modeler",
                        "version": "1.1.0",
                        "informationUri": "https://github.com/theAstiv/paranoid",
                        "rules": rules,
                    }
                },
                "results": results,
                "automationDetails": {
                    "id": model_id,
                    "guid": model_id,
                },
                "columnKind": "utf16CodeUnits",
                "properties": {
                    "framework": framework,
                    "generatedAt": datetime.now(UTC).isoformat(),
                },
            }
        ],
    }

    return sarif


def _threat_category(threat: Any) -> str | None:
    """STRIDE or MAESTRO category for a threat, or None if neither is set."""
    if hasattr(threat, "stride_category"):
        return threat.stride_category
    if hasattr(threat, "maestro_category"):
        return threat.maestro_category
    return None


def _cvss_band(score: float) -> str | None:
    """CVSS v3.1 qualitative band for a score, or None for a score GitHub's
    security-severity doesn't accept (0.0, or no score at all — the two
    are handled the same way by the caller: no band means "use the plain
    per-category rule, no security-severity property")."""
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    if score > 0.0:
        return "low"
    return None


def _rule_key(threat: Any) -> tuple[str, str | None] | None:
    """(category, band) for a threat's rule — band is None when the threat
    has no CVSS score or a 0.0 one, routing it to the plain per-category
    rule with no security-severity. Returns None if the threat has neither
    a STRIDE nor MAESTRO category."""
    category = _threat_category(threat)
    if category is None:
        return None
    score = getattr(threat, "cvss_score", None)
    band = _cvss_band(score) if score is not None else None
    return (category, band)


def _rule_id_for_key(framework: str, category: str, band: str | None) -> str:
    """SARIF rule id for a (category, band) key — shared by _generate_rules
    and _generate_results so they can never drift apart."""
    base = f"{framework.lower()}/{_rule_id(category)}"
    return f"{base}/{band}" if band else base


def _generate_rules(threats: ThreatsList, framework: str) -> list[dict[str, Any]]:
    """Generate SARIF rules, one per (STRIDE/MAESTRO category, CVSS severity
    band) pair actually present, plus a plain per-category rule for threats
    with no CVSS score. A single rule per *category* (the original design)
    meant a 3.1-scored Tampering threat inherited "Critical" security-
    severity from an unrelated 9.8-scored Tampering threat, since GitHub
    reads that property from the rule a result points at, not the result
    itself, and every Tampering threat pointed at the same rule. Splitting
    by band fixes that: a threat's rule now reflects only the threats in
    its own band. Dependency-sourced threats carry a STRIDE/MAESTRO
    category too (see backend/deps/threats.py's MAESTRO-layer mapping), so
    they fall into the same per-category/band rules as any other threat —
    dependency_ref.rule_id is a separate, purely informational field on the
    *result* and is never itself a SARIF rule.
    """
    # (category, band) -> max score seen in that bucket. band is None for
    # the plain per-category rule (no score, or a 0.0 one) and never has an
    # entry here — only banded buckets carry a score.
    max_score_by_key: dict[tuple[str, str | None], float] = {}
    # Plain per-category keys that must get a rule even with no scored
    # threats in them (e.g. every threat in Spoofing is DREAD-only).
    plain_keys: set[tuple[str, str | None]] = set()

    for threat in threats.threats:
        key = _rule_key(threat)
        if key is None:
            continue
        category, band = key
        if band is None:
            plain_keys.add((category, None))
        else:
            score = threat.cvss_score
            max_score_by_key[key] = max(score, max_score_by_key.get(key, score))

    all_keys = set(max_score_by_key) | plain_keys
    category_metadata = _get_category_metadata(framework)

    rules = []
    for category, band in sorted(all_keys, key=lambda k: (k[0], k[1] or "")):
        metadata = category_metadata.get(category, {})
        properties = {
            "category": category,
            "framework": framework,
        }
        if band is not None:
            properties["security-severity"] = str(max_score_by_key[(category, band)])
            # Paired with security-severity per GitHub's code scanning docs.
            properties["tags"] = ["security"]
        # stride_category/maestro_category are str-mixin Enums on a threat
        # straight from the pipeline (not yet round-tripped through the DB,
        # where they'd already be plain strings). str() methods like
        # .lower() work fine on them, but Enum's __str__ wins over str's in
        # an f-string, so f"{category}" would bake "StrideCategory.SPOOFING"
        # into this dict — which, unlike `category` embedded directly in a
        # field a JSON encoder later serializes, never gets a second chance
        # to resolve to the plain value.
        category_name = getattr(category, "value", category)
        rule = {
            "id": _rule_id_for_key(framework, category, band),
            "name": f"{category_name} ({band.capitalize()})" if band else category_name,
            "shortDescription": {"text": metadata.get("short", f"{category} threat identified")},
            "fullDescription": {
                "text": metadata.get(
                    "full",
                    f"A {category} threat was identified during threat modeling analysis.",
                )
            },
            "help": {
                "text": metadata.get(
                    "help",
                    "Review the threat details and implement recommended mitigations.",
                ),
                "markdown": metadata.get("markdown", ""),
            },
            "defaultConfiguration": {
                "level": "warning",  # All threats are warnings by default
            },
            "properties": properties,
        }
        rules.append(rule)

    return rules


def _generate_results(
    threats: ThreatsList, source_file: str | None, dependency_manifest_path: str = "package.json"
) -> list[dict[str, Any]]:
    """Convert threats to SARIF results.

    Each threat becomes a SARIF result with severity, location, and fixes.
    """
    results = []

    for threat in threats.threats:
        # Determine category and rule ID. Mirrors _generate_rules()'s
        # (category, band) key via the shared _rule_id_for_key() helper, so
        # a result's ruleId always resolves to a rule that actually exists.
        if hasattr(threat, "stride_category"):
            category = threat.stride_category
            framework = "stride"
        elif hasattr(threat, "maestro_category"):
            category = threat.maestro_category
            framework = "maestro"
        else:
            category = "Unknown"
            framework = "unknown"

        score = getattr(threat, "cvss_score", None)
        band = _cvss_band(score) if score is not None else None
        rule_id = _rule_id_for_key(framework, category, band)

        # Map DREAD severity to SARIF level
        level = _severity_to_level(threat)

        message_text = threat.description
        dependency_ref = getattr(threat, "dependency_ref", None)
        if dependency_ref is not None and dependency_ref.file:
            # The physical location points at the consumer's package.json
            # (see _build_locations) since dependency_ref.file is a path
            # inside the *dependency's* own tree — surface it here as text
            # since it can't be a resolvable SARIF location in this repo.
            where = dependency_ref.file
            if dependency_ref.line:
                where += f":{dependency_ref.line}"
            message_text = f"{message_text}\n\nFound in {dependency_ref.package}@{dependency_ref.version} at {where}."

        # Build result
        result = {
            "ruleId": rule_id,
            "level": level,
            "message": {
                "text": message_text,
            },
            "locations": _build_locations(threat, source_file, dependency_manifest_path),
            "partialFingerprints": {
                "threatName": threat.name,
                "target": threat.target,
            },
            "properties": {
                "threatName": threat.name,
                "target": threat.target,
                "impact": threat.impact,
                "likelihood": threat.likelihood,
                "source": threat.source,
            },
        }

        dependency_ref = getattr(threat, "dependency_ref", None)
        if dependency_ref is not None:
            result["properties"]["dependencyRef"] = {
                "package": dependency_ref.package,
                "version": dependency_ref.version,
                "file": dependency_ref.file,
                "line": dependency_ref.line,
                "ruleId": dependency_ref.rule_id,
            }

        attack_techniques = getattr(threat, "attack_techniques", None)
        if attack_techniques:
            # "embedding" matches are similarity guesses measured well below
            # the project's accuracy bar (tests/live/test_attack_mapping_golden.py)
            # — tagged /suggested so a consumer (e.g. GitHub code scanning)
            # doesn't present them with the same confidence as a table/seed
            # match, which are deterministic lookups.
            result["properties"]["tags"] = [
                f"attack/{t.id}"
                if getattr(t, "method", "embedding") != "embedding"
                else f"attack/{t.id}/suggested"
                for t in attack_techniques
            ]

        # Add DREAD score if available
        if hasattr(threat, "dread") and threat.dread:
            result["properties"]["dread"] = {
                "damage": threat.dread.damage,
                "reproducibility": threat.dread.reproducibility,
                "exploitability": threat.dread.exploitability,
                "affected_users": threat.dread.affected_users,
                "discoverability": threat.dread.discoverability,
                "score": threat.dread.score,
            }

        # Add CVSS score if available. This is informational on the result —
        # GitHub code scanning does NOT read a result-level security-severity;
        # it only reads tool.driver.rules[].properties["security-severity"],
        # set per-rule in _generate_rules() from the max score across that
        # rule's threats.
        cvss_score = getattr(threat, "cvss_score", None)
        if cvss_score is not None:
            cvss_metrics = getattr(threat, "cvss", None)
            result["properties"]["cvss"] = {
                "vector": to_vector_string(cvss_metrics) if cvss_metrics else None,
                "score": cvss_score,
                "severity": getattr(threat, "cvss_severity", None),
            }

        # Add mitigations as fixes
        if threat.mitigations:
            result["fixes"] = _build_fixes(threat.mitigations)

        results.append(result)

    return results


def to_sarif_uri(path: PurePath | str) -> str:
    """Forward-slash form of a path for SARIF `artifactLocation.uri`.

    A URI reference never contains backslashes, and GitHub resolves it against
    the repo — a Windows `str(Path)` ("examples\\app\\system.md") matches nothing.
    """
    if isinstance(path, PurePath):
        return path.as_posix()
    return path.replace("\\", "/")


def _build_locations(
    threat: Any, source_file: str | None, dependency_manifest_path: str = "package.json"
) -> list[dict[str, Any]]:
    """Build SARIF location array.

    For threat models without code context, we create a logical location
    pointing to the threatened component. Dependency-sourced threats
    (threat.dependency_ref set) get a package-scoped logical location
    ("npm:pkg@version") plus a physical location on the consumer's own
    manifest (dependency_manifest_path) — deliberately NOT dependency_ref.file
    /line, which is a path inside the *dependency's* own source tree (e.g.
    "lib/index.js", or even literally "package.json" for an install-hook
    finding — the dependency's own manifest, not the user's). A SARIF viewer
    such as GitHub resolves a physicalLocation's uri against the consumer's
    repo, where that path either doesn't exist or coincidentally names an
    unrelated file — the consumer's own manifest is the one path that's
    always valid there and is genuinely where the dependency is declared.
    Defaults to the repo root ("package.json") when the caller doesn't know
    the manifest's real path (e.g. web uploads, which are pasted content with
    no filesystem path); the CLI's --manifest flag passes the real one, which
    matters for a monorepo package (e.g. "apps/web/package.json"). The
    dependency's own file:line survives in properties.dependencyRef and the
    result message for anyone reading the raw SARIF.

    The physical and logical parts share ONE location object. GitHub code
    scanning reads locations[0] and rejects the *entire* upload ("expected a
    physical location") if it has no physicalLocation, so a logical-only
    entry must never lead (verified by uploading a real CLI run).
    """
    dependency_ref = getattr(threat, "dependency_ref", None)
    if dependency_ref is not None:
        return [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": to_sarif_uri(dependency_manifest_path)},
                    "region": {"startLine": 1, "startColumn": 1},
                },
                "logicalLocations": [
                    {
                        "name": f"npm:{dependency_ref.package}@{dependency_ref.version}",
                        "kind": "module",
                    }
                ],
            }
        ]

    locations = []

    if source_file:
        # Physical location in the threat model input file
        locations.append(
            {
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": to_sarif_uri(source_file),
                    },
                    "region": {
                        "startLine": 1,
                        "startColumn": 1,
                    },
                }
            }
        )

    # Logical location for the threatened component
    locations.append(
        {
            "logicalLocations": [
                {
                    "name": threat.target,
                    "kind": "component",
                }
            ]
        }
    )

    return locations


def _build_fixes(mitigations: list[str]) -> list[dict[str, Any]]:
    """Convert mitigations to SARIF fixes.

    Each mitigation becomes a fix suggestion.
    """
    fixes = []
    for idx, mitigation in enumerate(mitigations, start=1):
        # Extract mitigation type if tagged (e.g., "[P]", "[D]", "[C]")
        mitigation_type = "Mitigation"
        clean_text = mitigation
        if mitigation.startswith("[P]"):
            mitigation_type = "Preventive"
            clean_text = mitigation[3:].strip()
        elif mitigation.startswith("[D]"):
            mitigation_type = "Detective"
            clean_text = mitigation[3:].strip()
        elif mitigation.startswith("[C]"):
            mitigation_type = "Containment"
            clean_text = mitigation[3:].strip()

        fix = {
            "description": {
                "text": f"{mitigation_type} {idx}: {clean_text}",
            },
        }
        fixes.append(fix)

    return fixes


def _score_to_level(score: float) -> str:
    """Map a 0-10 score (CVSS or DREAD average) to a SARIF level."""
    if score >= 7:  # Critical/High
        return "error"
    if score >= 4:  # Medium
        return "warning"
    return "note"  # Low


def _severity_to_level(threat: Any) -> str:
    """Map CVSS score, DREAD severity, or likelihood to SARIF level.

    SARIF levels: error, warning, note, none

    CVSS takes precedence when present (the thresholds in _score_to_level
    are CVSS's own high/medium cut points, 7.0/4.0, not DREAD's 7/4
    average-of-5 bands — they happen to share the same numbers but are
    independent scales).
    """
    cvss_score = getattr(threat, "cvss_score", None)
    if cvss_score is not None:
        return _score_to_level(cvss_score)

    # Try DREAD score next (average 0-10)
    if hasattr(threat, "dread") and threat.dread:
        return _score_to_level(threat.dread.score)

    # Fall back to likelihood
    likelihood = getattr(threat, "likelihood", "").lower()
    if likelihood in ("high", "very high"):
        return "error"
    if likelihood == "medium":
        return "warning"
    return "note"


def _rule_id(category: str) -> str:
    """Convert category name to valid SARIF rule ID.

    Example: "Information Disclosure" -> "information-disclosure"
    """
    return category.lower().replace(" ", "-").replace("_", "-")


def _get_category_metadata(framework: str) -> dict[str, dict[str, str]]:
    """Get metadata for STRIDE/MAESTRO categories."""
    if framework.upper() == "STRIDE":
        return {
            "Spoofing": {
                "short": "Identity spoofing threat",
                "full": "An attacker may impersonate a legitimate user, system, or service to gain unauthorized access.",
                "help": "Implement strong authentication, use cryptographic signatures, and verify all identity claims.",
                "markdown": "**Spoofing** involves impersonating users or systems. Mitigate with:\n- Multi-factor authentication\n- Certificate-based authentication\n- Digital signatures\n- Anti-spoofing protocols",
            },
            "Tampering": {
                "short": "Data tampering threat",
                "full": "An attacker may modify data, configuration, or communications without authorization.",
                "help": "Use integrity checks, digital signatures, access controls, and audit logging.",
                "markdown": "**Tampering** involves unauthorized modification. Mitigate with:\n- Cryptographic hashing\n- Digital signatures\n- Access control lists\n- Tamper-evident seals\n- Audit logging",
            },
            "Repudiation": {
                "short": "Action repudiation threat",
                "full": "A user may deny performing an action without sufficient audit evidence to prove otherwise.",
                "help": "Implement comprehensive logging, non-repudiation mechanisms, and audit trails.",
                "markdown": "**Repudiation** involves denying actions. Mitigate with:\n- Digital signatures\n- Audit logging\n- Timestamps\n- Secure log storage\n- Non-repudiation protocols",
            },
            "Information Disclosure": {
                "short": "Information disclosure threat",
                "full": "Sensitive information may be exposed to unauthorized parties through various attack vectors.",
                "help": "Encrypt data at rest and in transit, implement proper access controls, and minimize data exposure.",
                "markdown": "**Information Disclosure** involves data leaks. Mitigate with:\n- Encryption (TLS, AES)\n- Access controls\n- Data masking\n- Principle of least privilege\n- Secure key management",
            },
            "Denial of Service": {
                "short": "Denial of service threat",
                "full": "An attacker may prevent legitimate users from accessing resources or services.",
                "help": "Implement rate limiting, resource quotas, load balancing, and DDoS protection.",
                "markdown": "**Denial of Service** involves resource exhaustion. Mitigate with:\n- Rate limiting\n- Resource quotas\n- Load balancing\n- Traffic filtering\n- Auto-scaling\n- DDoS protection services",
            },
            "Elevation of Privilege": {
                "short": "Privilege escalation threat",
                "full": "An attacker may gain higher access privileges than originally granted.",
                "help": "Enforce least privilege, use role-based access control, and validate all privilege changes.",
                "markdown": "**Elevation of Privilege** involves unauthorized access escalation. Mitigate with:\n- Principle of least privilege\n- Role-based access control\n- Privilege separation\n- Input validation\n- Regular permission audits",
            },
        }
    # MAESTRO
    return {
        "Data Security": {
            "short": "AI/ML data security threat",
            "full": "Training data, models, or inference data may be compromised or poisoned.",
            "help": "Secure data pipelines, validate inputs, and protect model artifacts.",
            "markdown": "**Data Security** in AI/ML. Mitigate with:\n- Data validation\n- Access controls\n- Encryption\n- Secure data provenance",
        },
        # Add other MAESTRO categories as needed
    }
