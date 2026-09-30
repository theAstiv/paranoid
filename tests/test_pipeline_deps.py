"""Tests for the dependency capability engine's pipeline integration (Week 3).

Covers three layers:
- backend.deps.analyze: analyze_manifest() lockfile resolution, the direct-
  dependency cap, and per-package failure isolation
- backend.deps.threats: dependency_threats() deterministic mapping
- backend.pipeline.runner: ANALYZE_DEPENDENCIES step wiring, graceful
  degradation on failure, and dependency threats merging into the catalog
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.deps import analyze
from backend.deps.threats import dependency_threats, merge_dependency_threats
from backend.models.dependencies import (
    CapabilityEvidence,
    CapabilityProfile,
    DependencyContext,
    DriftReport,
    PackageAnalysis,
    PackageRef,
    ResolvedPackage,
)
from backend.models.enums import CapabilityCategory, Framework, PathClass, SourceKind
from backend.pipeline.nodes.helpers import format_dependency_context
from backend.pipeline.runner import PipelineConfig, PipelineRunner, PipelineStep
from tests.mock_provider import MockProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolved(name="pkg", version="1.0.0") -> ResolvedPackage:
    return ResolvedPackage(
        name=name, version=version, tarball_url=f"https://x/{name}.tgz", integrity="sha512-AAAA"
    )


def _profile(name="pkg", version="1.0.0", categories=(), install_hooks=()) -> CapabilityProfile:
    evidence = [
        CapabilityEvidence(
            category=c,
            rule_id="r",
            file="index.js",
            line=1,
            snippet="x",
            source_kind=SourceKind.NPM_TARBALL,
            path_class=PathClass.SHIPPED,
        )
        for c in categories
    ]
    return CapabilityProfile(
        name=name,
        version=version,
        source_kind=SourceKind.NPM_TARBALL,
        evidence=evidence,
        install_hooks=list(install_hooks),
        capability_vector=list(categories),
        status="ok",
    )


# ---------------------------------------------------------------------------
# backend.deps.analyze — manifest-level analysis
# ---------------------------------------------------------------------------


class TestAnalyzeManifest:
    @pytest.mark.asyncio
    async def test_uses_lockfile_pin_over_range(self):
        manifest = {"dependencies": {"chalk": "^5.3.0"}}
        lockfile = {"packages": {"node_modules/chalk": {"version": "5.3.0"}}}

        with patch.object(
            analyze, "analyze_package", new=AsyncMock(return_value=_pa("chalk", "5.3.0"))
        ) as mock_analyze:
            context = await analyze.analyze_manifest(manifest, lockfile, source_mode="npm")

        mock_analyze.assert_awaited_once_with(
            "chalk", "5.3.0", "npm", mock_analyze.await_args[0][3]
        )
        assert len(context.packages) == 1
        assert context.skipped == {}

    @pytest.mark.asyncio
    async def test_unresolvable_range_is_skipped(self):
        manifest = {"dependencies": {"weird": "git+https://example.com/pkg.git"}}

        context = await analyze.analyze_manifest(manifest, None, source_mode="npm")

        assert context.packages == []
        assert context.skipped == {"weird": "unresolvable_version_range"}

    @pytest.mark.asyncio
    async def test_direct_dependency_cap_skips_overflow_deterministically(self):
        manifest = {"dependencies": {f"pkg{i}": "1.0.0" for i in range(5)}}

        with patch.object(
            analyze,
            "analyze_package",
            new=AsyncMock(side_effect=lambda name, version, *_a, **_kw: _pa(name, version)),
        ):
            context = await analyze.analyze_manifest(
                manifest, None, source_mode="npm", max_direct_dependencies=2
            )

        assert len(context.packages) == 2
        assert len(context.skipped) == 3
        assert all(reason == "exceeds_direct_dependency_cap" for reason in context.skipped.values())

    @pytest.mark.asyncio
    async def test_one_package_failure_does_not_abort_sweep(self):
        manifest = {"dependencies": {"good": "1.0.0", "bad": "1.0.0"}}

        async def fake_analyze(name, version, source_mode, client):
            if name == "bad":
                raise OSError("simulated failure")
            return _pa(name, version)

        with patch.object(analyze, "analyze_package", new=AsyncMock(side_effect=fake_analyze)):
            context = await analyze.analyze_manifest(manifest, None, source_mode="npm")

        by_name = {pa.ref.name: pa for pa in context.packages}
        assert by_name["good"].error is None
        assert "OSError" in by_name["bad"].error

    @pytest.mark.asyncio
    async def test_deadline_already_passed_skips_all_with_time_budget_reason(self):
        """N1: a deadline already in the past when the sweep starts must skip
        every target with reason 'time_budget' instead of attempting any of
        them — the partial-results contract also covers the zero-budget case."""
        manifest = {"dependencies": {"a": "1.0.0", "b": "1.0.0"}}

        with patch.object(
            analyze,
            "analyze_package",
            new=AsyncMock(side_effect=lambda n, v, *_a, **_kw: _pa(n, v)),
        ) as mock_analyze:
            context = await analyze.analyze_manifest(
                manifest, None, source_mode="npm", deadline=time.monotonic() - 1
            )

        mock_analyze.assert_not_awaited()
        assert context.packages == []
        assert context.skipped == {"a": "time_budget", "b": "time_budget"}

    @pytest.mark.asyncio
    async def test_deadline_mid_sweep_returns_partial_results(self):
        """A package still running when the deadline passes is skipped with
        reason 'time_budget'; packages that already finished are kept —
        analyze_manifest returns whatever it has instead of discarding
        everything, unlike wrapping the whole sweep in one wait_for."""
        manifest = {"dependencies": {"fast": "1.0.0", "slow": "1.0.0"}}

        async def fake_analyze(name, version, source_mode, client):
            if name == "slow":
                await asyncio.sleep(10)
            return _pa(name, version)

        # A pre-built client avoids httpx.AsyncClient()'s own construction
        # cost (SSL context setup) eating into the deadline budget below —
        # analyze_manifest() would otherwise build one itself before the
        # first package even starts.
        async with httpx.AsyncClient() as client:
            with patch.object(analyze, "analyze_package", new=AsyncMock(side_effect=fake_analyze)):
                context = await analyze.analyze_manifest(
                    manifest,
                    None,
                    source_mode="npm",
                    client=client,
                    deadline=time.monotonic() + 0.2,
                )

        by_name = {pa.ref.name: pa for pa in context.packages}
        assert "fast" in by_name
        assert context.skipped == {"slow": "time_budget"}

    @pytest.mark.asyncio
    async def test_no_deadline_means_unbounded_as_before(self):
        manifest = {"dependencies": {"a": "1.0.0"}}

        with patch.object(
            analyze, "analyze_package", new=AsyncMock(return_value=_pa("a", "1.0.0"))
        ):
            context = await analyze.analyze_manifest(manifest, None, source_mode="npm")

        assert len(context.packages) == 1
        assert context.skipped == {}


def _pa(name: str, version: str) -> PackageAnalysis:
    return PackageAnalysis(
        ref=PackageRef(name=name, version=version), resolved=_resolved(name, version)
    )


# ---------------------------------------------------------------------------
# backend.deps.threats — deterministic dependency threat mapping
# ---------------------------------------------------------------------------


class TestDependencyThreats:
    def test_no_packages_yields_no_threats(self):
        result = dependency_threats(DependencyContext(packages=[]), Framework.STRIDE)
        assert result.threats == []

    def test_errored_package_yields_no_threats(self):
        ctx = DependencyContext(
            packages=[PackageAnalysis(ref=PackageRef(name="x", version="1.0.0"), error="boom")]
        )
        result = dependency_threats(ctx, Framework.STRIDE)
        assert result.threats == []

    def test_dynamic_code_capability_produces_tampering_threat(self):
        profile = _profile("pkg", "1.0.0", categories=[CapabilityCategory.DYNAMIC_CODE])
        pa = PackageAnalysis(
            ref=PackageRef(name="pkg", version="1.0.0"),
            resolved=_resolved("pkg", "1.0.0"),
            npm_profile=profile,
        )
        result = dependency_threats(DependencyContext(packages=[pa]), Framework.STRIDE)

        assert len(result.threats) == 1
        threat = result.threats[0]
        assert threat.source == "dependency"
        assert threat.stride_category.value == "Tampering"
        assert threat.dependency_ref.package == "pkg"
        assert threat.dependency_ref.version == "1.0.0"
        assert threat.dependency_ref.rule_id == "dynamic_code"

    def test_native_ffi_produces_elevation_of_privilege_threat(self):
        profile = _profile("sharp", "0.33.0", categories=[CapabilityCategory.NATIVE_FFI])
        pa = PackageAnalysis(
            ref=PackageRef(name="sharp", version="0.33.0"),
            resolved=_resolved("sharp", "0.33.0"),
            npm_profile=profile,
        )
        result = dependency_threats(DependencyContext(packages=[pa]), Framework.STRIDE)

        assert any(t.stride_category.value == "Elevation of Privilege" for t in result.threats)

    def test_network_and_environment_together_produce_info_disclosure(self):
        profile = _profile(
            "pkg", "1.0.0", categories=[CapabilityCategory.NETWORK, CapabilityCategory.ENVIRONMENT]
        )
        pa = PackageAnalysis(
            ref=PackageRef(name="pkg", version="1.0.0"),
            resolved=_resolved("pkg", "1.0.0"),
            npm_profile=profile,
        )
        result = dependency_threats(DependencyContext(packages=[pa]), Framework.STRIDE)

        assert any(t.dependency_ref.rule_id == "network_environment" for t in result.threats)

    def test_network_alone_does_not_trigger_info_disclosure(self):
        profile = _profile("pkg", "1.0.0", categories=[CapabilityCategory.NETWORK])
        pa = PackageAnalysis(
            ref=PackageRef(name="pkg", version="1.0.0"),
            resolved=_resolved("pkg", "1.0.0"),
            npm_profile=profile,
        )
        result = dependency_threats(DependencyContext(packages=[pa]), Framework.STRIDE)
        assert result.threats == []

    def test_drift_signal_produces_tampering_threat(self):
        profile = _profile("pkg", "1.0.0")
        drift = DriftReport(
            name="pkg",
            version="1.0.0",
            status="compared",
            signal=True,
            signal_categories=[CapabilityCategory.DYNAMIC_CODE],
        )
        pa = PackageAnalysis(
            ref=PackageRef(name="pkg", version="1.0.0"),
            resolved=_resolved("pkg", "1.0.0"),
            npm_profile=profile,
            drift=drift,
        )
        result = dependency_threats(DependencyContext(packages=[pa]), Framework.STRIDE)
        assert any(t.dependency_ref.rule_id == "drift_signal" for t in result.threats)

    def test_install_hook_added_in_drift_takes_precedence_over_plain_hook(self):
        profile = _profile("pkg", "1.0.0", install_hooks=["postinstall: node setup.js"])
        drift = DriftReport(
            name="pkg",
            version="1.0.0",
            status="compared",
            install_hooks_added=["postinstall"],
        )
        pa = PackageAnalysis(
            ref=PackageRef(name="pkg", version="1.0.0"),
            resolved=_resolved("pkg", "1.0.0"),
            npm_profile=profile,
            drift=drift,
        )
        result = dependency_threats(DependencyContext(packages=[pa]), Framework.STRIDE)
        hook_threats = [
            t for t in result.threats if t.dependency_ref.rule_id.startswith("install_hook")
        ]
        assert len(hook_threats) == 1
        assert hook_threats[0].dependency_ref.rule_id == "install_hook_added"

    def test_mitigations_within_allowed_range(self):
        """Threat.mitigations has min_length=2/max_length=5 — every generated
        threat's mitigation list must satisfy the Pydantic constraint."""
        profile = _profile(
            "pkg",
            "1.0.0",
            categories=[CapabilityCategory.DYNAMIC_CODE, CapabilityCategory.NATIVE_FFI],
            install_hooks=["postinstall: node setup.js"],
        )
        pa = PackageAnalysis(
            ref=PackageRef(name="pkg", version="1.0.0"),
            resolved=_resolved("pkg", "1.0.0"),
            npm_profile=profile,
        )
        result = dependency_threats(DependencyContext(packages=[pa]), Framework.STRIDE)
        assert result.threats
        for t in result.threats:
            assert 2 <= len(t.mitigations) <= 5


# ---------------------------------------------------------------------------
# backend.pipeline.runner — ANALYZE_DEPENDENCIES step wiring
# ---------------------------------------------------------------------------


class TestRunnerDependencyWiring:
    @pytest.mark.asyncio
    async def test_pre_built_dependency_context_skips_analysis_step(self):
        profile = _profile("pkg", "1.0.0", categories=[CapabilityCategory.NETWORK])
        pa = PackageAnalysis(
            ref=PackageRef(name="pkg", version="1.0.0"),
            resolved=_resolved("pkg", "1.0.0"),
            npm_profile=profile,
        )
        context = DependencyContext(packages=[pa], source_mode="npm")

        provider = MockProvider(gap_call_threshold=1)
        runner = PipelineRunner(
            provider=provider, config=PipelineConfig(max_iterations=1), model_id="t"
        )

        events = [
            e
            async for e in runner.run(
                description="A service with a network-capable dependency",
                framework=Framework.STRIDE,
                dependency_context=context,
            )
        ]

        analyze_events = [e for e in events if e.step == PipelineStep.ANALYZE_DEPENDENCIES]
        # No "started" analysis event: a pre-built context is used as-is, not re-analyzed.
        assert not any(e.status == "started" for e in analyze_events)

    @pytest.mark.asyncio
    async def test_manifest_analysis_failure_degrades_gracefully(self):
        provider = MockProvider(gap_call_threshold=1)
        runner = PipelineRunner(
            provider=provider, config=PipelineConfig(max_iterations=1), model_id="t"
        )

        with patch(
            "backend.pipeline.runner.analyze_manifest",
            new=AsyncMock(side_effect=RuntimeError("network unavailable")),
        ):
            events = [
                e
                async for e in runner.run(
                    description="A service",
                    framework=Framework.STRIDE,
                    dependency_manifest={"dependencies": {"chalk": "1.0.0"}},
                )
            ]

        # Pipeline must still complete despite the analysis failure.
        assert events[-1].step == PipelineStep.COMPLETE
        assert events[-1].status == "completed"
        info_events = [
            e for e in events if e.step == PipelineStep.ANALYZE_DEPENDENCIES and e.status == "info"
        ]
        assert len(info_events) == 1
        assert "unavailable" in info_events[0].message.lower()

    @pytest.mark.asyncio
    async def test_dependency_threats_merged_into_catalog(self):
        profile = _profile("pkg", "1.0.0", categories=[CapabilityCategory.DYNAMIC_CODE])
        pa = PackageAnalysis(
            ref=PackageRef(name="pkg", version="1.0.0"),
            resolved=_resolved("pkg", "1.0.0"),
            npm_profile=profile,
        )
        context = DependencyContext(packages=[pa], source_mode="npm")

        provider = MockProvider(gap_call_threshold=1)
        runner = PipelineRunner(
            provider=provider, config=PipelineConfig(max_iterations=1), model_id="t"
        )

        events = [
            e
            async for e in runner.run(
                description="A service", framework=Framework.STRIDE, dependency_context=context
            )
        ]

        complete = events[-1]
        assert complete.step == PipelineStep.COMPLETE
        threats = complete.data["threats"].threats
        assert any(t.source == "dependency" for t in threats)


# ---------------------------------------------------------------------------
# Regression: dependency threats must survive semantic-similarity merge
# ---------------------------------------------------------------------------


class TestMergeDependencyThreats:
    def test_similarly_worded_threats_across_packages_all_survive(self):
        """Dependency threat descriptions are templated and differ only by
        package name; merge_rule_and_llm_threats embedding-similarity dedup
        collapsed 5 packages near-identical findings down to 1. This must not
        happen through merge_dependency_threats."""
        packages = [_pa(n, "1.0.0") for n in ("axios", "esbuild", "lodash", "chalk", "express")]
        for pa in packages:
            pa.npm_profile = _profile(
                pa.ref.name, "1.0.0", categories=[CapabilityCategory.DYNAMIC_CODE]
            )
        dep_threats = dependency_threats(DependencyContext(packages=packages), Framework.STRIDE)
        assert len(dep_threats.threats) == 5

        from backend.models.enums import StrideCategory
        from backend.models.state import Threat, ThreatsList

        llm_threat = Threat(
            name="SQL Injection",
            stride_category=StrideCategory.TAMPERING,
            description="x" * 80,
            target="DB",
            impact="High",
            likelihood="Medium",
            mitigations=["a", "b"],
        )
        merged = merge_dependency_threats(dep_threats, ThreatsList(threats=[llm_threat]))

        assert len(merged.threats) == 6
        dep_names = {t.dependency_ref.package for t in merged.threats if t.source == "dependency"}
        assert dep_names == {"axios", "esbuild", "lodash", "chalk", "express"}

    def test_reruns_do_not_duplicate_existing_dependency_threats(self):
        pa = _pa("pkg", "1.0.0")
        pa.npm_profile = _profile("pkg", "1.0.0", categories=[CapabilityCategory.DYNAMIC_CODE])
        dep_threats = dependency_threats(DependencyContext(packages=[pa]), Framework.STRIDE)

        from backend.models.state import ThreatsList

        merged_once = merge_dependency_threats(dep_threats, ThreatsList(threats=[]))
        merged_twice = merge_dependency_threats(dep_threats, merged_once)

        assert len(merged_twice.threats) == 1


# ---------------------------------------------------------------------------
# Deterministic package ordering
# ---------------------------------------------------------------------------


class TestAnalyzeManifestOrdering:
    @pytest.mark.asyncio
    async def test_packages_sorted_by_name_regardless_of_completion_order(self):
        """Packages are appended as concurrent scans finish, not in manifest
        order; the returned context must be sorted so the prompt block (and
        its cache key) is stable run to run."""
        manifest = {"dependencies": dict.fromkeys(("zeta", "alpha", "mu"), "1.0.0")}

        async def fake_analyze(name, version, source_mode, client):
            # Reverse-alphabetical completion delay so finish order is zeta,
            # mu, alpha -- the opposite of sorted order.
            delay = {"zeta": 0.0, "mu": 0.01, "alpha": 0.02}[name]
            await asyncio.sleep(delay)
            return _pa(name, version)

        with patch.object(analyze, "analyze_package", new=AsyncMock(side_effect=fake_analyze)):
            context = await analyze.analyze_manifest(manifest, None, source_mode="npm")

        assert [pa.ref.name for pa in context.packages] == ["alpha", "mu", "zeta"]

    @pytest.mark.asyncio
    async def test_max_direct_dependencies_none_disables_cap(self):
        """The CLI scan-manifest command passes max_direct_dependencies=None to
        keep its long-standing unlimited behavior; the pipelines default cap
        must not silently apply when explicitly disabled."""
        manifest = {"dependencies": {f"pkg{i}": "1.0.0" for i in range(60)}}

        with patch.object(
            analyze,
            "analyze_package",
            new=AsyncMock(side_effect=lambda name, version, *_a, **_kw: _pa(name, version)),
        ):
            context = await analyze.analyze_manifest(
                manifest, None, source_mode="npm", max_direct_dependencies=None
            )

        assert len(context.packages) == 60
        assert context.skipped == {}


# ---------------------------------------------------------------------------
# Capability threats carry file:line from scan evidence
# ---------------------------------------------------------------------------


class TestDependencyThreatFileLine:
    def test_dynamic_code_threat_carries_evidence_file_and_line(self):
        profile = CapabilityProfile(
            name="pkg",
            version="1.0.0",
            source_kind=SourceKind.NPM_TARBALL,
            evidence=[
                CapabilityEvidence(
                    category=CapabilityCategory.DYNAMIC_CODE,
                    rule_id="dynamic-code-eval",
                    file="lib/index.js",
                    line=42,
                    snippet="eval(x)",
                    source_kind=SourceKind.NPM_TARBALL,
                    path_class=PathClass.SHIPPED,
                )
            ],
        )
        pa = _pa("pkg", "1.0.0")
        pa.npm_profile = profile
        result = dependency_threats(DependencyContext(packages=[pa]), Framework.STRIDE)

        threat = next(t for t in result.threats if t.dependency_ref.rule_id == "dynamic_code")
        assert threat.dependency_ref.file == "lib/index.js"
        assert threat.dependency_ref.line == 42

    def test_native_ffi_threat_carries_evidence_file_and_line(self):
        profile = CapabilityProfile(
            name="sharp",
            version="0.33.0",
            source_kind=SourceKind.NPM_TARBALL,
            evidence=[
                CapabilityEvidence(
                    category=CapabilityCategory.NATIVE_FFI,
                    rule_id="native-ffi-addon",
                    file="binding.js",
                    line=7,
                    snippet="require(./build/addon.node)",
                    source_kind=SourceKind.NPM_TARBALL,
                    path_class=PathClass.SHIPPED,
                )
            ],
        )
        pa = _pa("sharp", "0.33.0")
        pa.npm_profile = profile
        result = dependency_threats(DependencyContext(packages=[pa]), Framework.STRIDE)

        threat = next(t for t in result.threats if t.dependency_ref.rule_id == "native_ffi")
        assert threat.dependency_ref.file == "binding.js"
        assert threat.dependency_ref.line == 7


# ---------------------------------------------------------------------------
# MAESTRO framework annotation
# ---------------------------------------------------------------------------


def test_maestro_framework_notes_supply_chain_layer():
    pa = _pa("pkg", "1.0.0")
    pa.npm_profile = _profile("pkg", "1.0.0", categories=[CapabilityCategory.DYNAMIC_CODE])
    stride_result = dependency_threats(DependencyContext(packages=[pa]), Framework.STRIDE)
    maestro_result = dependency_threats(DependencyContext(packages=[pa]), Framework.MAESTRO)

    assert "MAESTRO Supply Chain" not in stride_result.threats[0].description
    assert "MAESTRO Supply Chain" in maestro_result.threats[0].description


# ---------------------------------------------------------------------------
# format_dependency_context size cap with a large manifest
# ---------------------------------------------------------------------------


def test_format_dependency_context_stays_bounded_with_50_notable_packages():
    packages = []
    for i in range(50):
        name = f"pkg-{i:02d}"
        profile = CapabilityProfile(
            name=name,
            version="1.0.0",
            source_kind=SourceKind.NPM_TARBALL,
            evidence=[
                CapabilityEvidence(
                    category=CapabilityCategory.DYNAMIC_CODE,
                    rule_id="r",
                    file="index.js",
                    line=1,
                    snippet="eval(x)",
                    source_kind=SourceKind.NPM_TARBALL,
                    path_class=PathClass.SHIPPED,
                )
            ],
        )
        pa = _pa(name, "1.0.0")
        pa.npm_profile = profile
        packages.append(pa)

    context = DependencyContext(packages=packages, source_mode="npm")
    text = format_dependency_context(context)

    assert len(text) <= 3000
    assert "...and" in text  # only the first 15 are listed individually


# ---------------------------------------------------------------------------
# Runner: stop_after="extraction" skips dependency analysis; timeout degrades
# ---------------------------------------------------------------------------


class TestRunnerDependencyAnalysisScope:
    @pytest.mark.asyncio
    async def test_stop_after_extraction_skips_dependency_analysis(self):
        provider = MockProvider(gap_call_threshold=1)
        runner = PipelineRunner(
            provider=provider, config=PipelineConfig(max_iterations=1), model_id="t"
        )

        with patch("backend.pipeline.runner.analyze_manifest", new=AsyncMock()) as mock_analyze:
            events = [
                e
                async for e in runner.run(
                    description="A service",
                    framework=Framework.STRIDE,
                    dependency_manifest={"dependencies": {"chalk": "1.0.0"}},
                    stop_after="extraction",
                )
            ]

        mock_analyze.assert_not_called()
        analyze_events = [e for e in events if e.step == PipelineStep.ANALYZE_DEPENDENCIES]
        assert analyze_events == []

    @pytest.mark.asyncio
    async def test_dependency_analysis_timeout_degrades_gracefully(self):
        from backend.config import settings
        from backend.pipeline import runner as runner_module

        provider = MockProvider(gap_call_threshold=1)
        runner = PipelineRunner(
            provider=provider, config=PipelineConfig(max_iterations=1), model_id="t"
        )

        async def _hangs(*args, **kwargs):
            await asyncio.sleep(10)

        original_timeout = settings.deps_analysis_timeout_seconds
        original_grace = runner_module._DEPS_ANALYSIS_BACKSTOP_GRACE_S
        settings.deps_analysis_timeout_seconds = 0.05
        # Also shrink the backstop's grace period (see its docstring): the
        # real 30s grace exists to outlive a cancelled scan's cleanup, but
        # would make this test wait ~30s for the outer wait_for to fire.
        runner_module._DEPS_ANALYSIS_BACKSTOP_GRACE_S = 0.05
        try:
            with patch("backend.pipeline.runner.analyze_manifest", new=_hangs):
                events = [
                    e
                    async for e in runner.run(
                        description="A service",
                        framework=Framework.STRIDE,
                        dependency_manifest={"dependencies": {"chalk": "1.0.0"}},
                    )
                ]
        finally:
            settings.deps_analysis_timeout_seconds = original_timeout
            runner_module._DEPS_ANALYSIS_BACKSTOP_GRACE_S = original_grace

        assert events[-1].step == PipelineStep.COMPLETE
        assert events[-1].status == "completed"
        info_events = [
            e for e in events if e.step == PipelineStep.ANALYZE_DEPENDENCIES and e.status == "info"
        ]
        assert len(info_events) == 1
        assert "timed out" in info_events[0].message.lower()

    @pytest.mark.asyncio
    async def test_backstop_grace_survives_slow_partial_return(self):
        """N1 regression: analyze_manifest() can legitimately take a little
        longer than its own deadline to actually return — e.g. cancelling a
        still-running scan takes real wall-clock time
        (backend.deps.scanner._kill_process_tree: up to ~10s). If the outer
        wait_for's timeout equalled the deadline instead of exceeding it by
        _DEPS_ANALYSIS_BACKSTOP_GRACE_S, it would fire while analyze_manifest
        is still finishing that cleanup and discard the partial
        DependencyContext it was about to return — the exact all-or-nothing
        failure the deadline exists to avoid."""
        from backend.config import settings
        from backend.pipeline import runner as runner_module

        provider = MockProvider(gap_call_threshold=1)
        runner = PipelineRunner(
            provider=provider, config=PipelineConfig(max_iterations=1), model_id="t"
        )

        partial_context = DependencyContext(
            packages=[_pa("fast", "1.0.0")], skipped={"slow": "time_budget"}, source_mode="npm"
        )

        async def _slow_to_return_partial(*args, **kwargs):
            # Finishes past the per-package deadline (simulated by the tiny
            # settings.deps_analysis_timeout_seconds below), the way a real
            # cancelled-scan cleanup would, but still within the backstop's
            # grace period.
            await asyncio.sleep(0.08)
            return partial_context

        original_timeout = settings.deps_analysis_timeout_seconds
        original_grace = runner_module._DEPS_ANALYSIS_BACKSTOP_GRACE_S
        settings.deps_analysis_timeout_seconds = 0.01
        runner_module._DEPS_ANALYSIS_BACKSTOP_GRACE_S = 1.0
        try:
            with patch("backend.pipeline.runner.analyze_manifest", new=_slow_to_return_partial):
                events = [
                    e
                    async for e in runner.run(
                        description="A service",
                        framework=Framework.STRIDE,
                        dependency_manifest={"dependencies": {"fast": "1.0.0", "slow": "1.0.0"}},
                    )
                ]
        finally:
            settings.deps_analysis_timeout_seconds = original_timeout
            runner_module._DEPS_ANALYSIS_BACKSTOP_GRACE_S = original_grace

        completed = [
            e
            for e in events
            if e.step == PipelineStep.ANALYZE_DEPENDENCIES and e.status == "completed"
        ]
        assert len(completed) == 1
        assert completed[0].data == {"package_count": 1, "skipped_count": 1}
