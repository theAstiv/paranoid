"""SARIF 2.1.0 export for GitHub Security integration.

SARIF (Static Analysis Results Interchange Format) is the standard format
for security findings in GitHub, GitLab, VS Code, and most CI systems.
"""

from datetime import UTC, datetime
from typing import Any

from backend.models.state import ThreatsList


def export_sarif(
    threats: ThreatsList,
    model_id: str,
    framework: str,
    source_file: str | None = None,
) -> dict[str, Any]:
    """Export threats to SARIF 2.1.0 format for GitHub Security integration.

    Args:
        threats: ThreatsList containing all threats
        model_id: Unique identifier for this threat model run
        framework: Framework used (STRIDE or MAESTRO)
        source_file: Optional path to the input file analyzed

    Returns:
        SARIF 2.1.0 compliant dict ready for JSON serialization
    """
    # Map STRIDE/MAESTRO categories to SARIF rule IDs
    rules = _generate_rules(threats, framework)

    # Convert threats to SARIF results
    results = _generate_results(threats, source_file)

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


def _generate_rules(threats: ThreatsList, framework: str) -> list[dict[str, Any]]:
    """Generate SARIF rules from unique threat categories.

    Each STRIDE/MAESTRO category becomes a rule with metadata.
    """
    # Collect unique categories
    categories = set()
    for threat in threats.threats:
        if hasattr(threat, "stride_category"):
            categories.add(threat.stride_category)
        elif hasattr(threat, "maestro_category"):
            categories.add(threat.maestro_category)

    # Define category metadata
    category_metadata = _get_category_metadata(framework)

    rules = []
    for category in sorted(categories):
        metadata = category_metadata.get(category, {})
        rule = {
            "id": f"{framework.lower()}/{_rule_id(category)}",
            "name": category,
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
            "properties": {
                "category": category,
                "framework": framework,
            },
        }
        rules.append(rule)

    return rules


def _generate_results(threats: ThreatsList, source_file: str | None) -> list[dict[str, Any]]:
    """Convert threats to SARIF results.

    Each threat becomes a SARIF result with severity, location, and fixes.
    """
    results = []

    for threat in threats.threats:
        # Determine category and rule ID
        if hasattr(threat, "stride_category"):
            category = threat.stride_category
            framework = "stride"
        elif hasattr(threat, "maestro_category"):
            category = threat.maestro_category
            framework = "maestro"
        else:
            category = "Unknown"
            framework = "unknown"

        rule_id = f"{framework}/{_rule_id(category)}"

        # Map DREAD severity to SARIF level
        level = _severity_to_level(threat)

        # Build result
        result = {
            "ruleId": rule_id,
            "level": level,
            "message": {
                "text": threat.description,
            },
            "locations": _build_locations(threat, source_file),
            "partialFingerprints": {
                "threatName": threat.name,
                "target": threat.target,
            },
            "properties": {
                "threatName": threat.name,
                "target": threat.target,
                "impact": threat.impact,
                "likelihood": threat.likelihood,
            },
        }

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

        # Add mitigations as fixes
        if threat.mitigations:
            result["fixes"] = _build_fixes(threat.mitigations)

        results.append(result)

    return results


def _build_locations(threat: Any, source_file: str | None) -> list[dict[str, Any]]:
    """Build SARIF location array.

    For threat models without code context, we create a logical location
    pointing to the threatened component.
    """
    locations = []

    if source_file:
        # Physical location in the threat model input file
        locations.append(
            {
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": source_file,
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


def _severity_to_level(threat: Any) -> str:
    """Map DREAD severity or likelihood to SARIF level.

    SARIF levels: error, warning, note, none
    """
    # Try DREAD score first (average 0-10)
    if hasattr(threat, "dread") and threat.dread:
        score = threat.dread.score
        if score >= 7:  # Critical/High
            return "error"
        if score >= 4:  # Medium
            return "warning"
        return "note"  # Low

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
