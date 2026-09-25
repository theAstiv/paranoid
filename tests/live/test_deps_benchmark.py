"""Live benchmark: scans ~50 popular npm packages against both sources.

Not part of the default test run — excluded by `-m "not live"` in
pyproject.toml's `addopts`. Hits the real npm registry, codeload.github.com,
and runs the real Semgrep binary. Run explicitly:

    pytest -m live tests/live/test_deps_benchmark.py -v

Each package is resolved at its current `dist-tags.latest` (not a pinned
version): the benchmark is meant to reflect the real, current state of these
packages' capabilities, and pinning would just go stale. A dated snapshot is
still written to `data/benchmarks/` so a run's numbers are always on record.

Three gates are what "the dependency engine is done" is measured against
(Week 2 plan, Session 5):

  - Failure-A gate: every pure-utility package shows zero shipped
    process/network/dynamic_code evidence.
  - Recall sanity: a handful of packages with a well-known real capability
    (express -> network, sharp/esbuild -> native_ffi, node-gyp -> process)
    are actually detected.
  - Drift precision gate: across the whole benchmark, at most 2 packages may
    show a drift `signal` (capabilities_only_in_tarball). Each one that does
    is expected to be triaged by hand, not treated as ground truth.

GitHub resolution rate (overall, and by which ref candidate matched) is
reported in the artifact but not gated — see the Week 2 plan's Session 0
reality check for why: it's expected to vary a lot by package.
"""

import asyncio
import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from backend.deps import scanner
from backend.models.enums import CapabilityCategory
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
# Below this success rate the run is treated as environment flakiness
# (offline, npm registry outage) rather than a real finding.
_MIN_SUCCESS_RATE = 0.7


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

    async def _one(name: str, client: httpx.AsyncClient) -> None:
        async with semaphore:
            try:
                version = await _resolve_latest_version(name, client)
                resolved, npm_profile, github_profile, drift = await _scan_one(
                    name, version, "both", client
                )
                results[name] = {
                    "ok": True,
                    "version": resolved.version,
                    "github_status": resolved.github_status,
                    "github_ref": resolved.github_ref,
                    "npm_profile": npm_profile,
                    "github_profile": github_profile,
                    "drift": drift,
                }
            except Exception as e:
                results[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

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


def _write_artifact(results: dict[str, dict], gate_report: dict) -> Path:
    _BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    json_path = _BENCHMARK_DIR / f"deps-{stamp}.json"

    json_safe = {}
    for name, entry in results.items():
        if not entry.get("ok"):
            json_safe[name] = entry
            continue
        json_safe[name] = {
            "ok": True,
            "version": entry["version"],
            "github_status": entry["github_status"],
            "github_ref": entry["github_ref"],
            "npm_categories": sorted(
                c.value
                for c in (entry["npm_profile"].category_set() if entry["npm_profile"] else [])
            ),
            "npm_status": entry["npm_profile"].status if entry["npm_profile"] else None,
            "drift_signal": entry["drift"].signal if entry["drift"] else None,
            "drift_status": entry["drift"].status if entry["drift"] else None,
        }
    json_path.write_text(
        json.dumps({"results": json_safe, "gates": gate_report}, indent=2), encoding="utf-8"
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
    lines.append("## Per-package")
    lines.append("| package | version | npm categories | github status | drift |")
    lines.append("|---|---|---|---|---|")
    for name in sorted(results):
        entry = json_safe[name]
        if not entry.get("ok"):
            lines.append(f"| {name} | - | ERROR: {entry['error']} | - | - |")
            continue
        cats = ", ".join(entry["npm_categories"]) or "(none)"
        drift = "signal" if entry["drift_signal"] else (entry["drift_status"] or "-")
        lines.append(
            f"| {name} | {entry['version']} | {cats} | {entry['github_status']} | {drift} |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path


@pytest.mark.asyncio
async def test_benchmark_scan_gates():
    results = await _scan_all(_ALL_PACKAGES)

    succeeded = {n: e for n, e in results.items() if e.get("ok")}
    success_rate = len(succeeded) / len(results)
    if success_rate < _MIN_SUCCESS_RATE:
        pytest.skip(
            f"Only {len(succeeded)}/{len(results)} packages resolved/scanned "
            f"successfully — treating as environment/network flakiness, not a finding."
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
    drift_signals = [
        name
        for name, e in succeeded.items()
        if e["drift"] is not None and e["drift"].status == "compared" and e["drift"].signal
    ]

    # --- Resolution-rate reporting (informational) ---
    resolved_count = sum(1 for e in succeeded.values() if e["github_status"] == "resolved")
    by_strategy: dict[str, int] = {}
    for entry in succeeded.values():
        strategy = _ref_strategy(entry)
        by_strategy[strategy] = by_strategy.get(strategy, 0) + 1

    gate_report = {
        "succeeded": len(succeeded),
        "total": len(results),
        "gates": {
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
        },
        "resolution": {
            "resolved": resolved_count,
            "total": len(succeeded),
            "by_strategy": by_strategy,
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
