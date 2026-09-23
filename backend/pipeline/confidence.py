"""Confidence scoring for generated threats.

Scores each threat by how well-grounded it is in the system description,
identified assets, and data flows. Pure computation — no LLM calls.
"""

from __future__ import annotations

import re
from typing import Any

from backend.models.state import Threat


_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "need",
        "must",
        "ought",
        "and",
        "but",
        "or",
        "nor",
        "not",
        "so",
        "yet",
        "both",
        "either",
        "neither",
        "each",
        "every",
        "all",
        "any",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "only",
        "own",
        "same",
        "than",
        "too",
        "very",
        "just",
        "because",
        "as",
        "until",
        "while",
        "of",
        "at",
        "by",
        "for",
        "with",
        "about",
        "against",
        "between",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "to",
        "from",
        "up",
        "down",
        "in",
        "out",
        "on",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "they",
        "them",
        "their",
        "we",
        "our",
        "you",
        "your",
        "he",
        "him",
        "his",
        "she",
        "her",
        "if",
        "into",
        "which",
        "what",
        "who",
        "whom",
    }
)

_WORD_RE = re.compile(r"[a-zA-Z0-9_\-]+")


def _tokenize(text: str) -> set[str]:
    """Extract significant lowercase tokens (3+ chars, not stopwords)."""
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) >= 3 and w not in _STOPWORDS}


def _asset_match_score(threat_target: str, assets: list[dict[str, Any]]) -> float:
    """Score how well the threat target matches identified assets.

    Returns 1.0 for exact substring match, 0.5 for token overlap, 0.0 otherwise.
    """
    if not assets:
        return 0.0

    target_lower = threat_target.lower()
    target_tokens = _tokenize(threat_target)

    for asset in assets:
        asset_name = (asset.get("name") or "").lower()
        if not asset_name:
            continue
        if asset_name in target_lower or target_lower in asset_name:
            return 1.0

    if not target_tokens:
        return 0.0

    best_overlap = 0.0
    for asset in assets:
        asset_tokens = _tokenize(asset.get("name") or "")
        if not asset_tokens:
            continue
        overlap = len(target_tokens & asset_tokens) / max(len(target_tokens), len(asset_tokens))
        best_overlap = max(best_overlap, overlap)

    return min(best_overlap * 2, 1.0) * 0.5 if best_overlap > 0 else 0.0


def _flow_reference_score(threat_description: str, flows: list[dict[str, Any]]) -> float:
    """Score how many data flows the threat description references."""
    if not flows:
        return 0.0

    desc_tokens = _tokenize(threat_description)
    if not desc_tokens:
        return 0.0

    matched = 0
    for flow in flows:
        flow_terms = set()
        for field in ("source_entity", "target_entity", "flow_description"):
            flow_terms |= _tokenize(flow.get(field) or "")
        if desc_tokens & flow_terms:
            matched += 1

    if matched >= 2:
        return 1.0
    if matched == 1:
        return 0.6
    return 0.0


def _description_grounding_score(threat_description: str, system_description: str) -> float:
    """Score how many system description terms appear in the threat."""
    sys_tokens = _tokenize(system_description)
    if not sys_tokens:
        return 0.0

    threat_tokens = _tokenize(threat_description)
    if not threat_tokens:
        return 0.0

    matched = len(threat_tokens & sys_tokens)
    return min(matched / max(len(threat_tokens) * 0.4, 1), 1.0)


def _specificity_score(threat_description: str) -> float:
    """Penalize generic/boilerplate threats."""
    words = threat_description.split()
    if len(words) < 10:
        return 0.0

    tech_indicators = {
        "api",
        "sql",
        "xss",
        "csrf",
        "jwt",
        "oauth",
        "tls",
        "ssl",
        "http",
        "https",
        "dns",
        "tcp",
        "udp",
        "ssh",
        "rpc",
        "grpc",
        "redis",
        "kafka",
        "s3",
        "lambda",
        "iam",
        "vpc",
        "ec2",
        "rds",
        "docker",
        "kubernetes",
        "k8s",
        "nginx",
        "postgres",
        "mysql",
        "mongodb",
        "sqlite",
        "graphql",
        "rest",
        "websocket",
        "ldap",
        "saml",
        "oidc",
        "rbac",
        "acl",
        "cors",
        "csp",
        "hsts",
        "injection",
        "overflow",
        "deserialization",
        "xxe",
        "ssrf",
        "idor",
        "privilege",
        "escalation",
        "exfiltration",
        "encryption",
        "certificate",
        "token",
        "session",
        "cookie",
        "header",
        "payload",
        "endpoint",
        "middleware",
        "firewall",
        "proxy",
    }

    desc_lower = threat_description.lower()
    tech_count = sum(1 for term in tech_indicators if term in desc_lower)

    if tech_count >= 3:
        return 1.0
    if tech_count >= 1:
        return 0.7
    return 0.3


def score_threat_confidence(
    threat: Threat,
    assets: list[dict[str, Any]],
    flows: list[dict[str, Any]],
    description: str,
) -> float:
    """Score how well-grounded a threat is in the system input.

    Args:
        threat: The generated Threat object.
        assets: Asset dicts from crud.list_assets().
        flows: Flow dicts from crud.list_flows().
        description: The system description text.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    if threat.source == "rule_engine":
        return 0.85

    asset_score = _asset_match_score(threat.target, assets)
    flow_score = _flow_reference_score(threat.description, flows)
    grounding_score = _description_grounding_score(threat.description, description)
    spec_score = _specificity_score(threat.description)

    weighted = asset_score * 0.30 + flow_score * 0.25 + grounding_score * 0.25 + spec_score * 0.20

    return round(min(max(weighted, 0.0), 1.0), 2)
