"""Deterministic threats derived from dependency capability analysis.

Turns a `DependencyContext` (npm/GitHub capability profiles + drift, from
`backend.deps.analyze`) into `Threat` objects with `source="dependency"` and
a `dependency_ref` carrying package/file/rule provenance. Table-driven, no
LLM involved — mirrors `backend.rules.engine.match_patterns()`, which is the
same "deterministic pattern -> Threat" shape for the seed-pattern rule engine.

Determinism-first: the LLM only ever *reads* a summary of this context (see
`backend.pipeline.nodes.helpers.format_dependency_context`); it never sets
dependency provenance itself.
"""

import logging

from backend.models.dependencies import (
    CapabilityEvidence,
    CapabilityProfile,
    DependencyContext,
    PackageAnalysis,
)
from backend.models.enums import CapabilityCategory, Framework, PathClass, StrideCategory
from backend.models.state import DependencyRef, Threat, ThreatsList


logger = logging.getLogger(__name__)

_PIN_AND_VERIFY = "Pin the exact resolved version and verify lockfile integrity hashes on install"
_IGNORE_SCRIPTS = (
    "Install with `npm ci --ignore-scripts` where the package doesn't require a build step"
)
_REVIEW_DIFF = "Review the capability/version diff before upgrading this dependency"
_VENDOR_OR_REPLACE = "Vendor or replace the dependency if the flagged capability isn't required"

_DEFAULT_MITIGATIONS = [_PIN_AND_VERIFY, _REVIEW_DIFF, _VENDOR_OR_REPLACE]
_INSTALL_TIME_MITIGATIONS = [_PIN_AND_VERIFY, _IGNORE_SCRIPTS, _REVIEW_DIFF]


def _threat(
    *,
    name: str,
    stride_category: StrideCategory,
    description: str,
    target: str,
    mitigations: list[str],
    package: str,
    version: str,
    rule_id: str,
    file: str | None = None,
    line: int | None = None,
) -> Threat:
    threat = Threat(
        name=name,
        stride_category=stride_category,
        description=description,
        target=target,
        impact="Medium",
        likelihood="Medium",
        mitigations=mitigations,
        source="dependency",
        dependency_ref=DependencyRef(
            package=package, version=version, file=file, line=line, rule_id=rule_id
        ),
    )
    return threat


def _first_evidence(
    profile: CapabilityProfile, *categories: CapabilityCategory
) -> CapabilityEvidence | None:
    """The first SHIPPED evidence item for any of `categories`, if any —
    used to attach a real file:line to a capability-derived threat instead of
    leaving `DependencyRef.file`/`.line` empty when the scan evidence has them."""
    for evidence in profile.evidence:
        if evidence.path_class == PathClass.SHIPPED and evidence.category in categories:
            return evidence
    return None


def _package_findings(pa: PackageAnalysis) -> list[Threat]:
    """Deterministic threats for a single analyzed package."""
    if pa.error or pa.resolved is None:
        return []

    profile = pa.npm_profile or pa.github_profile
    if profile is None:
        return []

    name, version = pa.resolved.name, pa.resolved.version
    target = f"{name}@{version}"
    categories = profile.category_set()
    findings: list[Threat] = []

    # -- drift: published artifact has capability absent from its declared source
    if pa.drift is not None and pa.drift.signal:
        findings.append(
            _threat(
                name=f"Published capability drift in {target}",
                stride_category=StrideCategory.TAMPERING,
                description=(
                    f"The npm-published artifact for {target} contains capabilities "
                    f"({', '.join(c.value for c in pa.drift.signal_categories) or 'see evidence'}) "
                    "absent from its declared GitHub source, so the published code cannot be "
                    "verified against a reviewable source tree."
                ),
                target=target,
                mitigations=_DEFAULT_MITIGATIONS,
                package=name,
                version=version,
                rule_id="drift_signal",
            )
        )

    # -- install-time code execution: a lifecycle hook runs on `npm install`
    hooks_added = pa.drift.install_hooks_added if pa.drift is not None else []
    if hooks_added:
        findings.append(
            _threat(
                name=f"Install hook added to {target} not present in source",
                stride_category=StrideCategory.ELEVATION_OF_PRIVILEGE,
                description=(
                    f"{target} declares a lifecycle hook ({', '.join(hooks_added)}) that runs "
                    "arbitrary code during `npm install`, and the hook is absent from the "
                    "package's declared GitHub source — an install-time code execution surface "
                    "introduced only in the published artifact."
                ),
                target=target,
                mitigations=_INSTALL_TIME_MITIGATIONS,
                package=name,
                version=version,
                rule_id="install_hook_added",
                file="package.json",
            )
        )
    elif profile.install_hooks:
        findings.append(
            _threat(
                name=f"Install-time lifecycle hook in {target}",
                stride_category=StrideCategory.ELEVATION_OF_PRIVILEGE,
                description=(
                    f"{target} declares a lifecycle hook ({', '.join(profile.install_hooks)}) "
                    "that executes arbitrary code during `npm install`, before any application "
                    "code runs."
                ),
                target=target,
                mitigations=_INSTALL_TIME_MITIGATIONS,
                package=name,
                version=version,
                rule_id="install_hook_present",
                file="package.json",
            )
        )

    # -- dynamic code loading/evaluation
    if CapabilityCategory.DYNAMIC_CODE in categories:
        evidence = _first_evidence(profile, CapabilityCategory.DYNAMIC_CODE)
        findings.append(
            _threat(
                name=f"Dynamic code loading in {target}",
                stride_category=StrideCategory.TAMPERING,
                description=(
                    f"{target} loads or evaluates code modules it does not statically declare "
                    "(e.g. dynamic require/import, eval, or new Function), which can be used to "
                    "load a payload at runtime that static analysis of the package won't see."
                ),
                target=target,
                mitigations=_DEFAULT_MITIGATIONS,
                package=name,
                version=version,
                rule_id="dynamic_code",
                file=evidence.file if evidence else None,
                line=evidence.line if evidence else None,
            )
        )

    # -- network + environment together: credential/env exfiltration surface
    if CapabilityCategory.NETWORK in categories and CapabilityCategory.ENVIRONMENT in categories:
        evidence = _first_evidence(profile, CapabilityCategory.NETWORK) or _first_evidence(
            profile, CapabilityCategory.ENVIRONMENT
        )
        findings.append(
            _threat(
                name=f"Environment/network surface in {target}",
                stride_category=StrideCategory.INFORMATION_DISCLOSURE,
                description=(
                    f"{target} both reads process environment variables and makes outbound "
                    "network calls, a combination consistent with credential or secret "
                    "exfiltration — legitimate for some packages, but worth confirming against "
                    "documented behavior."
                ),
                target=target,
                mitigations=_DEFAULT_MITIGATIONS,
                package=name,
                version=version,
                rule_id="network_environment",
                file=evidence.file if evidence else None,
                line=evidence.line if evidence else None,
            )
        )

    # -- native code / FFI: escapes the JS sandbox
    if CapabilityCategory.NATIVE_FFI in categories:
        evidence = _first_evidence(profile, CapabilityCategory.NATIVE_FFI)
        findings.append(
            _threat(
                name=f"Native code execution in {target}",
                stride_category=StrideCategory.ELEVATION_OF_PRIVILEGE,
                description=(
                    f"{target} loads native code (a compiled addon or FFI binding), which runs "
                    "outside the JavaScript sandbox with the same privileges as the host process."
                ),
                target=target,
                mitigations=_DEFAULT_MITIGATIONS,
                package=name,
                version=version,
                rule_id="native_ffi",
                file=evidence.file if evidence else None,
                line=evidence.line if evidence else None,
            )
        )

    return findings


_MAESTRO_SUFFIX = " This falls under the MAESTRO Supply Chain layer."


def dependency_threats(context: DependencyContext, framework: Framework) -> ThreatsList:
    """Deterministic threats for every analyzed package in `context`.

    Threat only carries a single `stride_category` field (MAESTRO seed
    patterns map to the nearest STRIDE equivalent too, in
    `backend.rules.engine`), so `framework` doesn't change the categorization
    — every dependency finding is inherently a supply-chain concern, so for
    Framework.MAESTRO the description is annotated with that layer instead.
    """
    threats: list[Threat] = []
    for pa in context.packages:
        threats.extend(_package_findings(pa))
    if framework == Framework.MAESTRO:
        for t in threats:
            t.description += _MAESTRO_SUFFIX
    return ThreatsList(threats=threats)


def merge_dependency_threats(
    dep_threats: ThreatsList, existing_threats: ThreatsList
) -> ThreatsList:
    """Merge deterministic dependency threats into an existing catalog.

    Deliberately does NOT go through `backend.rules.engine.merge_rule_and_llm_threats`
    (embedding-similarity dedup): dependency threat descriptions are
    templated and differ from each other only by package name/version, so
    semantic similarity collapses distinct per-package findings into one —
    5 packages sharing the same dynamic-code template merged down to 1 in
    testing. Distinctness for a dependency threat is its (package, rule_id)
    pair, not its wording, so dedup is exact-match on that instead.
    """
    if not dep_threats.threats:
        return existing_threats

    seen: set[tuple[str, str, str]] = {
        (t.dependency_ref.package, t.dependency_ref.version, t.dependency_ref.rule_id)
        for t in existing_threats.threats
        if t.source == "dependency" and t.dependency_ref is not None
    }
    unique = [
        t
        for t in dep_threats.threats
        if (t.dependency_ref.package, t.dependency_ref.version, t.dependency_ref.rule_id)
        not in seen
    ]
    return ThreatsList(threats=existing_threats.threats + unique)
