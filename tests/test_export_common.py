"""Tests for backend/export/_common.py — dependency findings helpers."""

from backend.export._common import (
    dependency_category_set,
    dependency_findings_rows,
    dependency_flags,
)


def test_dependency_category_set_empty_for_missing_profile() -> None:
    assert dependency_category_set(None) == set()


def test_dependency_category_set_only_counts_shipped_evidence() -> None:
    profile = {
        "evidence": [
            {"category": "network", "path_class": "shipped"},
            {"category": "crypto", "path_class": "test"},
        ],
    }
    result = dependency_category_set(profile)
    assert "network" in result
    assert "crypto" not in result


def test_dependency_category_set_adds_build_install_from_hooks() -> None:
    profile = {"evidence": [], "install_hooks": ["postinstall: node setup.js"]}
    assert "build_install" in dependency_category_set(profile)


def test_dependency_flags_empty_for_clean_analysis() -> None:
    assert dependency_flags({"npm_profile": {"status": "ok"}}) == []


def test_dependency_flags_none_analysis() -> None:
    assert dependency_flags(None) == []


def test_dependency_flags_error() -> None:
    assert "error" in dependency_flags({"error": "resolution failed"})


def test_dependency_flags_drift_signal() -> None:
    assert "drift" in dependency_flags({"drift": {"signal": True}})


def test_dependency_flags_install_hook() -> None:
    analysis = {"npm_profile": {"install_hooks": ["postinstall: node setup.js"]}}
    assert "install-hook" in dependency_flags(analysis)


def test_dependency_flags_non_ok_status() -> None:
    assert "semgrep_timeout" in dependency_flags({"npm_profile": {"status": "semgrep_timeout"}})
    assert "partial_fetch" in dependency_flags({"github_profile": {"status": "partial_fetch"}})


def test_dependency_findings_rows_empty() -> None:
    assert dependency_findings_rows(None) == []
    assert dependency_findings_rows([]) == []


def test_dependency_findings_rows_formats_package_categories_flags() -> None:
    scans = [
        {
            "package": "lodash",
            "version": "4.17.21",
            "analysis": {
                "npm_profile": {
                    "status": "ok",
                    "evidence": [{"category": "dynamic_code", "path_class": "shipped"}],
                    "install_hooks": [],
                },
                "github_profile": None,
                "drift": {"signal": True},
                "error": None,
            },
        }
    ]
    rows = dependency_findings_rows(scans)
    assert rows == [("lodash@4.17.21", "dynamic_code", "drift")]


def test_dependency_findings_rows_placeholder_for_no_categories_or_flags() -> None:
    scans = [
        {
            "package": "left-pad",
            "version": "1.0.0",
            "analysis": {"npm_profile": {"status": "ok", "evidence": []}},
        }
    ]
    assert dependency_findings_rows(scans) == [("left-pad@1.0.0", "—", "—")]
