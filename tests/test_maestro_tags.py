"""MAESTRO applicability tagger (B2): keyword rules over asset name + description."""

import pytest

from backend.models.enums import MaestroCategory as C
from backend.pipeline.nodes.maestro_tags import applicable_categories, tag_asset


# (name, description, expected category). One positive per category.
_POSITIVE = [
    ("Fraud Classifier", "Gradient boosted model served for inference", C.MODEL_SECURITY),
    ("Training Data Lake", "Training dataset of labelled transactions", C.DATA_SECURITY),
    ("Support Chatbot", "LLM that answers customer questions with prompts", C.LLM_SECURITY),
    ("Customer Profile Store", "Holds PII and personal data used for personalisation", C.PRIVACY),
    ("Model Registry", "Pretrained weights downloaded from Hugging Face", C.SUPPLY_CHAIN),
    (
        "Inference API",
        "Token usage is billed per request; rate limit on GPU quota",
        C.RESOURCE_ABUSE,
    ),
    ("Training Pipeline", "MLOps pipeline that retrains and deploys models", C.PIPELINE_SECURITY),
    ("Reward Model", "Reward model used for RLHF fine-tuning", C.REINFORCEMENT_LEARNING),
    ("Federated Trainer", "Federated learning across hospital sites", C.DISTRIBUTED_ML),
    ("Drift Monitor", "Model monitoring that detects data drift", C.MONITORING),
    ("Explanation Service", "Explainability reports for each decision", C.INTERPRETABILITY),
    ("Tuning Job", "AutoML search over hyperparameters", C.AUTOML),
    ("Bias Auditor", "Checks fairness and disparate impact of scores", C.FAIRNESS),
]


@pytest.mark.parametrize(("name", "description", "expected"), _POSITIVE)
def test_tag_asset_matches_each_category(name, description, expected):
    assert expected in tag_asset(name, description)


def test_tag_asset_gpt_names_and_classification_models_from_real_extractions():
    # Seen untagged on saved loan-agent runs (10-15 review).
    assert C.LLM_SECURITY in tag_asset("GPT-4 Turbo Response Generator Model", "")
    assert C.LLM_SECURITY in tag_asset("Main agent", "Uses gpt-3.5-turbo for answers")
    assert C.MODEL_SECURITY in tag_asset("GPT-3.5-turbo Intent Classification Model", "")


def test_tag_asset_gpt_does_not_match_inside_other_words():
    assert tag_asset("Gptools", "gptq is not a word here and neither is gpts") == []


def test_tag_asset_agent_alone_does_not_imply_reinforcement_learning():
    assert C.REINFORCEMENT_LEARNING not in tag_asset("Loan Agent", "Agent that reviews loan files")


def test_tag_asset_matches_on_word_boundaries_only():
    # "llm" inside another word, "pii" inside "happiness", "rlhf" inside a token
    assert tag_asset("Callmanager", "happiness dashboard xrlhfx") == []


def test_tag_asset_is_case_insensitive():
    assert C.LLM_SECURITY in tag_asset("CHATBOT", "an LLM")


def test_tag_asset_unrelated_asset_has_no_categories():
    assert tag_asset("Postgres", "Relational database for orders") == []


def test_tag_asset_returns_enum_order_without_duplicates():
    tags = tag_asset("Model", "model model LLM llm training data")
    assert tags == sorted(set(tags), key=list(C).index)


def test_applicable_categories_is_union_in_enum_order():
    assets = [
        ("Support Chatbot", "LLM assistant"),
        ("Fraud Classifier", "ML model inference"),
        ("Postgres", "orders database"),
    ]
    assert applicable_categories(assets) == [C.MODEL_SECURITY, C.LLM_SECURITY]


def test_applicable_categories_empty_when_nothing_matches():
    assert applicable_categories([("Postgres", "orders database")]) == []
    assert applicable_categories([]) == []


# Hand-written expectations for the two shipped MAESTRO examples, taken from the
# example text before the tagger existed.
def test_rag_chatbot_example_applicable_set():
    # Asset names and descriptions from the "Assets" section of
    # examples/maestro-example-rag-chatbot.md, written down before running the tagger.
    assets = [
        ("RAG knowledge base", "product docs, policies, FAQs - 500K chunks"),
        ("Conversation history", "all customer interactions"),
        ("Embeddings", "vector representations of knowledge base"),
        ("System prompts", "confidential system prompts"),
        ("User queries", "contains PII"),
        ("OpenAI API keys", "$5K/month spend"),
        ("Embedding model weights", "ONNX - local"),
        ("Fine-tuned intent classifier", "gpt-3.5-turbo"),
        ("Monitoring dashboards", "Grafana"),
    ]
    got = set(applicable_categories(assets))
    assert {C.LLM_SECURITY, C.DATA_SECURITY, C.PRIVACY, C.MODEL_SECURITY} <= got
    assert not {C.REINFORCEMENT_LEARNING, C.DISTRIBUTED_ML, C.AUTOML, C.FAIRNESS} & got


@pytest.mark.parametrize(
    ("name", "description"),
    [
        ("SSO", "Federated identity via Okta SAML"),
        ("Docs", "Static analysis with type inference for TypeScript"),
        ("Web UI", "Prompts the user to confirm; tolerates clock drift"),
        ("Storage", "Per-tenant disk quota"),
        ("Orders DB", "dataset export and retrieval of orders"),
        ("Policy", "Fair use policy; selection bias is not discussed; automatic selection"),
        ("Gateway", "Parameters are tuned by ops; model of the building"),
    ],
)
def test_tag_asset_generic_words_in_non_ml_systems_do_not_match(name, description):
    assert tag_asset(name, description) == []


# --- coverage (pure) ---------------------------------------------------------


def _status(coverage, category):
    return next(c for c in coverage["categories"] if c["category"] == category.value)


def test_coverage_marks_covered_not_covered_and_na():
    from backend.pipeline.nodes.maestro_tags import maestro_coverage

    coverage = maestro_coverage(
        [["LLM Security", "Privacy"], []], {"LLM Security": 3, "Monitoring": 1}
    )

    assert coverage["assessed"] is True
    assert _status(coverage, C.LLM_SECURITY) == {
        "category": "LLM Security",
        "status": "covered",
        "threats": 3,
    }
    assert _status(coverage, C.PRIVACY)["status"] == "not_covered"
    assert _status(coverage, C.REINFORCEMENT_LEARNING)["status"] == "na"
    # Threats that exist always count, even when no component was tagged for them.
    assert _status(coverage, C.MONITORING)["status"] == "covered"
    assert [c["category"] for c in coverage["categories"]] == [c.value for c in C]


def test_coverage_is_not_assessed_when_no_asset_is_tagged():
    from backend.pipeline.nodes.maestro_tags import maestro_coverage

    for tags in ([], [None, None], [[], []]):
        coverage = maestro_coverage(tags, {"LLM Security": 2})
        assert coverage["assessed"] is False
        assert _status(coverage, C.LLM_SECURITY)["status"] == "covered"
        assert _status(coverage, C.PRIVACY)["status"] == "not_assessed"


# Written from examples/maestro-example-loan-agent.md (its "Assets" section) before
# running the tagger: an LLM with a policy RAG corpus and PII-bearing transcripts.
# Nothing there is reinforcement, federated or auto-tuned.
def test_loan_agent_example_applicable_set():
    assets = [
        ("Conversation transcripts", "PII-bearing conversation transcripts, 90-day retention"),
        (
            "Policy RAG corpus",
            "Confidential underwriting logic used for retrieval-augmented answers",
        ),
        (
            "System prompts and tool descriptions",
            "System prompt and tool schemas for the LLM agent",
        ),
        ("Anthropic API keys", "Credentials for the LLM provider, spend of about 40L per month"),
        ("CIBIL API key", "Credit bureau API credential"),
    ]
    got = applicable_categories(assets)
    assert {C.LLM_SECURITY, C.DATA_SECURITY, C.PRIVACY} <= set(got)
    assert not {C.REINFORCEMENT_LEARNING, C.DISTRIBUTED_ML, C.AUTOML, C.FAIRNESS} & set(got)


@pytest.mark.parametrize(
    ("name", "description"),
    [
        # Seen on a real loan-agent extraction (10-15 measurement): weak single-word signals.
        ("Experiment Tracking Metadata", "Logs of runs, metrics and Hyperparameters"),
        ("Feedback Loop Data", "Stale feedback can degrade model fairness over time"),
        ("Config", "fairness of the queue is round-robin; hyperparameter names are logged"),
    ],
)
def test_tag_asset_single_weak_words_do_not_make_automl_or_fairness_applicable(name, description):
    got = tag_asset(name, description)
    assert C.AUTOML not in got
    assert C.FAIRNESS not in got


def test_tag_asset_automl_and_fairness_still_match_explicit_phrases():
    assert C.AUTOML in tag_asset("Tuner", "hyperparameter tuning and AutoML search")
    assert C.FAIRNESS in tag_asset("Auditor", "runs bias mitigation and disparate impact checks")


def test_rules_version_changes_when_a_rule_changes(monkeypatch):
    from backend.pipeline.nodes import maestro_tags

    before = maestro_tags.rules_version()
    patched = {**maestro_tags._RULES, C.PRIVACY: (*maestro_tags._RULES[C.PRIVACY], "extra term")}
    monkeypatch.setattr(maestro_tags, "_RULES", patched)
    assert maestro_tags.rules_version() != before


# --- 10-15 live runs: categories the tagger missed (Supply Chain, Monitoring, Fairness)
# Asset names are from saved loan-agent / RAG extractions.
@pytest.mark.parametrize(
    ("name", "description", "expected"),
    [
        (
            "Build Pipeline",
            "GitHub Actions CI/CD that builds and pushes the container image",
            C.SUPPLY_CHAIN,
        ),
        ("Python Dependencies", "Packages pulled from PyPI and npm at build time", C.SUPPLY_CHAIN),
        ("Base Image", "Container registry image with the ML framework (PyTorch)", C.SUPPLY_CHAIN),
        ("SBOM", "Software supply chain inventory of third-party packages", C.SUPPLY_CHAIN),
        ("Monitoring Telemetry and Grafana Dashboards", "", C.MONITORING),
        ("CloudWatch Logs and Metrics", "Operational telemetry for all components", C.MONITORING),
        ("LLM Observability", "Traces of prompts and completions", C.MONITORING),
        ("Loan Decision Engine", "Makes automated credit decisions about applicants", C.FAIRNESS),
        ("Scoring Service", "Credit scoring and loan approval for retail applicants", C.FAIRNESS),
        ("Screening Agent", "Candidate screening and hiring decisions", C.FAIRNESS),
    ],
)
def test_tag_asset_matches_software_supply_chain_observability_and_decision_domains(
    name, description, expected
):
    assert expected in tag_asset(name, description)


@pytest.mark.parametrize(
    ("name", "description"),
    [
        ("Policy", "Fair use policy for the shared drive"),
        ("Invoices", "Quarterly audit of the invoice archive by finance"),
        ("Cards", "Credit card number and billing address"),
        ("People", "The hiring manager approves a new seat"),
        ("Supplier", "Supply of office chairs and the supplier portal"),
        ("Tool", "Runs npmx and mypypi helpers"),
        ("Web UI", "Shows a dashboard of orders"),
        # Audit logs are storage/compliance, not ML monitoring: these asset texts only
        # mention them (10-15 loan-agent re-run tagged both as Monitoring).
        ("User Profile Database", "Applicant profiles, loan history, KYC status and audit logs"),
        ("KMS Encryption Keys", "Keys whose use is written to the audit trail"),
    ],
)
def test_tag_asset_new_phrases_do_not_match_ordinary_words(name, description):
    assert tag_asset(name, description) == []
