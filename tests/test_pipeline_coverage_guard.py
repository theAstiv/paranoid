"""Unit tests for backend/pipeline/coverage_guard.py (pure functions)."""

from backend.models.enums import AssetType, MaestroCategory, StrideCategory
from backend.models.state import Asset, AssetsList, Threat, ThreatsList
from backend.pipeline.coverage_guard import (
    applicable_maestro,
    build_report,
    build_targeted_gap,
    empty_categories,
    plan_targeted_pass,
)


_DESC = "An attacker could abuse this component to cause harm to users and the business."


def _threat(
    stride: StrideCategory,
    maestro: MaestroCategory | None = None,
    source: str = "llm",
) -> Threat:
    return Threat(
        name=f"{stride.value} {maestro.value if maestro else ''} {source}",
        stride_category=stride,
        maestro_category=maestro,
        description=_DESC,
        target="Target",
        impact="medium",
        likelihood="medium",
        mitigations=["Mitigation A", "Mitigation B"],
        source=source,
    )


def _all_stride_but(missing: StrideCategory, source: str = "llm") -> ThreatsList:
    return ThreatsList(threats=[_threat(c, source=source) for c in StrideCategory if c != missing])


_CHATBOT = AssetsList(
    assets=[
        Asset(type=AssetType.ASSET, name="Support Chatbot LLM", description="Answers tickets"),
        Asset(type=AssetType.ASSET, name="Web Application", description="Svelte frontend"),
    ]
)


def test_empty_categories_flags_stride_category_with_zero_threats():
    holes = empty_categories(
        _all_stride_but(StrideCategory.TAMPERING), check_maestro=False, applicable=[]
    )
    assert holes.stride == [StrideCategory.TAMPERING]
    assert holes.labels == ["Tampering"]


def test_one_threat_is_enough_unlike_the_balance_gate():
    threats = ThreatsList(threats=[_threat(c) for c in StrideCategory])
    assert not empty_categories(threats, check_maestro=False, applicable=[])


def test_seeded_and_rule_engine_threats_do_not_count():
    for source in ("seeded", "rule_engine", "dependency"):
        threats = ThreatsList(
            threats=[_threat(c) for c in StrideCategory if c != StrideCategory.TAMPERING]
            + [_threat(StrideCategory.TAMPERING, source=source)]
        )
        holes = empty_categories(threats, check_maestro=False, applicable=[])
        assert holes.stride == [StrideCategory.TAMPERING], source


def test_only_applicable_maestro_categories_can_be_holes():
    applicable = [MaestroCategory.LLM_SECURITY, MaestroCategory.PRIVACY]
    threats = ThreatsList(
        threats=[_threat(c) for c in StrideCategory]
        + [_threat(StrideCategory.TAMPERING, MaestroCategory.LLM_SECURITY)]
    )
    holes = empty_categories(threats, check_maestro=True, applicable=applicable)
    assert holes.maestro == [MaestroCategory.PRIVACY]
    assert holes.labels == ["MAESTRO: Privacy"]


def test_unknown_applicability_and_disabled_maestro_produce_no_maestro_holes():
    threats = ThreatsList(threats=[_threat(c) for c in StrideCategory])
    assert not empty_categories(threats, check_maestro=True, applicable=[])
    assert not empty_categories(
        threats, check_maestro=False, applicable=[MaestroCategory.LLM_SECURITY]
    )


def test_applicable_maestro_comes_from_asset_text():
    assert applicable_maestro(_CHATBOT) == [MaestroCategory.LLM_SECURITY]
    assert applicable_maestro(None) == []


def test_targeted_gap_names_every_hole_and_the_matching_assets():
    holes = empty_categories(
        _all_stride_but(StrideCategory.REPUDIATION),
        check_maestro=True,
        applicable=[MaestroCategory.LLM_SECURITY],
    )
    text = build_targeted_gap(holes, _CHATBOT)
    assert "Repudiation" in text
    assert "LLM Security" in text
    assert "Support Chatbot LLM" in text
    assert "Web Application" not in text
    assert "Do not repeat" in text


def test_plan_targeted_pass_is_none_when_covered():
    threats = ThreatsList(threats=[_threat(c) for c in StrideCategory])
    assert plan_targeted_pass(threats, None, check_maestro=False, applicable=[]) is None


def test_report_is_none_when_there_is_nothing_to_say():
    threats = ThreatsList(threats=[_threat(c) for c in StrideCategory])
    report = build_report(
        final_threats=threats,
        check_maestro=False,
        applicable=[],
        triggered=False,
        iteration=None,
        targeted=[],
    )
    assert report is None


def test_report_lists_na_unknown_and_still_empty():
    threats = _all_stride_but(StrideCategory.TAMPERING)
    report = build_report(
        final_threats=threats,
        check_maestro=True,
        applicable=[MaestroCategory.LLM_SECURITY],
        triggered=True,
        iteration=1,
        targeted=["Tampering"],
    )
    assert report is not None
    assert report.still_empty == ["Tampering", "MAESTRO: LLM Security"]
    assert "Privacy" in report.na_maestro
    assert "LLM Security" not in report.na_maestro
    assert not report.unknown_maestro

    unknown = build_report(
        final_threats=ThreatsList(threats=[_threat(c) for c in StrideCategory]),
        check_maestro=True,
        applicable=[],
        triggered=False,
        iteration=None,
        targeted=[],
    )
    assert unknown is not None
    assert unknown.unknown_maestro
    assert unknown.na_maestro == []
