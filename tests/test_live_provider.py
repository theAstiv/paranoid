"""Provider selection for the live suites (`tests/live/_provider.py`). No network."""

import sys
from types import SimpleNamespace

import pytest

import tests.live._provider as live


def test_defaults_to_direct_anthropic_with_default_model():
    assert live.resolve_live_target({"DEFAULT_MODEL": "claude-sonnet-5-5"}) == (
        "anthropic",
        "claude-sonnet-5-5",
    )


def test_slot_name_resolves_provider_and_model_from_bench_env():
    env = {"BENCH_LIVE_MODEL": "SONNET_55", "BENCH_MODEL_SONNET_55": "us.anthropic.sonnet-55"}
    assert live.resolve_live_target(env) == ("bedrock", "us.anthropic.sonnet-55")


def test_unconfigured_slot_skips_with_a_reason():
    provider, model = live.resolve_live_target({"BENCH_LIVE_MODEL": "SONNET_55"})
    assert (provider, model) == ("bedrock", "")
    assert "BENCH_LIVE_MODEL" in live.skip_reason(provider, model, {})


def test_raw_model_id_with_explicit_provider():
    env = {"BENCH_LIVE_PROVIDER": "Bedrock", "BENCH_LIVE_MODEL": "us.anthropic.x"}
    assert live.resolve_live_target(env) == ("bedrock", "us.anthropic.x")


def test_misspelt_provider_fails_loudly():
    with pytest.raises(ValueError, match="BENCH_LIVE_PROVIDER"):
        live.resolve_live_target({"BENCH_LIVE_PROVIDER": "bedrok"})


@pytest.mark.parametrize("key", ["", "sk-ant-xxx-placeholder"])
def test_anthropic_without_a_real_key_skips(key):
    assert "ANTHROPIC_API_KEY" in live.skip_reason("anthropic", "m", {"ANTHROPIC_API_KEY": key})


def test_anthropic_with_a_key_runs():
    assert live.skip_reason("anthropic", "m", {"ANTHROPIC_API_KEY": "sk-ant-real"}) is None


def _fake_boto3(monkeypatch, *, credentials, region):
    session = SimpleNamespace(get_credentials=lambda: credentials, region_name=region)
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(Session=lambda **_: session))


def test_bedrock_without_credentials_skips(monkeypatch):
    _fake_boto3(monkeypatch, credentials=None, region="us-east-2")
    assert "credentials" in live.skip_reason("bedrock", "m", {})


def test_bedrock_without_a_region_skips(monkeypatch):
    _fake_boto3(monkeypatch, credentials=object(), region=None)
    assert "AWS_REGION" in live.skip_reason("bedrock", "m", {})


def test_bedrock_with_credentials_and_region_runs(monkeypatch):
    _fake_boto3(monkeypatch, credentials=object(), region=None)
    assert live.skip_reason("bedrock", "m", {"AWS_REGION": "us-east-2"}) is None


@pytest.fixture
def captured(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(live, "create_provider", lambda **kw: calls.append(kw) or kw)
    return calls


def test_bedrock_gets_region_profile_and_effort_but_no_timeout(captured):
    env = {"AWS_REGION": "us-east-2", "AWS_PROFILE": "bench", "BENCH_EFFORT": "medium"}
    live.build_live_provider(
        "bedrock", "us.anthropic.claude-sonnet-5-5", env, timeout=240.0, max_retries=2
    )
    kwargs = captured[0]
    assert kwargs["region"] == "us-east-2"
    assert kwargs["profile"] == "bench"
    assert kwargs["effort"] == "medium"
    # BedrockProvider takes neither; passing them would raise TypeError.
    assert "timeout" not in kwargs
    assert "max_retries" not in kwargs


def test_bedrock_non_claude_model_gets_no_effort(captured):
    live.build_live_provider(
        "bedrock", "qwen.qwen3", {"ANTHROPIC_EFFORT": "medium"}, timeout=1, max_retries=1
    )
    assert "effort" not in captured[0]


def test_anthropic_gets_key_timeout_retries_and_effort(captured):
    env = {"ANTHROPIC_API_KEY": "sk-ant-real", "ANTHROPIC_EFFORT": "medium"}
    live.build_live_provider("anthropic", "claude-sonnet-5-5", env, timeout=240.0, max_retries=2)
    kwargs = captured[0]
    assert kwargs["api_key"] == "sk-ant-real"
    assert (kwargs["timeout"], kwargs["max_retries"], kwargs["effort"]) == (240.0, 2, "medium")


def test_ollama_gets_timeout_and_base_url_only(captured):
    env = {"OLLAMA_BASE_URL": "http://127.0.0.1:11434"}
    live.build_live_provider("ollama", "qwen2.5:14b", env, timeout=300.0, max_retries=2)
    kwargs = captured[0]
    assert kwargs["base_url"] == "http://127.0.0.1:11434"
    assert kwargs["timeout"] == 300.0
    assert "max_retries" not in kwargs
