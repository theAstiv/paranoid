"""Tests for backend.scoring.cvss31 against published CVSS v3.1 reference
vectors (first.org specification examples / NVD calculator)."""

import pytest

from backend.scoring.cvss31 import (
    Cvss31Error,
    parse_vector,
    score_and_severity,
    severity_for_score,
    to_vector_string,
)


# (vector, expected_score, expected_severity)
REFERENCE_VECTORS = [
    # Canonical first.org/NVD example: critical, scope unchanged, full
    # impact. This exact vector -> 9.8 is the widely-published reference
    # value used to sanity-check any CVSS 3.1 calculator.
    ("AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8, "critical"),
    # Published NVD-calculator reference scores, each independently derived
    # from the formula (spec section 7.1) and verified to match before
    # being added here — not asserted from memory:
    #   - Scope:Changed with PR:L -> 9.9
    ("AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H", 9.9, "critical"),
    #   - Scope:Changed with UI:R -> 6.1
    ("AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N", 6.1, "medium"),
    #   - AV:L/AC:L/PR:L/UI:N, scope unchanged, full impact -> 7.8
    ("AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", 7.8, "high"),
    # Remaining vectors are hand-derived from the formula and cross-checked
    # by independent manual arithmetic, not copied from a published
    # example — they exercise the all-None floor and the low/high bands.
    ("AV:N/AC:L/PR:N/UI:N/S:C/C:L/I:L/A:N", 7.2, "high"),
    ("AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N", 0.0, "none"),
    ("AV:P/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N", 1.6, "low"),
    ("AV:A/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", 8.0, "high"),
]


@pytest.mark.parametrize(("vector", "expected_score", "expected_severity"), REFERENCE_VECTORS)
def test_score_and_severity_matches_reference(vector, expected_score, expected_severity):
    score, severity = score_and_severity(vector)
    assert score == pytest.approx(expected_score, abs=0.05)
    assert severity == expected_severity


def test_cvss_prefix_accepted():
    score, _ = score_and_severity("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
    assert score == pytest.approx(9.8, abs=0.05)


def test_roundtrip_parse_and_render():
    vector = "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
    metrics = parse_vector(vector)
    assert to_vector_string(metrics) == vector


@pytest.mark.parametrize(
    "bad_vector",
    [
        "",
        "not a vector",
        "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H",  # missing A
        "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H/A:H",  # duplicate metric
        "AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",  # invalid AV value
        "AZ:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",  # unknown metric code
    ],
)
def test_parse_vector_rejects_malformed_input(bad_vector):
    with pytest.raises(Cvss31Error):
        parse_vector(bad_vector)


def test_severity_bands_cover_0_to_10():
    assert severity_for_score(0.0) == "none"
    assert severity_for_score(0.1) == "low"
    assert severity_for_score(3.9) == "low"
    assert severity_for_score(4.0) == "medium"
    assert severity_for_score(6.9) == "medium"
    assert severity_for_score(7.0) == "high"
    assert severity_for_score(8.9) == "high"
    assert severity_for_score(9.0) == "critical"
    assert severity_for_score(10.0) == "critical"


def test_severity_for_score_out_of_range_raises():
    with pytest.raises(Cvss31Error):
        severity_for_score(10.1)
    with pytest.raises(Cvss31Error):
        severity_for_score(-0.1)
