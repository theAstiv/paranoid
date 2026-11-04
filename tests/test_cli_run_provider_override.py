"""`paranoid run --provider X` uses X's model and X's key (BB-97).

--provider only replaced default_provider after the settings were loaded, so
the run kept the configured provider's model (ollama + a Claude model ID), the
config file's key for X was never read, and a missing key for the configured
provider failed the run before --provider was looked at.
"""

import json

import pytest

from cli import context
from cli.commands.run import _get_config_supplement, _load_merged_settings
from cli.errors import ConfigurationError


_ENV = (
    "DEFAULT_PROVIDER",
    "DEFAULT_MODEL",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OLLAMA_BASE_URL",
)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """No env provider settings, no .env (cwd is empty), config file in tmp_path."""
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".paranoid" / "config.json"
    monkeypatch.setattr(context, "CONFIG_DIR", path.parent)
    monkeypatch.setattr(context, "CONFIG_FILE", path)

    def write(config: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": "1.1.0", **config}), encoding="utf-8")

    return write


def test_provider_override_takes_that_providers_key_and_model_from_the_config(isolated):
    isolated(
        {
            "default_provider": "anthropic",
            "default_model": "claude-configured",
            "providers": {
                "anthropic": {"api_key": "sk-ant-x", "model": "claude-configured"},
                "openai": {"api_key": "sk-openai-x", "model": "gpt-configured"},
            },
        }
    )

    settings = _load_merged_settings("openai")

    assert settings.default_provider == "openai"
    assert settings.default_model == "gpt-configured"
    assert settings.openai_api_key == "sk-openai-x"


def test_provider_override_without_a_configured_model_uses_the_builtin_default(isolated):
    isolated({"default_provider": "anthropic", "providers": {"anthropic": {"api_key": "k"}}})

    settings = _load_merged_settings("ollama")

    assert (settings.default_provider, settings.default_model) == ("ollama", "llama3.1:8b")


def test_provider_override_doesnt_need_the_configured_providers_key(isolated):
    """No Anthropic key at all, --provider ollama: used to fail on the Anthropic key."""
    isolated({"default_provider": "anthropic", "providers": {}})

    settings = _load_merged_settings("ollama")

    assert settings.default_provider == "ollama"


def test_provider_override_works_with_no_config_file(isolated):
    settings = _load_merged_settings("ollama")

    assert (settings.default_provider, settings.default_model) == ("ollama", "llama3.1:8b")


def test_provider_override_still_requires_the_chosen_providers_key(isolated):
    isolated({"default_provider": "ollama", "providers": {}})

    with pytest.raises(ConfigurationError, match="OpenAI API key not configured"):
        _load_merged_settings("openai")


def test_the_same_provider_keeps_the_configured_model(isolated):
    isolated(
        {
            "default_provider": "anthropic",
            "default_model": "claude-configured",
            "providers": {"anthropic": {"api_key": "k"}},
        }
    )

    settings = _load_merged_settings("anthropic")

    assert settings.default_model == "claude-configured"


def test_bedrock_without_a_model_leaves_it_empty_for_the_run_to_reject():
    supplement = _get_config_supplement(None, {"default_provider": "anthropic"}, "bedrock")

    assert supplement["default_provider"] == "bedrock"
    assert supplement["default_model"] == ""


def test_the_run_rejects_bedrock_without_a_model(isolated, tmp_path):
    from click.testing import CliRunner

    from cli.main import cli

    description = tmp_path / "system.txt"
    description.write_text("A web API backed by a Postgres database." * 3, encoding="utf-8")

    result = CliRunner().invoke(cli, ["run", str(description), "--provider", "bedrock"])

    assert result.exit_code != 0
    assert "No model for provider 'bedrock'" in result.output
