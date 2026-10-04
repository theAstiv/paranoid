"""Tests for the CLI run summary's usage block (cli/output/console.py)."""

from cli.output.console import ConsoleRenderer


_USAGE = {
    "by_model": [{"model": "claude-sonnet-5", "calls": 4, "total_tokens": 600}],
    "total_tokens": 600,
    "fast_model": None,
    "fast_model_share": None,
}


def test_summary_warns_when_fast_routing_was_disabled_mid_run(capsys):
    ConsoleRenderer().render_final_summary(
        total_threats=3, iterations=1, duration=1.0, usage={**_USAGE, "fast_routing_disabled": True}
    )
    assert "fast routing was disabled mid-run" in capsys.readouterr().out


def test_summary_has_no_warning_for_a_normal_run(capsys):
    ConsoleRenderer().render_final_summary(
        total_threats=3,
        iterations=1,
        duration=1.0,
        usage={**_USAGE, "fast_routing_disabled": False},
    )
    assert "disabled mid-run" not in capsys.readouterr().out


def test_summary_tolerates_usage_without_the_flag(capsys):
    ConsoleRenderer().render_final_summary(
        total_threats=3, iterations=1, duration=1.0, usage=_USAGE
    )
    out = capsys.readouterr().out
    assert "Total Tokens:" in out
    assert "disabled mid-run" not in out
