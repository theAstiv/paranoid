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


def test_sarif_attack_techniques_rendered_as_tags():
    """A trusted (table/seed) technique match gets properties.tags, formatted
    as "attack/<id>" for GitHub Code Scanning's tag taxonomy."""
    from backend.models.state import TechniqueRef, Threat

    threat = Threat(
        name="Compromise Software Supply Chain",
        stride_category="Tampering",
        description="x " * 40,
        target="evil-pkg",
        impact="high",
        likelihood="medium",
        mitigations=["pin version", "audit"],
        attack_techniques=[
            TechniqueRef(
                id="T1195.002",
                name="Compromise Software Supply Chain",
                url="https://attack.mitre.org/techniques/T1195/002",
                confidence=0.9,
                method="table",
            )
        ],
    )
    output = export_sarif(
        threats=ThreatsList(threats=[threat]), model_id="tag-test", framework="STRIDE"
    )
    result = output["runs"][0]["results"][0]
    assert result["properties"]["tags"] == ["attack/T1195.002"]


def test_sarif_embedding_match_tagged_as_suggested():
    """An embedding-sourced match (a similarity guess, not a confirmed
    lookup) gets a /suggested tag suffix so GitHub code scanning doesn't
    present it with the same confidence as a table/seed match."""
    from backend.models.state import TechniqueRef, Threat

    threat = Threat(
        name="Some LLM-authored threat",
        stride_category="Tampering",
        description="x " * 40,
        target="A service",
        impact="high",
        likelihood="medium",
        mitigations=["pin version", "audit"],
        attack_techniques=[
            TechniqueRef(
                id="AML.T0020",
                name="ML Training Data Poisoning",
                url="https://atlas.mitre.org/techniques/AML.T0020",
                confidence=0.5,
                method="embedding",
            )
        ],
    )
    output = export_sarif(
        threats=ThreatsList(threats=[threat]), model_id="suggested-test", framework="STRIDE"
    )
    result = output["runs"][0]["results"][0]
    assert result["properties"]["tags"] == ["attack/AML.T0020/suggested"]


def test_sarif_no_tags_property_when_no_techniques_matched():
    threats = make_stride_threats()
    output = export_sarif(threats=threats, model_id="no-tags", framework="STRIDE")
    for result in output["runs"][0]["results"]:
        assert "tags" not in result["properties"]


def test_sarif_cvss_result_properties_and_rule_security_severity():
    """properties.cvss on the result carries vector/score/severity (useful
    for a human/tool reading the raw SARIF), but security-severity — the
    literal property GitHub code scanning actually reads for its own
    severity sort/badge — lives on the RULE (tool.driver.rules[].properties),
    not the result. GitHub does not read a result-level security-severity."""
    from backend.models.state import Threat
    from backend.scoring.cvss31 import Cvss31Metrics

    metrics = Cvss31Metrics(
        attack_vector="N",
        attack_complexity="L",
        privileges_required="N",
        user_interaction="N",
        scope="U",
        confidentiality="H",
        integrity="H",
        availability="H",
    )
    threat = Threat(
        name="Remote Code Execution",
        stride_category="Tampering",
        description="x " * 40,
        target="API Gateway",
        impact="high",
        likelihood="high",
        mitigations=["pin version", "audit"],
        cvss=metrics,
        cvss_score=9.8,
        cvss_severity="critical",
    )
    output = export_sarif(
        threats=ThreatsList(threats=[threat]), model_id="cvss-test", framework="STRIDE"
    )
    result = output["runs"][0]["results"][0]
    assert result["properties"]["cvss"] == {
        "vector": "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        "score": 9.8,
        "severity": "critical",
    }
    assert "security-severity" not in result["properties"]
    assert result["level"] == "error"  # CVSS >= 7 takes precedence

    rules = output["runs"][0]["tool"]["driver"]["rules"]
    tampering_rule = next(r for r in rules if r["id"] == result["ruleId"])
    assert tampering_rule["properties"]["security-severity"] == "9.8"


def test_sarif_rule_name_uses_enum_value_not_python_repr():
    """threat.stride_category is a str-mixin Enum (StrideCategory), not a
    plain string, on any Threat built directly (every Threat() call coerces
    its stride_category input into the enum via Pydantic validation — this
    isn't a special "fresh pipeline result" case, it's every Threat).
    `.lower()`/`_rule_id()` work fine on it since the mixin's str value IS
    the enum's value, but Enum's __str__ wins over str's in an f-string, so
    f"{category}" bakes "StrideCategory.TAMPERING" into the rule name
    instead of "Tampering". Unlike `properties["category"] = category`
    (the raw enum, fixed up later by a JSON encoder when this dict is
    serialized), a value already baked into an f-string never gets that
    second chance."""
    from backend.models.state import Threat

    threat = Threat(
        name="Tampering via crafted input",
        stride_category="Tampering",
        description="x " * 40,
        target="A",
        impact="high",
        likelihood="high",
        mitigations=["pin version", "audit"],
        cvss_score=9.5,
        cvss_severity="critical",
    )
    output = export_sarif(
        threats=ThreatsList(threats=[threat]), model_id="enum-name-test", framework="STRIDE"
    )
    rules = output["runs"][0]["tool"]["driver"]["rules"]
    rule = next(r for r in rules if r["id"] == "stride/tampering/critical")
    assert rule["name"] == "Tampering (Critical)"
    assert "StrideCategory" not in rule["name"]


def test_sarif_rules_split_by_severity_band_within_a_category():
    """A low-scoring threat must NOT inherit a high-scoring sibling's
    security-severity just because they share a STRIDE category — one rule
    per (category, band), not one rule per category. Before this fix, a
    single stride/tampering rule carried the category's max score (9.1),
    so GitHub would have shown the 3.0 threat as "High" too."""
    from backend.models.state import Threat

    low = Threat(
        name="Low severity tampering",
        stride_category="Tampering",
        description="x " * 40,
        target="A",
        impact="low",
        likelihood="low",
        mitigations=["pin version", "audit"],
        cvss_score=3.0,
        cvss_severity="low",
    )
    high = Threat(
        name="High severity tampering",
        stride_category="Tampering",
        description="x " * 40,
        target="B",
        impact="high",
        likelihood="high",
        mitigations=["pin version", "audit"],
        cvss_score=9.1,
        cvss_severity="critical",
    )
    output = export_sarif(
        threats=ThreatsList(threats=[low, high]), model_id="max-test", framework="STRIDE"
    )
    results = output["runs"][0]["results"]
    rules = output["runs"][0]["tool"]["driver"]["rules"]
    rule_by_id = {r["id"]: r for r in rules}

    low_result = next(
        r for r in results if r["partialFingerprints"]["threatName"] == "Low severity tampering"
    )
    high_result = next(
        r for r in results if r["partialFingerprints"]["threatName"] == "High severity tampering"
    )

    assert low_result["ruleId"] == "stride/tampering/low"
    assert high_result["ruleId"] == "stride/tampering/critical"
    assert rule_by_id["stride/tampering/low"]["properties"]["security-severity"] == "3.0"
    assert rule_by_id["stride/tampering/critical"]["properties"]["security-severity"] == "9.1"
    assert rule_by_id["stride/tampering/low"]["properties"]["tags"] == ["security"]


def test_sarif_rule_security_severity_is_max_within_its_own_band():
    """Two threats land in the SAME band (both "high") — the rule's
    security-severity must be the higher of the two, not the first/last."""
    from backend.models.state import Threat

    lower_high = Threat(
        name="Lower high tampering",
        stride_category="Tampering",
        description="x " * 40,
        target="A",
        impact="high",
        likelihood="high",
        mitigations=["pin version", "audit"],
        cvss_score=7.2,
        cvss_severity="high",
    )
    higher_high = Threat(
        name="Higher high tampering",
        stride_category="Tampering",
        description="x " * 40,
        target="B",
        impact="high",
        likelihood="high",
        mitigations=["pin version", "audit"],
        cvss_score=8.9,
        cvss_severity="high",
    )
    output = export_sarif(
        threats=ThreatsList(threats=[lower_high, higher_high]),
        model_id="band-max-test",
        framework="STRIDE",
    )
    rules = output["runs"][0]["tool"]["driver"]["rules"]
    tampering_high = next(r for r in rules if r["id"] == "stride/tampering/high")
    assert tampering_high["properties"]["security-severity"] == "8.9"


def test_sarif_no_scored_threat_never_emits_zero_security_severity():
    """A 0.0 CVSS score is outside GitHub's allowed security-severity range
    (above 0.0, up to 10.0) — such a threat must fall back to the plain
    per-category rule with no security-severity property, same as a threat
    with no CVSS score at all."""
    from backend.models.state import Threat

    zero = Threat(
        name="Zero score tampering",
        stride_category="Tampering",
        description="x " * 40,
        target="A",
        impact="low",
        likelihood="low",
        mitigations=["pin version", "audit"],
        cvss_score=0.0,
        cvss_severity="none",
    )
    output = export_sarif(
        threats=ThreatsList(threats=[zero]), model_id="zero-test", framework="STRIDE"
    )
    result = output["runs"][0]["results"][0]
    assert result["ruleId"] == "stride/tampering"
    rules = output["runs"][0]["tool"]["driver"]["rules"]
    tampering_rule = next(r for r in rules if r["id"] == "stride/tampering")
    assert "security-severity" not in tampering_rule["properties"]


def test_sarif_rule_engine_threat_with_no_score_uses_plain_category_rule():
    """A rule-engine/DREAD-only threat (no cvss_score) in the same category
    as a scored threat must use the plain category rule, not inherit the
    scored sibling's band."""
    from backend.models.state import Threat

    unscored = Threat(
        name="Unscored tampering",
        stride_category="Tampering",
        description="x " * 40,
        target="A",
        impact="high",
        likelihood="high",
        mitigations=["pin version", "audit"],
    )
    scored = Threat(
        name="Scored tampering",
        stride_category="Tampering",
        description="x " * 40,
        target="B",
        impact="high",
        likelihood="high",
        mitigations=["pin version", "audit"],
        cvss_score=9.5,
        cvss_severity="critical",
    )
    output = export_sarif(
        threats=ThreatsList(threats=[unscored, scored]), model_id="mixed-test", framework="STRIDE"
    )
    results = output["runs"][0]["results"]
    unscored_result = next(
        r for r in results if r["partialFingerprints"]["threatName"] == "Unscored tampering"
    )
    assert unscored_result["ruleId"] == "stride/tampering"

    rules = output["runs"][0]["tool"]["driver"]["rules"]
    rule_ids = {r["id"] for r in rules}
    assert "stride/tampering" in rule_ids
    assert "stride/tampering/critical" in rule_ids
    plain_rule = next(r for r in rules if r["id"] == "stride/tampering")
    assert "security-severity" not in plain_rule["properties"]


def test_sarif_no_cvss_property_when_no_score():
    threats = make_stride_threats()
    output = export_sarif(threats=threats, model_id="no-cvss", framework="STRIDE")
    for result in output["runs"][0]["results"]:
        assert "cvss" not in result["properties"]
    for rule in output["runs"][0]["tool"]["driver"]["rules"]:
        assert "security-severity" not in rule["properties"]


def test_sarif_severity_mapping_prefers_cvss_over_dread():
    """When both CVSS and DREAD scores are present, CVSS wins for `level`."""

    class MockThreat:
        def __init__(self, cvss_score=None, dread=None, likelihood=""):
            self.cvss_score = cvss_score
            self.dread = dread
            self.likelihood = likelihood

    class MockDread:
        score = 9.0  # would be "error" too, so use a low DREAD to prove CVSS wins

    class MockLowDread:
        score = 1.0

    assert _severity_to_level(MockThreat(cvss_score=2.0, dread=MockDread())) == "note"
    assert _severity_to_level(MockThreat(cvss_score=9.0, dread=MockLowDread())) == "error"
