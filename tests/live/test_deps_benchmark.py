"""Live benchmark: scans ~50 popular npm packages against both sources.

Not part of the default test run — excluded by `-m "not live"` in
pyproject.toml's `addopts`. Hits the real npm registry, codeload.github.com,
and runs the real Semgrep binary. Run explicitly:

    pytest -m live tests/live/test_deps_benchmark.py -v

Each package is resolved at its current `dist-tags.latest` (not a pinned
version): the benchmark is meant to reflect the real, current state of these
packages' capabilities, and pinning would just go stale. A dated snapshot is
still written to `data/benchmarks/` so a run's numbers are always on record.

Four gates are what "the dependency engine is done" is measured against
(Week 2 plan, Session 5 + the PR D hardening follow-up):

  - Failure-A gate: every pure-utility package shows zero shipped
    process/network/dynamic_code evidence.
  - Recall sanity: a handful of packages with a well-known real capability
    (express -> network, sharp/esbuild -> native_ffi, node-gyp -> process)
    are actually detected.
  - Drift precision gate: across the whole benchmark, at most 2 packages may
    show a drift `signal` (capabilities_only_in_tarball). Each one that does
    is expected to be triaged by hand, not treated as ground truth.
    `generated_unverifiable` files (see backend/deps/drift.py) never
    contribute to this — they need no separate exclusion here.
  - Drift coverage gate: of every package whose GitHub source actually
    resolved, at least 85% must reach `drift.status == "compared"` — the
    fixes in #91-#94 (scoped extraction, package discovery, the identity
    gate) exist specifically to make comparison possible, not just to avoid
    a wrong-tree false positive. Every package that didn't compare lists its
    `skip_reason` in the gate detail and the artifact's skip-reason
    histogram, so a coverage shortfall is diagnosable rather than an opaque
    percentage.

The artifact also reports (informational, not gated): GitHub resolution rate
by ref-candidate strategy, per-package `discovered_directory` /
`external_build_markers` / partial-fetch / unverifiable / relocated / weak
counts (both sides), and an external-build triage table for every
strong-signal package (does it have a repo-root build marker, and is the
signalling file declared by the *GitHub* repo's own manifest — never the
tarball's, which is attacker-controlled) — the "measure first" step the
hardening plan calls for before deciding whether the deferred repo-wide
second Semgrep pass (never built in this PR) is actually worth building
later.
"""

import asyncio
import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from backend.deps import scanner
from backend.deps.drift import _declared_manifest_paths, _load_package_json
from backend.deps.fetcher import cache_dir_for
from backend.deps.install_hooks import hook_node_files_from_package_json
from backend.models.enums import CapabilityCategory, SourceKind
from cli.commands.deps import _scan_one


pytestmark = [
    pytest.mark.live,
    pytest.mark.timeout(1800),
    pytest.mark.skipif(
        scanner.resolve_semgrep_binary() is None, reason="semgrep binary not installed"
    ),
]

_CONCURRENCY = 6
_BENCHMARK_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "benchmarks"

# Packages with no runtime dependencies and no legitimate reason to touch the
# network, spawn a process, or eval/require dynamic code — the Failure-A
# gate's negative-control set.
_PURE_UTILITIES = [
    "lodash",
    "ramda",
    "dayjs",
    "date-fns",
    "ms",
    "semver",
    "uuid",
    "nanoid",
    "clsx",
    "classnames",
    "camelcase",
    "kebab-case",
    "is-plain-object",
    "fast-deep-equal",
    "lru-cache",
    "mime-types",
    "qs",
    "query-string",
    "chalk",
    "picocolors",
    "ansi-styles",
    "leven",
    "type-fest",
    "p-limit",
    "p-queue",
    "zod",
]

_FRAMEWORKS = ["express", "fastify", "koa"]
_TOOLING_NATIVE = ["esbuild", "sharp", "node-gyp", "better-sqlite3"]
_AUTH = ["jsonwebtoken", "bcryptjs", "jose"]
_NETWORKING = ["axios", "ws", "got", "undici"]
_MONOREPO_SCOPED = ["@babel/core", "@babel/parser", "@jest/core", "@types/node"]

_ALL_PACKAGES = (
    _PURE_UTILITIES + _FRAMEWORKS + _TOOLING_NATIVE + _AUTH + _NETWORKING + _MONOREPO_SCOPED
)

# Recall sanity: packages with a well-known real capability that must show up
# in the npm-tarball scan. esbuild ships a platform binary selected at install
# time and *spawned* as a subprocess (no N-API bindings) — that's `process`,
# not `native_ffi`; `sharp` is the native_ffi example (a real .node addon).
_EXPECTED_CATEGORY = {
    "express": CapabilityCategory.NETWORK,
    "sharp": CapabilityCategory.NATIVE_FFI,
    "esbuild": CapabilityCategory.PROCESS,
    "node-gyp": CapabilityCategory.PROCESS,
}

_RISKY_FOR_FAILURE_A = frozenset(
    {CapabilityCategory.PROCESS, CapabilityCategory.NETWORK, CapabilityCategory.DYNAMIC_CODE}
)

_DRIFT_SIGNAL_MAX = 2
# Of every package whose GitHub source resolved, this fraction must actually
# reach drift.status == "compared" — #91-#94 exist specifically to make
# comparison possible (scoped extraction, package discovery, the identity
# gate), not just to avoid a wrong-tree false positive.
_MIN_DRIFT_COVERAGE = 0.85
# Below this success rate the run is treated as environment flakiness
# (offline, npm registry outage) rather than a real finding.
_MIN_SUCCESS_RATE = 0.7
# A package that fails only on a transient network error (after retries) is
# "unavailable" this run, not a scan finding — it's excluded from the other
# gates rather than counted against them. But too many unavailable packages
# means the run's data isn't trustworthy at all, so a distinct threshold
# fails the run outright instead of silently shrinking the sample.
_MAX_UNAVAILABLE_RATE = 0.10
_TRANSIENT_RETRIES = 3
_TRANSIENT_BACKOFF_S = 2.0
_TRANSIENT_EXC_TYPES = (
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


async def _resolve_latest_version(name: str, client: httpx.AsyncClient) -> str:
    from backend.deps.resolver import fetch_registry_doc

    doc = await fetch_registry_doc(name, client)
    latest = doc.get("dist-tags", {}).get("latest")
    if not latest:
        raise ValueError(f"{name} has no dist-tags.latest")
    return latest


async def _scan_all(packages: list[str]) -> dict[str, dict]:
    semaphore = asyncio.Semaphore(_CONCURRENCY)
    results: dict[str, dict] = {}

    async def _attempt(name: str, client: httpx.AsyncClient) -> dict:
        version = await _resolve_latest_version(name, client)
        resolved, npm_profile, github_profile, drift = await _scan_one(
            name, version, "both", client
        )
        return {
            "ok": True,
            "unavailable": False,
            "version": resolved.version,
            "github_status": resolved.github_status,
            "github_ref": resolved.github_ref,
            "npm_profile": npm_profile,
            "github_profile": github_profile,
            "drift": drift,
        }

    async def _one(name: str, client: httpx.AsyncClient) -> None:
        async with semaphore:
            last_error: Exception | None = None
            for attempt in range(_TRANSIENT_RETRIES):
                try:
                    results[name] = await _attempt(name, client)
                    return
                except _TRANSIENT_EXC_TYPES as e:
                    last_error = e
                    if attempt < _TRANSIENT_RETRIES - 1:
                        await asyncio.sleep(_TRANSIENT_BACKOFF_S * (attempt + 1))
                    continue
                except Exception as e:
                    # Non-transient failure: not retried, not "unavailable" —
                    # a real finding worth surfacing (e.g. a corrupt tarball,
                    # a bug in the scan pipeline).
                    results[name] = {
                        "ok": False,
                        "unavailable": False,
                        "error": f"{type(e).__name__}: {e}",
                    }
                    return
            # Exhausted retries on a transient network error only.
            results[name] = {
                "ok": False,
                "unavailable": True,
                "error": f"{type(last_error).__name__}: {last_error} "
                f"(after {_TRANSIENT_RETRIES} attempts)",
            }

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*(_one(n, client) for n in packages))
    return results


def _ref_strategy(entry: dict) -> str:
    """Classify which candidate ref actually resolved, for the resolution-rate breakdown."""
    if entry.get("github_status") != "resolved":
        return "unresolved"
    ref = entry.get("github_ref")
    version = entry.get("version")
    if ref == version:
        return "bare_version"
    if ref == f"v{version}":
        return "v_prefixed"
    if ref and ref.endswith(f"@{version}"):
        return "name_at_version"
    return "git_head"


def _promoted_count(profile) -> int:
    """Files reclassified SHIPPED via reachability/install-time promotion
    (`CapabilityEvidence.reclassified_from`) — informational, from PR B."""
    if profile is None:
        return 0
    return sum(1 for e in profile.evidence if e.reclassified_from is not None)


def _package_row(entry: dict) -> dict:
    """Flatten one `_scan_all` entry into the JSON-safe extended fields (#91-#94)
    the benchmark never surfaced before PR D — every field here already
    existed on `CapabilityProfile`/`DriftReport`, just unreported."""
    npm_profile = entry["npm_profile"]
    github_profile = entry["github_profile"]
    drift = entry["drift"]

    row = {
        "ok": True,
        "version": entry["version"],
        "github_status": entry["github_status"],
        "github_ref": entry["github_ref"],
        "npm_categories": sorted(
            c.value for c in (npm_profile.category_set() if npm_profile else [])
        ),
        "npm_status": npm_profile.status if npm_profile else None,
        "npm_partial_fetch": npm_profile.status == "partial_fetch" if npm_profile else False,
        "npm_skipped_long_paths": npm_profile.skipped_long_paths if npm_profile else 0,
        "npm_skipped_link_names_count": len(npm_profile.skipped_link_names) if npm_profile else 0,
        "npm_promoted_count": _promoted_count(npm_profile),
        "github_discovered_directory": github_profile.discovered_directory
        if github_profile
        else None,
        "github_external_build_markers": list(github_profile.external_build_markers)
        if github_profile
        else [],
        "github_partial_fetch": github_profile.status == "partial_fetch"
        if github_profile
        else False,
        "github_skipped_long_paths": github_profile.skipped_long_paths if github_profile else 0,
        "github_skipped_link_names_count": len(github_profile.skipped_link_names)
        if github_profile
        else 0,
        "github_promoted_count": _promoted_count(github_profile),
        "drift_signal": drift.signal if drift else None,
        "drift_status": drift.status if drift else None,
        "drift_skip_reason": drift.skip_reason if drift else None,
        "drift_signal_categories": sorted(c.value for c in drift.signal_categories)
        if drift
        else [],
        "drift_unverifiable_count": len(drift.unverifiable) if drift else 0,
        "drift_generated_unverifiable_count": len(drift.generated_unverifiable) if drift else 0,
        "drift_relocated_count": len(drift.relocated) if drift else 0,
        "drift_new_evidence_in_matched_count": len(drift.new_evidence_in_matched) if drift else 0,
        "drift_install_hooks_added": list(drift.install_hooks_added) if drift else [],
        "drift_install_hooks_added_benign": list(drift.install_hooks_added_benign) if drift else [],
    }
    return row


def _declared_on_github(rel_path: str, name: str, version: str) -> bool:
    """Whether `rel_path` is an *exact* path declared by the GitHub repo's
    own manifest (main/bin/exports, or a lifecycle-hook target) — reusing
    `backend.deps.drift`'s own check so the triage table answers exactly the
    question `_is_generated_unverifiable` asks (deliberately exact-path-only,
    no declared-directory excuse — see that function's docstring), against
    the same cached GitHub source `_scan_one` already fetched."""
    github_dir = cache_dir_for(SourceKind.GITHUB, name, version)
    package_json = _load_package_json(github_dir)
    declared = _declared_manifest_paths(package_json) | hook_node_files_from_package_json(
        package_json
    )
    return rel_path in declared


def _external_build_triage(name: str, entry: dict, row: dict) -> dict | None:
    """For a strong-signal package, note whether the GitHub side has a
    repo-root build marker and whether each signalling file is declared by
    the *GitHub* repo's own manifest — the "measure first" data point the
    hardening plan calls for before deciding whether the deferred repo-wide
    second Semgrep pass is worth building. A file already excused into
    `generated_unverifiable` never reaches `signal_files`, so every row here
    is a case that PR D's per-file excuse did *not* catch — either correctly
    (no marker, or a GitHub-undeclared file — e.g. an attacker's own
    self-declared payload, which must never be excused) or a gap worth a
    follow-up look."""
    drift = entry["drift"]
    if drift is None or not drift.signal:
        return None
    markers = row["github_external_build_markers"]
    version = row["version"]
    return {
        "package": name,
        "signal_files": sorted(drift.signal_files),
        "has_external_build_marker": bool(markers),
        "external_build_markers": markers,
        "declared_on_github": {
            f: _declared_on_github(f, name, version) for f in sorted(drift.signal_files)
        },
    }


def _write_artifact(results: dict[str, dict], gate_report: dict) -> Path:
    _BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    json_path = _BENCHMARK_DIR / f"deps-{stamp}.json"

    json_safe = {}
    for name, entry in results.items():
        if not entry.get("ok"):
            json_safe[name] = entry
            continue
        json_safe[name] = _package_row(entry)

    triage = [
        row
        for name, entry in sorted(results.items())
        if entry.get("ok") and (row := _external_build_triage(name, entry, json_safe[name]))
    ]

    json_path.write_text(
        json.dumps(
            {"results": json_safe, "gates": gate_report, "external_build_triage": triage},
            indent=2,
        ),
        encoding="utf-8",
    )

    md_path = _BENCHMARK_DIR / f"deps-{stamp}.md"
    lines = [f"# Dependency engine benchmark — {stamp}", ""]
    lines.append(f"Packages: {len(results)}, succeeded: {gate_report['succeeded']}")
    lines.append("")
    lines.append("## Gates")
    for gate_name, gate_result in gate_report["gates"].items():
        status = "PASS" if gate_result["passed"] else "FAIL"
        lines.append(f"- **{gate_name}**: {status} — {gate_result['detail']}")
    lines.append("")
    lines.append("## GitHub resolution rate")
    lines.append(
        f"resolved: {gate_report['resolution']['resolved']}/{gate_report['resolution']['total']}"
    )
    for strategy, count in gate_report["resolution"]["by_strategy"].items():
        lines.append(f"  - {strategy}: {count}")
    lines.append("")
    lines.append("## Drift coverage")
    coverage = gate_report["coverage"]
    lines.append(f"compared: {coverage['compared']}/{coverage['github_resolved']}")
    if coverage["skip_reason_histogram"]:
        lines.append("skip-reason histogram:")
        for reason, count in sorted(coverage["skip_reason_histogram"].items()):
            lines.append(f"  - {reason}: {count}")
    lines.append("")
    if triage:
        lines.append("## External-build triage (strong-signal packages)")
        lines.append("| package | signal file | declared on GitHub? | build marker? | markers |")
        lines.append("|---|---|---|---|---|")
        for row in triage:
            for f in row["signal_files"]:
                lines.append(
                    f"| {row['package']} | {f} | {row['declared_on_github'][f]} | "
                    f"{row['has_external_build_marker']} | "
                    f"{', '.join(row['external_build_markers'])} |"
                )
        lines.append("")
    lines.append("## Per-package")
    lines.append(
        "| package | version | npm categories | github status | drift | "
        "unverifiable | generated_unverifiable | discovered dir | build markers |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for name in sorted(results):
        entry = json_safe[name]
        if not entry.get("ok"):
            lines.append(f"| {name} | - | ERROR: {entry['error']} | - | - | - | - | - | - |")
            continue
        cats = ", ".join(entry["npm_categories"]) or "(none)"
        drift = "signal" if entry["drift_signal"] else (entry["drift_status"] or "-")
        lines.append(
            f"| {name} | {entry['version']} | {cats} | {entry['github_status']} | {drift} | "
            f"{entry['drift_unverifiable_count']} | {entry['drift_generated_unverifiable_count']} | "
            f"{entry['github_discovered_directory'] or '-'} | "
            f"{', '.join(entry['github_external_build_markers']) or '-'} |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path


@pytest.mark.asyncio
async def test_benchmark_scan_gates():
    results = await _scan_all(_ALL_PACKAGES)

    unavailable = {n: e for n, e in results.items() if e.get("unavailable")}
    unavailable_rate = len(unavailable) / len(results) if results else 0.0
    assert unavailable_rate <= _MAX_UNAVAILABLE_RATE, (
        f"{len(unavailable)}/{len(results)} packages ({unavailable_rate:.0%}) were "
        f"unavailable after {_TRANSIENT_RETRIES} retries each — the network is too "
        f"unreliable for this run's results to mean anything: "
        f"{sorted(unavailable)}"
    )

    # Packages that stayed unavailable after retries are excluded from the
    # sample the other gates measure over — they were never really scanned,
    # so they shouldn't count as either a pass or a failure of any gate.
    succeeded = {n: e for n, e in results.items() if e.get("ok")}
    gateable_total = len(results) - len(unavailable)
    success_rate = len(succeeded) / gateable_total if gateable_total else 1.0
    if success_rate < _MIN_SUCCESS_RATE:
        pytest.skip(
            f"Only {len(succeeded)}/{gateable_total} non-network-flaky packages "
            f"resolved/scanned successfully — treating as environment flakiness, "
            f"not a finding."
        )

    # --- Failure-A gate: pure utilities carry no risky shipped evidence ---
    # An unscanned utility is a gate failure, not something to skip past —
    # otherwise the gate can report PASS while silently checking nothing.
    failure_a_violations = []
    for name in _PURE_UTILITIES:
        entry = succeeded.get(name)
        if entry is None or entry["npm_profile"] is None:
            failure_a_violations.append(f"{name}: not scanned")
            continue
        if entry["npm_profile"].status != "ok":
            failure_a_violations.append(f"{name}: scan status={entry['npm_profile'].status}")
            continue
        risky = entry["npm_profile"].category_set() & _RISKY_FOR_FAILURE_A
        if risky:
            failure_a_violations.append(f"{name}: {sorted(c.value for c in risky)}")

    # --- Recall sanity: known capabilities are actually detected ---
    recall_misses = []
    for name, expected in _EXPECTED_CATEGORY.items():
        entry = succeeded.get(name)
        if entry is None or entry["npm_profile"] is None or entry["npm_profile"].status != "ok":
            recall_misses.append(f"{name}: not scanned")
            continue
        if expected not in entry["npm_profile"].category_set():
            recall_misses.append(f"{name}: expected {expected.value}, got nothing")

    # --- Drift precision gate ---
    # generated_unverifiable files (backend/deps/drift.py) never set `signal`,
    # so no separate exclusion is needed here to keep this gate honest.
    drift_signals = [
        name
        for name, e in succeeded.items()
        if e["drift"] is not None and e["drift"].status == "compared" and e["drift"].signal
    ]

    # --- Drift coverage gate ---
    # Of every package whose GitHub source actually resolved, most should
    # reach a real comparison — #91-#94 exist specifically to make that
    # possible. A package that resolved but never compared lists its
    # skip_reason, so a shortfall is diagnosable rather than one opaque
    # percentage.
    github_resolved_entries = {
        name: e for name, e in succeeded.items() if e["github_status"] == "resolved"
    }
    compared_entries = {
        name: e
        for name, e in github_resolved_entries.items()
        if e["drift"] is not None and e["drift"].status == "compared"
    }
    skip_reason_histogram: dict[str, int] = {}
    coverage_misses: list[str] = []
    for name, e in github_resolved_entries.items():
        if name in compared_entries:
            continue
        reason = e["drift"].skip_reason if e["drift"] is not None else "drift_not_attempted"
        reason = reason or "(unspecified)"
        skip_reason_histogram[reason] = skip_reason_histogram.get(reason, 0) + 1
        coverage_misses.append(f"{name}: {reason}")

    coverage_rate = (
        len(compared_entries) / len(github_resolved_entries) if github_resolved_entries else 1.0
    )

    # --- Resolution-rate reporting (informational) ---
    resolved_count = len(github_resolved_entries)
    by_strategy: dict[str, int] = {}
    for entry in succeeded.values():
        strategy = _ref_strategy(entry)
        by_strategy[strategy] = by_strategy.get(strategy, 0) + 1

    gate_report = {
        "succeeded": len(succeeded),
        "total": len(results),
        "unavailable": len(unavailable),
        "unavailable_rate": unavailable_rate,
        "unavailable_packages": sorted(unavailable),
        "gates": {
            "network_availability": {
                "passed": unavailable_rate <= _MAX_UNAVAILABLE_RATE,
                "detail": (
                    f"{len(unavailable)}/{len(results)} unavailable after "
                    f"{_TRANSIENT_RETRIES} retries ({unavailable_rate:.0%}, max "
                    f"{_MAX_UNAVAILABLE_RATE:.0%}): {sorted(unavailable)}"
                ),
            },
            "failure_a": {
                "passed": not failure_a_violations,
                "detail": "; ".join(failure_a_violations) or "no risky evidence in pure utilities",
            },
            "recall_sanity": {
                "passed": not recall_misses,
                "detail": "; ".join(recall_misses) or "all expected capabilities detected",
            },
            "drift_precision": {
                "passed": len(drift_signals) <= _DRIFT_SIGNAL_MAX,
                "detail": f"{len(drift_signals)} signal(s): {drift_signals}",
            },
            "drift_coverage": {
                "passed": coverage_rate >= _MIN_DRIFT_COVERAGE,
                "detail": (
                    f"{len(compared_entries)}/{len(github_resolved_entries)} compared "
                    f"({coverage_rate:.0%}); misses: {coverage_misses}"
                ),
            },
        },
        "resolution": {
            "resolved": resolved_count,
            "total": len(succeeded),
            "by_strategy": by_strategy,
        },
        "coverage": {
            "compared": len(compared_entries),
            "github_resolved": len(github_resolved_entries),
            "skip_reason_histogram": skip_reason_histogram,
        },
    }

    artifact_path = _write_artifact(results, gate_report)

    assert not failure_a_violations, (
        f"Failure-A gate: pure utilities showed risky capabilities: {failure_a_violations} "
        f"(see {artifact_path})"
    )
    assert not recall_misses, f"Recall sanity gate failed: {recall_misses} (see {artifact_path})"
    assert len(drift_signals) <= _DRIFT_SIGNAL_MAX, (
        f"Drift precision gate: {len(drift_signals)} packages showed a drift signal "
        f"(max {_DRIFT_SIGNAL_MAX}): {drift_signals} (see {artifact_path})"
    )
    assert coverage_rate >= _MIN_DRIFT_COVERAGE, (
        f"Drift coverage gate: only {len(compared_entries)}/{len(github_resolved_entries)} "
        f"resolved packages compared ({coverage_rate:.0%}, need >= {_MIN_DRIFT_COVERAGE:.0%}): "
        f"{coverage_misses} (see {artifact_path})"
    )


# ---------------------------------------------------------------------------
# Historical versions still on npm (flexible, informational — Week 2 plan
# Session 6). The actual malicious versions of ua-parser-js and event-stream
# were unpublished; these are benign hops either side of the real incidents,
# so this only asserts the delta computes cleanly end to end against real
# registry data. Detection of the incidents themselves is covered by the
# inert reconstructions in tests/test_deps_incidents.py.
# ---------------------------------------------------------------------------
_HISTORICAL_PAIRS = [
    ("ua-parser-js", "0.7.28", "0.7.30"),
    ("event-stream", "3.3.4", "3.3.5"),
]


@pytest.mark.asyncio
async def test_historical_version_deltas_compute_cleanly():
    from backend.deps.delta import compute_delta
    from backend.deps.fetcher import fetch_source
    from backend.deps.resolver import resolve_npm
    from backend.deps.scanner import scan_source
    from backend.models.enums import SourceKind

    # Each pair is independent: one unavailable (since-unpublished) version
    # must not prevent the other pair from being checked. Only the expected
    # "this version isn't on the registry" (ValueError from resolve_npm) and
    # transient HTTP failures are treated as "unavailable, skip this pair" —
    # a FetchError (hostile/corrupt tarball) is a real finding against a real
    # historical package and must fail the test loudly, not disappear into
    # this list. Skips are collected and reported even when the other pair
    # succeeded, so a real problem with one pair is never silently dropped
    # just because the other one worked.
    unavailable: list[str] = []
    checked: list[str] = []

    async with httpx.AsyncClient() as client:
        for name, prev_version, curr_version in _HISTORICAL_PAIRS:
            pair_label = f"{name} {prev_version}->{curr_version}"
            try:
                prev_resolved = await resolve_npm(name, prev_version, client)
                curr_resolved = await resolve_npm(name, curr_version, client)
                prev_path = (await fetch_source(prev_resolved, SourceKind.NPM_TARBALL, client)).path
                curr_path = (await fetch_source(curr_resolved, SourceKind.NPM_TARBALL, client)).path
            except (httpx.HTTPStatusError, ValueError) as e:
                unavailable.append(f"{pair_label}: {type(e).__name__}: {e}")
                continue

            if prev_path is None or curr_path is None:
                unavailable.append(f"{pair_label}: npm tarball source not available")
                continue

            prev_profile = await scan_source(
                prev_path, SourceKind.NPM_TARBALL, name=name, version=prev_version
            )
            curr_profile = await scan_source(
                curr_path, SourceKind.NPM_TARBALL, name=name, version=curr_version
            )
            if prev_profile.status != "ok" or curr_profile.status != "ok":
                unavailable.append(f"{pair_label}: scan did not finish cleanly")
                continue

            delta = compute_delta(prev_resolved, curr_resolved, prev_profile, curr_profile)
            assert delta.previous_version == prev_version, pair_label
            assert delta.current_version == curr_version, pair_label
            checked.append(pair_label)

    if unavailable:
        warnings.warn(
            f"{len(unavailable)}/{len(_HISTORICAL_PAIRS)} historical pair(s) unavailable, "
            f"skipped: {unavailable}",
            stacklevel=1,
        )
    if not checked:
        pytest.skip(f"No historical pair was available to check: {unavailable}")
