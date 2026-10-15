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


def test_summary_reports_what_the_coverage_guard_did(capsys):
    report = {
        "triggered": True,
        "iteration": 1,
        "targeted": ["Tampering"],
        "still_empty": ["Tampering"],
        "na_maestro": ["Privacy"],
        "unknown_maestro": False,
    }
    ConsoleRenderer().render_final_summary(
        total_threats=3, iterations=2, duration=1.0, usage={**_USAGE, "coverage_guard": report}
    )
    out = capsys.readouterr().out
    assert "stop overridden at iteration 1 for Tampering" in out
    assert "No LLM threats:     Tampering after a targeted pass" in out
    assert "MAESTRO N/A:        Privacy (no matching component)" in out


def test_summary_says_maestro_applicability_is_unknown(capsys):
    report = {"triggered": False, "still_empty": [], "na_maestro": [], "unknown_maestro": True}
    ConsoleRenderer().render_final_summary(
        total_threats=3, iterations=1, duration=1.0, usage={**_USAGE, "coverage_guard": report}
    )
    out = capsys.readouterr().out
    assert "not assessed" in out
    assert "stop overridden" not in out


def test_summary_without_a_coverage_report_prints_nothing_extra(capsys):
    ConsoleRenderer().render_final_summary(
        total_threats=3, iterations=1, duration=1.0, usage={**_USAGE, "coverage_guard": None}
    )
    out = capsys.readouterr().out
    assert "Coverage guard" not in out
    assert "MAESTRO N/A" not in out
