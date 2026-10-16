"""Tag assets with the MAESTRO categories they make applicable (B2).

Pure functions, no IO and no LLM call. The rules are deliberately conservative:
a miss only leaves a category out of the applicable set, while a false hit would
make the coverage guard (B3) force a pointless extra pass. A bare "agent" or
"model" is therefore not enough for the narrow categories. Rules live here, not
in seeds/, because the seed loader counts every seeds/*.json as a pattern file.
"""

import hashlib
import json
import re
from collections.abc import Iterable
from functools import lru_cache

from backend.models.enums import MaestroCategory as C


# Whole words/phrases, matched case-insensitively on word boundaries.
_RULES: dict[C, tuple[str, ...]] = {
    C.MODEL_SECURITY: (
        "ml model",
        "machine learning model",
        "classifier",
        "classification model",
        "model inference",
        "inference endpoint",
        "model weights",
        "fine-tuned",
        "fine tuned",
        "neural network",
        "embedding model",
        "model serving",
    ),
    C.DATA_SECURITY: (
        "training data",
        "training dataset",
        "feature store",
        "vector store",
        "vector database",
        "embeddings",
        "knowledge base",
        "rag corpus",
        "retrieval-augmented",
        "retrieval augmented",
    ),
    C.LLM_SECURITY: (
        "llm",
        "gpt",
        "large language model",
        "chatbot",
        "system prompt",
        "prompt injection",
        "prompt template",
        "prompt templates",
        "generative ai",
        "copilot",
        "rag",
    ),
    C.PRIVACY: (
        "pii",
        "personal data",
        "personally identifiable",
        "gdpr",
        "dpdpa",
        "user conversations",
        "conversation transcripts",
        "chat history",
        "customer profile",
    ),
    C.SUPPLY_CHAIN: (
        "pretrained",
        "pre-trained",
        "model registry",
        "model hub",
        "hugging face",
        "huggingface",
        "third-party model",
        "model provider",
        # Software supply chain: the rule engine and seeds file CI/CD poisoning,
        # ML-framework compromise and package attacks here too (10-15 live runs).
        "supply chain",
        "software supply chain",
        "ci/cd",
        "ci pipeline",
        "github actions",
        "build pipeline",
        "package registry",
        "npm",
        "pypi",
        "container image",
        "container registry",
        "base image",
        "sbom",
        "third-party package",
        "third-party packages",
        "third-party dependency",
        "third-party dependencies",
        "ml framework",
        "ai framework",
        "pytorch",
        "tensorflow",
        "langchain",
    ),
    C.RESOURCE_ABUSE: (
        "gpu",
        "token usage",
        "token budget",
        "inference cost",
        "gpu quota",
        "token quota",
        "per-token",
    ),
    C.PIPELINE_SECURITY: (
        "mlops",
        "training pipeline",
        "ml pipeline",
        "retrain",
        "retrains",
        "retraining",
        "model deployment",
        "feature pipeline",
    ),
    C.REINFORCEMENT_LEARNING: (
        "reinforcement learning",
        "rlhf",
        "reward model",
        "reward function",
        "policy gradient",
    ),
    C.DISTRIBUTED_ML: (
        "federated learning",
        "distributed training",
        "parameter server",
        "gradient aggregation",
    ),
    C.MONITORING: (
        "data drift",
        "model drift",
        "concept drift",
        "model monitoring",
        "model observability",
        "observability",
        "llm observability",
        "ai observability",
        "monitoring dashboard",
        "monitoring dashboards",
        "telemetry",
        "grafana",
        "prometheus",
        "anomaly detection",
    ),
    C.INTERPRETABILITY: (
        "explainability",
        "explainable ai",
        "interpretability",
        "model explanations",
        "feature attribution",
    ),
    C.AUTOML: (
        "automl",
        "hyperparameter tuning",
        "hyperparameter optimization",
        "hyperparameter search",
        "neural architecture search",
        "model selection pipeline",
    ),
    C.FAIRNESS: (
        "algorithmic bias",
        "model bias",
        "bias mitigation",
        "bias detection",
        "fairness metrics",
        "fairness testing",
        "fairness audit",
        "fairness constraints",
        "disparate impact",
        # Decision domains where fairness applies without the word "bias".
        "credit decision",
        "credit decisions",
        "credit scoring",
        "loan approval",
        "loan decision",
        "loan decisions",
        "lending decision",
        "lending decisions",
        "hiring decision",
        "hiring decisions",
        "candidate screening",
        "insurance underwriting",
    ),
}


def rules_version() -> str:
    """Short hash of the rule set. Stored by the startup backfill so saved models
    are re-tagged when a rule changes, not only when an asset is written."""
    payload = json.dumps({c.value: sorted(terms) for c, terms in _RULES.items()}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


_ENUM_ORDER = {category: i for i, category in enumerate(C)}


@lru_cache(maxsize=1)
def _compiled() -> tuple[tuple[C, re.Pattern[str]], ...]:
    compiled = []
    for category, terms in _RULES.items():
        alternation = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
        compiled.append((category, re.compile(rf"(?<![a-z0-9])(?:{alternation})(?![a-z0-9])")))
    return tuple(compiled)


def tag_asset(name: str, description: str = "") -> list[C]:
    """Categories one asset makes applicable, in enum order."""
    text = f"{name} {description}".lower()
    hits = [category for category, pattern in _compiled() if pattern.search(text)]
    return sorted(hits, key=_ENUM_ORDER.__getitem__)


def applicable_categories(assets: Iterable[tuple[str, str]]) -> list[C]:
    """Union of the categories of (name, description) pairs, in enum order."""
    found: set[C] = set()
    for name, description in assets:
        found.update(tag_asset(name, description))
    return sorted(found, key=_ENUM_ORDER.__getitem__)


def applicability_section(assets: Iterable[tuple[str, str]]) -> str:
    """Prompt text naming the applicable and not-applicable categories.

    Empty when no asset matched any rule: the rules are conservative, so "nothing
    matched" means "unknown", and the prompt must not tell the model that every
    category is out of scope.
    """
    applicable = applicable_categories(assets)
    if not applicable:
        return ""
    others = [c for c in C if c not in applicable]
    text = "Components in this system make these categories applicable: "
    text += ", ".join(c.value for c in applicable) + ".\n"
    if others:
        text += (
            "No matching component: "
            + ", ".join(c.value for c in others)
            + ". Do not invent components to fill these; "
            "use them only if the description clearly places a component there."
        )
    return text


def maestro_coverage(asset_tags: Iterable[list[str] | None], threat_counts: dict[str, int]) -> dict:
    """Covered / not covered / N/A per category for one model.

    A category with threats is "covered" whatever the tags say. Otherwise it is
    "not_covered" when some asset made it applicable and "na" when it did not.
    If no asset has any tag, applicability is unknown: those categories are
    "not_assessed" rather than "na", which would claim something we can't back.
    """
    applicable = {name for tags in asset_tags if tags for name in tags}
    assessed = bool(applicable)
    categories = []
    for category in C:
        count = threat_counts.get(category.value, 0)
        if count:
            status = "covered"
        elif category.value in applicable:
            status = "not_covered"
        else:
            status = "na" if assessed else "not_assessed"
        categories.append({"category": category.value, "status": status, "threats": count})
    return {"assessed": assessed, "categories": categories}
