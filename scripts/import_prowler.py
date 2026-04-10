#!/usr/bin/env python3
"""Convert Prowler check metadata JSONs to paranoid seed format.

Usage:
    python scripts/import_prowler.py /path/to/prowler/repo

Reads prowler/providers/{aws,azure,gcp,kubernetes}/services/**/*.metadata.json
and emits seeds/{provider}_prowler_patterns.json for each provider.

Expected yield with a fully-cloned Prowler repo:
    aws        ~300 patterns
    azure      ~150 patterns
    gcp        ~80 patterns
    kubernetes ~40 patterns

The pre-built seed files in seeds/*_prowler_patterns.json contain a curated
subset that has been hand-calibrated after the initial generation run (STRIDE
reclassifications, likelihood tuning, description edits). Running this script
will OVERWRITE those hand edits. Before regenerating, either:
  1. Diff the output against the existing files and selectively merge changes, or
  2. Accept that hand-calibrations will be lost and review the new output carefully.

License: Prowler is Apache 2.0; these generated seeds inherit that license.
"""

import json
import re
import sys
from pathlib import Path


# Maps (check type / category keywords) → STRIDE category.
# Priority order: specific ATT&CK TTP labels first, then category hints.
_STRIDE_RULES: list[tuple[str, str]] = [
    # ATT&CK TTPs embedded in CheckType
    ("credential access", "Spoofing"),
    ("initial access", "Spoofing"),
    ("privilege escalation", "Elevation of Privilege"),
    ("defense evasion", "Repudiation"),
    ("collection", "Information Disclosure"),
    ("exfiltration", "Information Disclosure"),
    ("impact", "Denial of Service"),
    ("persistence", "Tampering"),
    ("lateral movement", "Elevation of Privilege"),
    # Category-based inference
    ("internet-exposed", "Spoofing"),
    ("identity-access", "Spoofing"),
    ("authentication", "Spoofing"),
    ("encryption", "Information Disclosure"),
    ("data exposure", "Information Disclosure"),
    ("logging", "Repudiation"),
    ("forensics", "Repudiation"),
    ("monitoring", "Repudiation"),
    ("backup", "Denial of Service"),
    ("redundancy", "Denial of Service"),
    ("vulnerability", "Tampering"),
    ("infrastructure", "Tampering"),
    ("network reachability", "Spoofing"),
]

_SEVERITY_MAP: dict[str, str] = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "informational": "Low",
}

# Maps Prowler Severity to an approximate likelihood estimate.
# Prowler doesn't track likelihood directly; severity serves as a proxy —
# critical/high misconfigurations are more frequently targeted in the wild.
_SEVERITY_TO_LIKELIHOOD: dict[str, str] = {
    "critical": "High",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "informational": "Low",
}

# Service name → human-readable resource label
_SERVICE_LABELS: dict[str, str] = {
    # AWS
    "iam": "IAM",
    "s3": "S3 Bucket",
    "ec2": "EC2 Instance",
    "rds": "RDS Instance",
    "eks": "EKS Cluster",
    "lambda": "Lambda Function",
    "kms": "KMS Key",
    "cloudtrail": "CloudTrail Trail",
    "cloudwatch": "CloudWatch",
    "vpc": "VPC",
    "elb": "Load Balancer",
    "elbv2": "Application Load Balancer",
    "ecr": "ECR Repository",
    "ecs": "ECS",
    "sns": "SNS Topic",
    "sqs": "SQS Queue",
    "dynamodb": "DynamoDB Table",
    "elasticache": "ElastiCache Cluster",
    "secretsmanager": "Secrets Manager",
    "config": "AWS Config",
    "guardduty": "GuardDuty",
    "securityhub": "Security Hub",
    "waf": "WAF",
    "shield": "Shield",
    # Azure
    "storage": "Storage Account",
    "sql": "SQL Server",
    "keyvault": "Key Vault",
    "monitor": "Azure Monitor",
    "aks": "AKS Cluster",
    "appservice": "App Service",
    "functions": "Function App",
    "containerregistry": "Container Registry",
    # GCP
    "gcs": "Cloud Storage Bucket",
    "cloudsql": "Cloud SQL Instance",
    "gke": "GKE Cluster",
    "cloudlogging": "Cloud Logging",
    "cloudkms": "Cloud KMS",
    # Kubernetes
    "rbac": "Kubernetes RBAC",
    "networkpolicy": "Kubernetes Network Policy",
    "serviceaccount": "Kubernetes Service Account",
    "apiserver": "Kubernetes API Server",
    "pod": "Kubernetes Pod",
}


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting from description/risk/remediation text."""
    # Remove fenced code blocks
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Remove bold/italic
    text = re.sub(r"\*{1,2}(.*?)\*{1,2}", r"\1", text)
    # Remove inline code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove hyperlinks — keep the text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove bare URLs
    text = re.sub(r"https?://\S+", "", text)
    # Collapse list markers (bullet and numbered)
    text = re.sub(r"\n\s*[-*\d]+[.)]\s+", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _infer_stride(check: dict) -> str:
    """Infer STRIDE category from CheckType and Categories fields."""
    check_types = " ".join(check.get("CheckType", [])).lower()
    categories = " ".join(check.get("Categories", [])).lower()
    combined = check_types + " " + categories

    for keyword, stride in _STRIDE_RULES:
        if keyword in combined:
            return stride
    return "Tampering"


def _build_target(check: dict) -> str:
    """Build target string from provider + service name."""
    provider = check.get("Provider", "").lower()
    service = check.get("ServiceName", "").lower()

    provider_prefix = {
        "aws": "AWS",
        "azure": "Azure",
        "gcp": "GCP",
        "kubernetes": "Kubernetes",
    }.get(provider, provider.upper())

    label = _SERVICE_LABELS.get(service)
    if label:
        return f"{provider_prefix} {label}"

    # Fall back to parsing ResourceType (e.g. AwsEc2Instance → EC2 Instance)
    resource_type = check.get("ResourceType", "")
    if resource_type:
        clean = re.sub(r"^(Aws|Azure|Gcp|K8s|Kubernetes|[A-Za-z]+/)", "", resource_type)
        words = re.sub(r"([A-Z])", r" \1", clean).strip()
        return f"{provider_prefix} {words}"

    resource_group = check.get("ResourceGroup", service).title()
    return f"{provider_prefix} {resource_group}"


def _build_description(check: dict) -> str:
    """Build threat description from Description + Risk fields."""
    desc = _strip_markdown(check.get("Description", ""))
    risk = _strip_markdown(check.get("Risk", ""))

    parts = []
    if desc:
        parts.append(desc)
    if risk:
        parts.append(f"Risk: {risk}")

    return " ".join(parts) if parts else check.get("CheckTitle", "")


def _build_mitigations(check: dict) -> list[str]:
    """Build mitigations list from Remediation block."""
    mitigations: list[str] = []
    remediation = check.get("Remediation", {})
    rec = remediation.get("Recommendation", {})

    text = _strip_markdown(rec.get("Text", ""))
    if text:
        mitigations.append(text)

    url = rec.get("Url", "")
    if url:
        mitigations.append(f"See: {url}")

    # Include short CLI remediations when present
    cli = _strip_markdown(remediation.get("Code", {}).get("CLI", ""))
    if cli and len(cli) < 200:
        mitigations.append(f"CLI: {cli}")

    return mitigations or [
        "Follow the provider security baseline and CIS benchmark for this resource",
        "Apply least privilege and enable defence-in-depth controls",
    ]


def convert_check(check: dict) -> dict | None:
    """Convert a single Prowler check dict to seed pattern format."""
    try:
        title = check["CheckTitle"]
        if not title:
            return None
        severity = check.get("Severity", "medium").lower()
        return {
            "name": title,
            "stride_category": _infer_stride(check),
            "description": _build_description(check),
            "target": _build_target(check),
            "impact": _SEVERITY_MAP.get(severity, "Medium"),
            "likelihood": _SEVERITY_TO_LIKELIHOOD.get(severity, "Medium"),
            "mitigations": _build_mitigations(check),
        }
    except (KeyError, TypeError) as e:
        print(f"  Skipping {check.get('CheckID', '?')}: {e}", file=sys.stderr)
        return None


def import_prowler(prowler_root: Path) -> dict[str, list[dict]]:
    """Read all Prowler metadata JSONs and return per-provider pattern lists."""
    providers = ["aws", "azure", "gcp", "kubernetes"]
    results: dict[str, list[dict]] = {p: [] for p in providers}

    for provider in providers:
        services_path = prowler_root / "prowler" / "providers" / provider / "services"
        if not services_path.exists():
            print(f"[warn] provider path not found: {services_path}", file=sys.stderr)
            continue

        metadata_files = sorted(services_path.rglob("*.metadata.json"))
        print(f"{provider}: found {len(metadata_files)} checks", file=sys.stderr)

        for path in metadata_files:
            try:
                check = json.loads(path.read_text(encoding="utf-8"))
                pattern = convert_check(check)
                if pattern:
                    results[provider].append(pattern)
            except (json.JSONDecodeError, OSError) as e:
                print(f"  [error] {path.name}: {e}", file=sys.stderr)

    return results


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} /path/to/prowler", file=sys.stderr)
        sys.exit(1)

    prowler_root = Path(sys.argv[1]).resolve()
    if not prowler_root.exists():
        print(f"Error: path does not exist: {prowler_root}", file=sys.stderr)
        sys.exit(1)

    seeds_dir = Path(__file__).parent.parent / "seeds"
    seeds_dir.mkdir(exist_ok=True)

    results = import_prowler(prowler_root)

    for provider, patterns in results.items():
        if not patterns:
            continue
        patterns.sort(key=lambda p: p["name"])
        out = seeds_dir / f"{provider}_prowler_patterns.json"
        out.write_text(
            json.dumps(patterns, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Wrote {len(patterns)} {provider} patterns → {out}")


if __name__ == "__main__":
    main()
