"""Tests for SARIF 2.1.0 export (backend/export/sarif.py).

Uses fixture threats from tests/fixtures/pipeline.py — no API tokens needed.
"""

import pytest

from backend.export.sarif import (
    _severity_to_level,
    export_sarif,
)
from backend.models.state import ThreatsList
from tests.fixtures.pipeline import make_stride_threats


@pytest.fixture
def sarif_output():
    """Pre-built SARIF output from stride threats."""
    threats = make_stride_threats()
    return export_sarif(
        threats=threats,
        model_id="test-model-001",
        framework="STRIDE",
        source_file="examples/stride-example.md",
    )


def test_sarif_output_valid_schema(sarif_output):
    """SARIF output should have required top-level structure."""
    assert sarif_output["version"] == "2.1.0"
    assert "$schema" in sarif_output
    assert "runs" in sarif_output
    assert len(sarif_output["runs"]) == 1

    run = sarif_output["runs"][0]
    assert "tool" in run
    assert "results" in run
    assert run["tool"]["driver"]["name"] == "Paranoid Threat Modeler"


def test_sarif_rules_per_category(sarif_output):
    """Should generate one rule per unique STRIDE category."""
    rules = sarif_output["runs"][0]["tool"]["driver"]["rules"]
    # 6 threats = 6 STRIDE categories = 6 rules
    assert len(rules) == 6

    rule_ids = [r["id"] for r in rules]
    for rule_id in rule_ids:
        assert rule_id.startswith("stride/")


def test_sarif_results_match_threats(sarif_output):
    """Should have one result per threat."""
    results = sarif_output["runs"][0]["results"]
    # 6 stride threats = 6 results
    assert len(results) == 6

    for result in results:
        assert "ruleId" in result
        assert "message" in result
        assert "level" in result


def test_sarif_severity_mapping():
    """Test severity mapping from likelihood strings."""
    # Create mock threat-like objects for _severity_to_level
    class MockThreat:
        def __init__(self, likelihood, dread=None):
            self.likelihood = likelihood
            self.dread = dread

    assert _severity_to_level(MockThreat("high")) == "error"
    assert _severity_to_level(MockThreat("very high")) == "error"
    assert _severity_to_level(MockThreat("medium")) == "warning"
    assert _severity_to_level(MockThreat("low")) == "note"
    assert _severity_to_level(MockThreat("")) == "note"


def test_sarif_empty_threats():
    """Empty threat list should produce valid SARIF with no results."""
    result = export_sarif(
        threats=ThreatsList(threats=[]),
        model_id="empty-test",
        framework="STRIDE",
    )
    assert result["version"] == "2.1.0"
    assert len(result["runs"][0]["results"]) == 0
    assert len(result["runs"][0]["tool"]["driver"]["rules"]) == 0


def test_sarif_locations(sarif_output):
    """Results should include location info when source_file is provided."""
    results = sarif_output["runs"][0]["results"]
    for result in results:
        if "locations" in result and len(result["locations"]) > 0:
            location = result["locations"][0]
            assert "physicalLocation" in location
            artifact = location["physicalLocation"]["artifactLocation"]
            assert artifact["uri"] == "examples/stride-example.md"
