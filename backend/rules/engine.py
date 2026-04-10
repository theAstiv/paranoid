"""Deterministic rule engine for threat pattern matching.

Extracts keywords from system descriptions, matches them against curated seed
patterns, and provides vector similarity retrieval for RAG context injection.
Runs independently of any LLM provider — no external API calls.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

from backend.models.enums import Framework, StrideCategory
from backend.models.state import Threat, ThreatsList


logger = logging.getLogger(__name__)

SEEDS_DIR = Path(__file__).parent.parent.parent / "seeds"

# Maps MAESTRO categories to the nearest STRIDE equivalent.
# Required because Threat.stride_category is a mandatory field in the pipeline's
# shared ThreatsList model, even when threats originate from MAESTRO patterns.
_MAESTRO_TO_STRIDE: dict[str, StrideCategory] = {
    "Model Security": StrideCategory.TAMPERING,
    "Data Security": StrideCategory.INFORMATION_DISCLOSURE,
    "LLM Security": StrideCategory.ELEVATION_OF_PRIVILEGE,
    "Privacy": StrideCategory.INFORMATION_DISCLOSURE,
    "Supply Chain": StrideCategory.TAMPERING,
    "Resource Abuse": StrideCategory.DENIAL_OF_SERVICE,
    "Pipeline Security": StrideCategory.TAMPERING,
    "Reinforcement Learning": StrideCategory.TAMPERING,
    "Distributed ML": StrideCategory.TAMPERING,
    "Monitoring": StrideCategory.REPUDIATION,
    "Interpretability": StrideCategory.INFORMATION_DISCLOSURE,
    "AutoML": StrideCategory.TAMPERING,
    "Fairness": StrideCategory.TAMPERING,
}

# Regex patterns for extracting security-relevant technology keywords.
# Each group targets a distinct domain so coverage is broad but precise.
_KEYWORD_PATTERNS: list[str] = [
    # Authentication & session management
    r"\b(auth(?:entication|orization)?|jwt|oauth|saml|openid|sso|mfa|2fa|ldap|session|token|cookie|password|credential|api[ -]?key)\b",
    # Databases
    r"\b(sql|mysql|postgresql|postgres|sqlite|oracle|mssql|nosql|mongodb|redis|cassandra|dynamodb|elasticsearch|neo4j)\b",
    # Network protocols & transport security
    r"\b(http[s]?|rest(?:ful)?|grpc|graphql|websocket|mqtt|amqp|smtp|ftp|sftp|ssh|tls|ssl|cert(?:ificate)?|dns)\b",
    # Cloud & infrastructure
    r"\b(s3|aws|azure|gcp|cloud|docker|kubernetes|k8s|lambda|cdn|load[ -]?balancer|firewall|vpn|vpc)\b",
    # ML/AI specific
    r"\b(model|ml|ai|llm|gpt|neural|training|inference|embedding|vector|dataset|rag|fine[ -]?tun(?:e|ing)|prompt)\b",
    # Application architecture
    r"\b(web|mobile|api|microservice|monolith|serverless|queue|message[ -]?broker|file[ -]?storage|upload|download|admin)\b",
    # Cryptography & key management
    r"\b(encrypt(?:ion|ed)?|decrypt(?:ion)?|hash(?:ing)?|sign(?:ature)?|key[ -]?management|secret|private[ -]?key|public[ -]?key)\b",
    # Access control
    r"\b(role|permission|privilege|access[ -]?control|rbac|abac|acl|sudo|root)\b",
    # Managed identity & auth providers
    r"\b(auth0|clerk|cognito|firebase|supabase|okta|keycloak|identity[ -]?provider|magic[ -]?link|passkey)\b",
    # ORMs & query builders
    r"\b(prisma|sqlalchemy|mongoose|drizzle|sequelize|typeorm|hibernate|activerecord|orm)\b",
    # Cloud messaging & object storage services
    r"\b(sqs|sns|pub[ -]?sub|pubsub|blob[ -]?storage|gcs|kinesis|eventbridge|event[ -]?hub)\b",
    # Web frameworks
    r"\b(django|fastapi|express(?:js)?|rails|next(?:js|[ -]js)?|flask|spring(?:boot)?|laravel|nuxt)\b",
    # Message brokers & stream processors
    r"\b(kafka|rabbitmq|redis[ -]?stream|celery|bullmq|sidekiq|nats|pulsar)\b",
    # Container & IaC infrastructure
    r"\b(nginx|terraform|helm|istio|envoy|ingress|etcd|vault|consul|ansible)\b",
    # AI/LLM tooling & vector stores
    r"\b(langchain|pinecone|weaviate|qdrant|chroma(?:db)?|milvus|vector[ -]?store|vector[ -]?db|embedding[ -]?model)\b",
    # Serialization, deserialization & data formats
    r"\b(serial(?:iz(?:ation|e|ed))?|deserializ(?:ation|e|ed)|pickle|protobuf|avro|thrift|msgpack|yaml|xml|json(?:p)?|soap)\b",
    # Supply chain & dependency management
    r"\b(npm|pypi|maven|nuget|cargo|gem|package[ -]?lock|dependency|supply[ -]?chain|update[ -]?server|artifact)\b",
    # Deep link, mobile & URL scheme
    r"\b(deep[ -]?link|url[ -]?scheme|universal[ -]?link|app[ -]?link|intent|broadcast|webview)\b",
    # Network & protocol attack surface
    r"\b(arp|dhcp|bgp|ospf|ntp|snmp|icmp|ssrf|crlf|rfi|lfi|xxe|ssi|dn[s]?[ -]?rebind)\b",
    # Browser & client-side security
    r"\b(browser|extension|addon|plugin|iframe|cors|csp|sri|hsts|same[-]?origin|cookie[ -]?flag)\b",
    # AWS service identifiers (EC2, RDS, EKS, KMS, etc.)
    r"\b(ec2|rds|eks|ecs|fargate|sagemaker|bedrock|glue|athena|redshift|elasticache|aurora|cloudfront|route53|guardduty|securityhub|cloudtrail|cloudwatch|codecommit|codepipeline|codebuild|codeartifact|kms)\b",
    # Azure service identifiers (AKS, Entra, Key Vault, Storage Account, etc.)
    r"\b(aks|entra|app[-\s]?service|key[-\s]?vault|azure[-\s]?sql|azure[-\s]?ad|function[-\s]?app|azure[-\s]?container|azure[-\s]?devops|acr|ado|storage[-\s]?account)\b",
    # GCP service identifiers (GKE, Cloud SQL, Cloud Storage, Compute Engine, etc.)
    r"\b(gke|cloud[-\s]?sql|cloud[-\s]?run|cloud[-\s]?function|vertex[-\s]?ai|stackdriver|bigquery|cloud[-\s]?armor|cloud[-\s]?build|cloud[-\s]?spanner|cloud[-\s]?storage|compute[-\s]?engine|compute[-\s]?instance)\b",
    # CI/CD pipeline security (T1677 Poisoned Pipeline Execution)
    r"\b(ci[-/]?cd|github[-\s]?action|gitlab[-\s]?ci|jenkins|circleci|travis|buildkite|tekton|argo[-\s]?cd|artifact[-\s]?registry|ecr|ghcr|container[-\s]?registry)\b",
    # Cloud identity & federation attack surface (T1552.005, T1606.002, T1548.005)
    r"\b(imds|metadata[-\s]?api|instance[-\s]?metadata|federation|workload[-\s]?identity|oidc[-\s]?token|assume[-\s]?role|cross[-\s]?account|service[-\s]?principal|managed[-\s]?identity)\b",
]


def extract_keywords(description: str) -> set[str]:
    """Extract security-relevant technology keywords from a system description.

    Args:
        description: System description text

    Returns:
        Set of lowercase keyword matches
    """
    text = description.lower()
    keywords: set[str] = set()

    for pattern in _KEYWORD_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        keywords.update(m.lower().strip() for m in matches)

    return keywords


def _load_seed_patterns() -> list[dict[str, Any]]:
    """Load all seed patterns from JSON files on disk.

    Returns:
        Combined list of all seed pattern dicts
    """
    all_patterns: list[dict[str, Any]] = []

    for filename in (
        "stride_patterns.json",
        "maestro_patterns.json",
        "owasp_llm_top10.json",
        "auth_provider_patterns.json",
        "orm_patterns.json",
        "cloud_service_patterns.json",
        "framework_patterns.json",
        "message_broker_patterns.json",
        "infrastructure_patterns.json",
        "ai_llm_patterns.json",
        "capec_patterns.json",
        "aws_prowler_patterns.json",
        "azure_prowler_patterns.json",
        "gcp_prowler_patterns.json",
        "attack_cloud_patterns.json",
        "atlas_patterns.json",
    ):
        path = SEEDS_DIR / filename
        if not path.exists():
            logger.warning(f"Seed file not found: {path}")
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                all_patterns.extend(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load seed file {path}: {e}")

    return all_patterns


def _score_pattern(pattern: dict[str, Any], keywords: set[str]) -> int:
    """Score a seed pattern's relevance against extracted keywords.

    Counts how many extracted keywords appear in the pattern's name,
    description, and target fields.

    Args:
        pattern: Seed pattern dictionary
        keywords: Extracted keywords from system description

    Returns:
        Integer relevance score (0 = no match)
    """
    searchable = " ".join(
        [
            pattern.get("name", ""),
            pattern.get("description", ""),
            pattern.get("target", ""),
        ]
    ).lower()

    return sum(1 for kw in keywords if kw in searchable)


def _pattern_to_threat(pattern: dict[str, Any], framework: Framework) -> Threat | None:
    """Convert a seed pattern dict to a Threat model instance.

    MAESTRO-only patterns are mapped to the nearest STRIDE category to satisfy
    the pipeline's shared ThreatsList model requirements.

    Args:
        pattern: Seed pattern dict from seeds/*.json
        framework: Active threat modeling framework

    Returns:
        Threat instance, or None if conversion fails
    """
    try:
        raw_stride = pattern.get("stride_category")
        if raw_stride:
            try:
                stride_cat = StrideCategory(raw_stride)
            except ValueError:
                stride_cat = StrideCategory.TAMPERING
        else:
            maestro_cat = pattern.get("maestro_category", "")
            stride_cat = _MAESTRO_TO_STRIDE.get(maestro_cat, StrideCategory.TAMPERING)

        return Threat(
            name=pattern["name"],
            stride_category=stride_cat,
            description=pattern["description"],
            target=pattern.get("target", "System Component"),
            impact=pattern.get("impact", "Medium"),
            likelihood=pattern.get("likelihood", "Medium"),
            mitigations=pattern.get(
                "mitigations", ["Review security controls", "Apply defense in depth"]
            ),
        )
    except (KeyError, ValueError) as e:
        logger.warning(f"Skipping seed pattern '{pattern.get('name')}': {e}")
        return None


def match_patterns(
    description: str,
    framework: Framework,
    max_results: int = 10,
    min_score: int = 1,
) -> ThreatsList:
    """Match seed patterns against keywords extracted from the description.

    Loads seed patterns from disk, filters to framework-relevant ones, scores each
    by keyword overlap with the description, and returns the top matches as Threats.

    OWASP patterns carry both stride_category and maestro_category so they appear
    in results for both frameworks.

    Args:
        description: System description text
        framework: Active framework — filters which seed patterns are considered
        max_results: Maximum number of matched threats to return
        min_score: Minimum keyword match score to include a pattern

    Returns:
        ThreatsList of matched seed patterns (may be empty)
    """
    keywords = extract_keywords(description)
    if not keywords:
        logger.debug("No keywords extracted — rule engine returning empty result")
        return ThreatsList(threats=[])

    patterns = _load_seed_patterns()

    if framework == Framework.STRIDE:
        patterns = [p for p in patterns if p.get("stride_category")]
    elif framework == Framework.MAESTRO:
        patterns = [p for p in patterns if p.get("maestro_category")]
    # Framework.HYBRID: keep all patterns

    scored = [(p, _score_pattern(p, keywords)) for p in patterns]
    scored = [(p, s) for p, s in scored if s >= min_score]
    scored.sort(key=lambda x: x[1], reverse=True)

    threats = []
    for pattern, _ in scored[:max_results]:
        threat = _pattern_to_threat(pattern, framework)
        if threat is not None:
            threats.append(threat)

    logger.info(
        f"Rule engine: {len(threats)} patterns matched "
        f"({len(keywords)} keywords, framework={framework.value})"
    )
    return ThreatsList(threats=threats)


async def fetch_rag_context(
    description: str,
    assets_text: str = "",
    limit: int = 5,
    threshold: float = 0.7,
) -> list[str]:
    """Retrieve similar threats from the vector store for RAG prompt injection.

    Queries sqlite-vec for semantically similar seed/approved threats. Returns an
    empty list if the vector store is unavailable (seeds not loaded, DB not
    initialized, sqlite-vec extension missing).

    Args:
        description: System description used as the similarity query
        assets_text: Optional asset names appended to enrich the query
        limit: Maximum number of similar threats to retrieve
        threshold: Minimum cosine similarity score (0-1)

    Returns:
        List of formatted threat strings ready for injection into the LLM prompt
    """
    from backend.db.vectors import search_similar_threats

    query = f"{description} {assets_text}".strip()

    try:
        results = await search_similar_threats(
            query_text=query,
            limit=limit,
            threshold=threshold,
        )
    except Exception as e:
        logger.warning(f"RAG vector search failed (continuing without context): {e}")
        return []

    if not results:
        return []

    formatted = []
    for r in results:
        category = r.get("stride_category") or ""
        name = r.get("name") or ""
        desc = r.get("description") or ""
        header = f"**{name}** ({category})" if category else f"**{name}**"
        formatted.append(f"{header}\n{desc}" if desc else header)

    logger.debug(f"RAG context: {len(formatted)} similar threats retrieved")
    return formatted


def merge_rule_and_llm_threats(
    rule_threats: ThreatsList,
    llm_threats: ThreatsList,
    threshold: float = 0.85,
) -> ThreatsList:
    """Merge rule engine threats with LLM-generated threats, deduplicating by similarity.

    LLM threats take precedence. Rule engine threats semantically covered by LLM
    output are dropped; unique rule patterns are appended after.

    Args:
        rule_threats: Threats from the deterministic rule engine
        llm_threats: Threats generated by the LLM provider
        threshold: Cosine similarity threshold for dedup (0-1)

    Returns:
        Merged ThreatsList: LLM threats first, unique rule patterns appended
    """
    if not rule_threats.threats:
        return llm_threats
    if not llm_threats.threats:
        return rule_threats

    from backend.dedup import deduplicate_threats

    dedup_result = deduplicate_threats(
        new_threats=rule_threats,
        existing_threats=llm_threats,
        threshold=threshold,
    )

    if dedup_result.removed_count > 0:
        logger.info(
            f"Rule engine merge: {dedup_result.removed_count} patterns already covered by LLM, "
            f"{len(dedup_result.threats.threats)} unique patterns added"
        )

    return ThreatsList(threats=llm_threats.threats + dedup_result.threats.threats)


def run_rule_engine(
    description: str,
    framework: Framework,
    max_patterns: int = 10,
) -> ThreatsList:
    """Run the deterministic rule engine on a system description.

    No LLM calls. No database queries. Pure keyword extraction + JSON pattern matching.

    Args:
        description: System description text
        framework: Active threat modeling framework
        max_patterns: Cap on matched patterns returned

    Returns:
        ThreatsList of matched patterns (may be empty if no keywords extracted)
    """
    return match_patterns(description, framework, max_results=max_patterns)
