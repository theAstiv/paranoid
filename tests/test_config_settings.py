"""Tests for Settings fields added in week 4a-2 (per-step model routing)."""

import pytest
from pydantic import ValidationError

from backend.config import Settings


@pytest.fixture(autouse=True)
def _clear_4a2_env(monkeypatch):
    """Settings() reads the real process env (and .env) by default. Clear
    the fields this file exercises so a developer's own .env / exported
    FAST_MODEL_OPENAI etc. can't change these tests' outcomes."""
    for var in ("FAST_MODEL_OPENAI", "FAST_MODEL_BEDROCK", "FAST_MODEL_OLLAMA", "STEP_MODELS"):
        monkeypatch.delenv(var, raising=False)


def _settings(**overrides) -> Settings:
    """Settings() ignoring any real .env file on disk, env-only otherwise."""
    return Settings(_env_file=None, **overrides)


def test_fast_model_per_provider_defaults():
    s = _settings()
    assert s.fast_model_openai == "gpt-4.1-mini"
    assert s.fast_model_bedrock == ""
    assert s.fast_model_ollama == ""


def test_step_models_default_empty():
    assert _settings().step_models == {}


def test_step_models_env_var_parsed_as_json(monkeypatch):
    monkeypatch.setenv("STEP_MODELS", '{"extract_flows": "main", "summarize": "fast"}')
    s = _settings()
    assert s.step_models == {"extract_flows": "main", "summarize": "fast"}


def test_step_models_rejects_invalid_choice(monkeypatch):
    monkeypatch.setenv("STEP_MODELS", '{"extract_flows": "slow"}')
    with pytest.raises(ValidationError, match="must be 'fast' or 'main'"):
        _settings()


def test_step_models_rejects_unknown_step_name(monkeypatch):
    monkeypatch.setenv("STEP_MODELS", '{"extract_flow": "main"}')
    with pytest.raises(ValidationError, match="Unknown pipeline step"):
        _settings()


def test_step_models_rejects_forbidden_fast_step_at_startup(monkeypatch):
    """Must fail at Settings() construction, not on the first pipeline run —
    a bad STEP_MODELS value should never reach a live run and fail there."""
    monkeypatch.setenv("STEP_MODELS", '{"generate_threats": "fast"}')
    with pytest.raises(ValidationError, match="can never be routed to the fast model"):
        _settings()


def test_valid_pipeline_steps_matches_llm_calling_steps():
    """backend.config duplicates the routable (LLM-calling) step names as
    plain strings to avoid a circular import (backend.pipeline.runner
    imports `settings` from backend.config at module load). Guard against
    the two drifting apart. Deliberately narrower than the full PipelineStep
    enum — rule_engine/iterate/complete/analyze_dependencies never reach a
    provider, so STEP_MODELS must reject them rather than silently no-op."""
    from backend.config import _FORBIDDEN_FAST_STEP_NAMES, _VALID_PIPELINE_STEPS
    from backend.pipeline.runner import _DEFAULT_STEP_MODELS, FORBIDDEN_FAST_STEPS

    assert {s.value for s in _DEFAULT_STEP_MODELS} == _VALID_PIPELINE_STEPS
    assert {s.value for s in FORBIDDEN_FAST_STEPS} == _FORBIDDEN_FAST_STEP_NAMES


def test_step_models_rejects_non_llm_step_name(monkeypatch):
    """rule_engine never calls an LLM, so a STEP_MODELS entry for it would
    silently do nothing — reject it instead of accepting dead config."""
    monkeypatch.setenv("STEP_MODELS", '{"rule_engine": "main"}')
    with pytest.raises(ValidationError, match="Unknown pipeline step"):
        _settings()
