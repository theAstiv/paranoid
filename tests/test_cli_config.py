"""`paranoid config` defaults and help text (BB-95, BB-96)."""

import json

import pytest
from click.testing import CliRunner

import cli.commands.config as config_command
from cli import context
from cli.main import cli


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """Point the CLI's config file at a temp dir (never ~/.paranoid)."""
    path = tmp_path / ".paranoid" / "config.json"
    monkeypatch.setattr(context, "CONFIG_DIR", path.parent)
    monkeypatch.setattr(context, "CONFIG_FILE", path)
    monkeypatch.setattr(config_command, "CONFIG_FILE", path)
    return path


def _init(answers: list[str]):
    return CliRunner().invoke(cli, ["config", "init"], input="\n".join(answers) + "\n")


def test_openai_defaults_to_gpt_4_1(config_file):
    result = _init(["2", "sk-test", "", ""])  # provider, key, model (default), iterations
    assert result.exit_code == 0, result.output
    saved = json.loads(config_file.read_text())
    assert saved["default_model"] == "gpt-4.1"
    assert "OpenAI (GPT-4.1)" in result.output


def test_ollama_defaults_to_llama3_1_8b(config_file):
    result = _init(["3", "", "", ""])  # provider, base URL, model, iterations
    assert result.exit_code == 0, result.output
    assert json.loads(config_file.read_text())["default_model"] == "llama3.1:8b"


def test_the_wizard_says_how_to_set_up_bedrock(config_file):
    result = _init(["1", "sk-ant-test", "", ""])
    assert "DEFAULT_PROVIDER=bedrock" in result.output
    assert "AWS_REGION" in result.output


def test_a_run_of_the_wizard_does_not_change_the_built_in_defaults(config_file):
    _init(["2", "sk-test", "", ""])
    assert context.DEFAULT_CONFIG["providers"]["openai"]["api_key"] is None
    assert context.DEFAULT_CONFIG["default_provider"] == "anthropic"


def test_show_labels_the_config_schema_version(config_file):
    _init(["1", "sk-ant-test", "", ""])
    result = CliRunner().invoke(cli, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert "Config schema:    1.1.0" in result.output
    assert "Version:" not in result.output


@pytest.mark.parametrize(
    "args",
    [["config", "--help"], ["config", "init", "--help"], ["config", "show", "--help"]],
)
def test_help_has_no_literal_backslash_b(args):
    """BB-96: `\\\\b` in a docstring printed a literal backslash-b."""
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0
    assert "\\b" not in result.output


@pytest.mark.parametrize(
    ("args", "kept_line"),
    [
        (["run", "--help"], "  - <component_description> -> STRIDE"),
        (["version", "--help"], "  - Paranoid CLI version"),
    ],
)
def test_bullet_blocks_are_not_rewrapped(args, kept_line):
    result = CliRunner().invoke(cli, args)
    assert any(line.strip() == kept_line.strip() for line in result.output.splitlines())


def test_deps_scan_summary_is_not_cut_off():
    result = CliRunner().invoke(cli, ["deps", "--help"])
    scan_line = next(
        line for line in result.output.splitlines() if line.strip().startswith("scan ")
    )
    assert "(e.g." not in scan_line
    assert scan_line.rstrip().endswith("NAME@VERSION.")


@pytest.mark.parametrize("content", ["{not json", '{"default_provider": "anthropic"}'])
def test_config_file_errors_break_lines_instead_of_printing_backslash_n(config_file, content):
    """Same escaping bug as BB-96: the messages used two-backslash escapes."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(content)
    with pytest.raises(context.ConfigurationError) as info:
        context.load_config()
    message = str(info.value)
    assert chr(92) + "n" not in message  # a literal backslash-n
    assert "\n\n" in message
