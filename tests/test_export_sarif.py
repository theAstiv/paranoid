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


def test_sarif_dependency_threat_gets_npm_logical_location_and_manifest_physical_location():
    """A dependency-sourced threat gets a package-scoped logical location
    ("npm:pkg@version") and a physical location on the consumer's own
    package.json — NOT dependency_ref.file, which is a path inside the
    dependency's own tree and would resolve to the wrong file (or nothing)
    when GitHub renders the SARIF against the consumer's repo. The
    dependency's own file:line still appears in the message text and in
    properties.dependencyRef for anyone reading the raw SARIF."""
    from backend.models.state import DependencyRef, Threat

    threat = Threat(
        name="Install-time code execution",
        stride_category="Elevation of Privilege",
        description="x " * 40,
        target="lodash",
        impact="high",
        likelihood="high",
        mitigations=["pin version", "audit"],
        source="dependency",
        dependency_ref=DependencyRef(
            package="lodash",
            version="4.17.21",
            file="lib/index.js",
            line=42,
            rule_id="dynamic_code",
        ),
    )
    output = export_sarif(
        threats=ThreatsList(threats=[threat]),
        model_id="dep-test",
        framework="STRIDE",
        source_file="examples/stride-example.md",
    )

    result = output["runs"][0]["results"][0]
    locations = result["locations"]

    logical = next(loc for loc in locations if "logicalLocations" in loc)
    assert logical["logicalLocations"][0]["name"] == "npm:lodash@4.17.21"

    physical = next(loc for loc in locations if "physicalLocation" in loc)
    assert physical["physicalLocation"]["artifactLocation"]["uri"] == "package.json"
    assert physical["physicalLocation"]["region"]["startLine"] == 1

    # The dependency's own internal path must never be used as a SARIF
    # physical location — it doesn't exist in the consumer's repo tree.
    assert not any(
        loc.get("physicalLocation", {}).get("artifactLocation", {}).get("uri") == "lib/index.js"
        for loc in locations
    )
    # Nor the generic input-file location — package.json replaces it for
    # dependency threats.
    assert not any(
        loc.get("physicalLocation", {}).get("artifactLocation", {}).get("uri")
        == "examples/stride-example.md"
        for loc in locations
    )

    assert "lib/index.js:42" in result["message"]["text"]
    assert result["properties"]["dependencyRef"] == {
        "package": "lodash",
        "version": "4.17.21",
        "file": "lib/index.js",
        "line": 42,
        "ruleId": "dynamic_code",
    }


def test_sarif_dependency_threat_without_file_still_gets_manifest_location():
    from backend.models.state import DependencyRef, Threat

    threat = Threat(
        name="Drift finding",
        stride_category="Tampering",
        description="x " * 40,
        target="ua-parser-js",
        impact="high",
        likelihood="high",
        mitigations=["pin version", "audit"],
        source="dependency",
        dependency_ref=DependencyRef(
            package="ua-parser-js", version="0.7.29", file=None, line=None
        ),
    )
    output = export_sarif(
        threats=ThreatsList(threats=[threat]), model_id="dep-test-2", framework="STRIDE"
    )

    result = output["runs"][0]["results"][0]
    locations = result["locations"]
    # One location carrying both parts: GitHub rejects the whole upload unless
    # locations[0] has a physicalLocation.
    assert len(locations) == 1
    assert locations[0]["logicalLocations"][0]["name"] == "npm:ua-parser-js@0.7.29"
    assert locations[0]["physicalLocation"]["artifactLocation"]["uri"] == "package.json"
    assert "Found in" not in result["message"]["text"]


def test_sarif_dependency_threat_uses_caller_supplied_manifest_path():
    """A caller that knows the manifest's real path (e.g. the CLI's --manifest
    flag for a monorepo package) can override the "package.json" default so
    the physical location resolves to the right file."""
    from backend.models.state import DependencyRef, Threat

    threat = Threat(
        name="Install-time code execution",
        stride_category="Elevation of Privilege",
        description="x " * 40,
        target="lodash",
        impact="high",
        likelihood="high",
        mitigations=["pin version", "audit"],
        source="dependency",
        dependency_ref=DependencyRef(package="lodash", version="4.17.21", file=None, line=None),
    )
    output = export_sarif(
        threats=ThreatsList(threats=[threat]),
        model_id="dep-test-3",
        framework="STRIDE",
        dependency_manifest_path="apps/web/package.json",
    )

    physical = next(
        loc for loc in output["runs"][0]["results"][0]["locations"] if "physicalLocation" in loc
    )
    assert physical["physicalLocation"]["artifactLocation"]["uri"] == "apps/web/package.json"


def _dependency_threat(package="lodash", version="4.17.21"):
    from backend.models.state import DependencyRef, Threat

    return Threat(
        name="Install-time code execution",
        stride_category="Elevation of Privilege",
        description="x " * 40,
        target=package,
        impact="high",
        likelihood="high",
        mitigations=["pin version", "audit"],
        source="dependency",
        dependency_ref=DependencyRef(package=package, version=version, file=None, line=None),
    )


def test_sarif_dependency_result_leads_with_a_physical_location():
    """GitHub code scanning reads locations[0] and rejects the *entire* upload
    ("locationFromSarifResult: expected a physical location") when it has no
    physicalLocation — found by uploading a real CLI run. The npm logical
    location therefore lives in the same location object, after the physical
    one, rather than as a separate leading entry."""
    output = export_sarif(
        threats=ThreatsList(threats=[_dependency_threat()]),
        model_id="dep-gh",
        framework="STRIDE",
        source_file="examples/stride-example.md",
    )
    locations = output["runs"][0]["results"][0]["locations"]
    assert "physicalLocation" in locations[0]
    assert locations[0]["logicalLocations"][0]["name"] == "npm:lodash@4.17.21"


def test_to_sarif_uri_uses_forward_slashes_for_windows_paths():
    from pathlib import PureWindowsPath

    from backend.export.sarif import to_sarif_uri

    assert to_sarif_uri(PureWindowsPath("examples\\arsenal-deps\\description.md")) == (
        "examples/arsenal-deps/description.md"
    )
    assert to_sarif_uri("apps\\web\\package.json") == "apps/web/package.json"
    assert to_sarif_uri("already/posix.md") == "already/posix.md"


def test_sarif_locations_normalize_windows_style_paths():
    """SARIF artifact URIs are URI references: a Windows `str(Path)` with
    backslashes does not resolve against the repo on GitHub."""
    output = export_sarif(
        threats=ThreatsList(threats=[_dependency_threat()]),
        model_id="dep-win",
        framework="STRIDE",
        source_file="examples\\arsenal-deps\\description.md",
        dependency_manifest_path="apps\\web\\package.json",
    )
    uri = output["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"][
        "uri"
    ]
    assert uri == "apps/web/package.json"
