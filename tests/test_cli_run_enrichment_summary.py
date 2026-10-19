"""Tests for the `paranoid run --enrich` summary line."""

from cli.commands.run import _enrichment_summary


def test_summary_without_refusals_is_unchanged():
    assert (
        _enrichment_summary(36, 36, 0, 0) == "Enrichment complete: 36 attack trees, 36 test suites"
    )


def test_summary_counts_attack_tree_refusals():
    assert _enrichment_summary(12, 36, 24, 0) == (
        "Enrichment complete: 12 attack trees (24 refused by the provider's content filter), "
        "36 test suites"
    )


def test_summary_counts_test_suite_refusals_too():
    assert _enrichment_summary(1, 26, 36, 11) == (
        "Enrichment complete: 1 attack trees (36 refused by the provider's content filter), "
        "26 test suites (11 refused by the provider's content filter)"
    )
