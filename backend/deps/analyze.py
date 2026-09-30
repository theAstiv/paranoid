"""Package- and manifest-level dependency analysis orchestration.

Composes `backend.deps.resolver` + `.fetcher` + `.scanner` + `.drift` into two
entry points: `analyze_package()` for one `name@version`, and
`analyze_manifest()` for every direct dependency declared in a package.json
(plus an optional lockfile). Used by the CLI (`paranoid deps scan` /
`scan-manifest`), the live benchmark, and the pipeline's ANALYZE_DEPENDENCIES
step — one implementation, three callers.
"""

import asyncio
import contextlib
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

from backend.deps.drift import compare_sources
from backend.deps.fetcher import FetchError, cache_dir_for, fetch_source, mark_in_use
from backend.deps.resolver import resolve_github_ref, resolve_npm
from backend.deps.scanner import scan_source
from backend.models.dependencies import (
    CapabilityProfile,
    DependencyContext,
    DriftReport,
    PackageAnalysis,
    PackageRef,
    ResolvedPackage,
)
from backend.models.enums import SourceKind


logger = logging.getLogger(__name__)

_MANIFEST_CONCURRENCY = 4
DEFAULT_MAX_DIRECT_DEPENDENCIES = 50

_EXACT_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


async def fetch_and_scan_one(
    resolved: ResolvedPackage, kind: SourceKind, client: httpx.AsyncClient
) -> tuple[Path | None, CapabilityProfile | None, str | None]:
    """Fetch + scan one source.

    Returns (path, profile, skip_reason) — `skip_reason` is set exactly when
    `path` is None, so the caller can label *why* a source wasn't compared
    instead of collapsing every skip into one opaque status.

    For GitHub only, a hostile/corrupt tarball degrades this source to
    "unavailable" rather than raising — the same outcome as GitHub not
    resolving — so a real repo tripping the safety net on one file (e.g. a
    legitimate symlink) never discards results already obtained from the npm
    side in `analyze_package`. The npm tarball is the primary,
    integrity-checked source: a hostile/tampered *npm* tarball (integrity
    mismatch, path traversal, symlink member) is exactly the kind of finding
    this engine exists to surface, so it still raises — silently reporting it
    as "(not scanned)" would hide a flagged dependency behind an ordinary miss.
    """
    if kind == SourceKind.GITHUB:
        try:
            result = await fetch_source(resolved, kind, client)
        except FetchError as e:
            logger.warning(
                "GitHub fetch rejected for %s@%s: %s — treating GitHub source as unavailable",
                resolved.name,
                resolved.version,
                e,
            )
            return None, None, f"github_fetch_rejected:{type(e).__name__}"
    else:
        result = await fetch_source(resolved, kind, client)
    if result.path is None:
        return None, None, result.reason
    # Eviction protection for this path is the caller's job (analyze_package
    # marks it in-use for the whole fetch+scan+drift span before calling
    # this function) — not scoped here, so there's no gap between this
    # function's own work finishing and the caller's drift comparison
    # starting.
    profile = await scan_source(result.path, kind, name=resolved.name, version=resolved.version)
    if (
        result.skipped_long_paths
        or result.skipped_link_names
        or result.discovered_directory
        or result.external_build_markers
    ):
        # Fetch-time skips (and a discovered package directory) are recorded
        # on the profile itself (not just logged) so they survive into
        # downstream JSON output and the capability grid. Downgrading status
        # away from "ok" to "partial_fetch" flags the scan as incomplete
        # without drift.py needing to know about fetch-time skips itself —
        # but drift.compare_sources still runs on a partial_fetch profile
        # (only a semgrep_* status skips it entirely); the affected paths
        # land in its `unverifiable` bucket instead of disabling the
        # comparison outright.
        updates: dict = {
            "skipped_long_paths": result.skipped_long_paths,
            "skipped_link_names": list(result.skipped_link_names),
            "skipped_long_path_names": list(result.skipped_long_path_names),
            "discovered_directory": result.discovered_directory,
            "external_build_markers": list(result.external_build_markers),
        }
        if result.skipped_long_paths and profile.status == "ok":
            updates["status"] = "partial_fetch"
        profile = profile.model_copy(update=updates)
    return result.path, profile, None


async def analyze_package(
    name: str, version: str, source_mode: str, client: httpx.AsyncClient
) -> PackageAnalysis:
    """Resolve + fetch + scan one `name@version` for the requested source(s).

    `source_mode` is one of "npm", "github", "both". Drift is only computed
    when both sources were requested — it stays None (not attempted) rather
    than taking on a status otherwise.
    """
    want_npm = source_mode in ("npm", "both")
    want_github = source_mode in ("github", "both")
    ref = PackageRef(name=name, version=version)

    resolved = await resolve_npm(name, version, client)
    if want_github:
        resolved = await resolve_github_ref(resolved, client)

    # Marked in-use for the entire fetch+scan+drift span, starting *before*
    # either source is fetched — not just around the drift comparison at the
    # end. cache_dir_for() is deterministic from (kind, name, version) alone,
    # so the eventual fetch path is already known here, before fetch_source
    # even runs. A narrower window (e.g. only wrapping scan_source, or only
    # wrapping the drift comparison) leaves gaps — the GitHub fetch itself,
    # or the time between npm's scan finishing and drift starting — where a
    # concurrent fetch for a *different* package could still evict this
    # entry and turn a scan-time gap into a false supply-chain drift alarm.
    async with contextlib.AsyncExitStack() as stack:
        if want_npm:
            await stack.enter_async_context(
                mark_in_use(cache_dir_for(SourceKind.NPM_TARBALL, resolved.name, resolved.version))
            )
        if want_github:
            await stack.enter_async_context(
                mark_in_use(cache_dir_for(SourceKind.GITHUB, resolved.name, resolved.version))
            )

        tarball_path = tarball_profile = tarball_skip_reason = None
        if want_npm:
            tarball_path, tarball_profile, tarball_skip_reason = await fetch_and_scan_one(
                resolved, SourceKind.NPM_TARBALL, client
            )

        github_path = github_profile = github_skip_reason = None
        if want_github:
            github_path, github_profile, github_skip_reason = await fetch_and_scan_one(
                resolved, SourceKind.GITHUB, client
            )

        drift = None
        if want_npm and want_github:
            if tarball_path is None or tarball_profile is None:
                # compare_sources requires a resolved tarball dir/profile — this is
                # the npm side failing to fetch, not GitHub, so it gets its own label.
                drift = DriftReport(
                    name=name,
                    version=version,
                    status="skipped_npm_unavailable",
                    skip_reason=tarball_skip_reason,
                )
            else:
                drift = compare_sources(
                    name, version, tarball_path, tarball_profile, github_path, github_profile
                )
                if drift.status == "skipped_github_unavailable" and github_skip_reason:
                    drift = drift.model_copy(update={"skip_reason": github_skip_reason})
                elif drift.status == "skipped_scan_incomplete":
                    incomplete_sides = [
                        side
                        for side, profile in (("npm", tarball_profile), ("github", github_profile))
                        if profile is not None and profile.status != "ok"
                    ]
                    drift = drift.model_copy(
                        update={"skip_reason": f"scan_incomplete:{','.join(incomplete_sides)}"}
                    )

    return PackageAnalysis(
        ref=ref,
        resolved=resolved,
        npm_profile=tarball_profile,
        github_profile=github_profile,
        drift=drift,
    )


def parse_lockfile_versions(lockfile_data: dict[str, Any]) -> dict[str, str]:
    """Extract {name: pinned_version} from a parsed v1, v2, or v3 package-lock.json."""
    if not isinstance(lockfile_data, dict):
        return {}

    versions: dict[str, str] = {}
    packages = lockfile_data.get("packages")
    if isinstance(packages, dict):
        # v2/v3: keyed by "node_modules/<name>" (top-level only — nested paths
        # like "node_modules/a/node_modules/b" are transitive deps of another
        # package, not a direct dependency of this manifest).
        for key, info in packages.items():
            if not key.startswith("node_modules/"):
                continue
            rel = key[len("node_modules/") :]
            if "node_modules/" in rel:
                continue
            if isinstance(info, dict) and isinstance(info.get("version"), str):
                versions[rel] = info["version"]
        return versions

    dependencies = lockfile_data.get("dependencies")
    if isinstance(dependencies, dict):
        # v1
        for dep_name, info in dependencies.items():
            if isinstance(info, dict) and isinstance(info.get("version"), str):
                versions[dep_name] = info["version"]
    return versions


def pin_from_range(range_str: str) -> str | None:
    """Best-effort literal version from a semver range, when there's no lockfile.

    Only strips a leading ^ or ~ — anything else (a range with a space, an
    'x'/'*' wildcard, a git/file/url spec, an OR range) is not a single
    pinnable version, so it's left for the caller to skip.
    """
    stripped = range_str.strip().lstrip("^~")
    return stripped if _EXACT_VERSION_RE.match(stripped) else None


def direct_dependencies_from_manifest(manifest_data: dict[str, Any]) -> dict[str, str]:
    """{name: version_range} for every dependencies + devDependencies entry."""
    direct: dict[str, str] = {}
    for section in ("dependencies", "devDependencies"):
        entries = manifest_data.get(section)
        if isinstance(entries, dict):
            direct.update({k: v for k, v in entries.items() if isinstance(v, str)})
    return direct


def count_resolvable_direct_dependencies(
    manifest_data: dict[str, Any], lockfile_data: dict[str, Any] | None
) -> int:
    """How many direct dependencies analyze_manifest() will actually attempt
    to analyze — i.e. the same `targets` computation it does internally
    (pinned by the lockfile, or by a caret/tilde range), before its own
    max_direct_dependencies cap. Shared by every caller that pre-validates a
    manifest against DEFAULT_MAX_DIRECT_DEPENDENCIES before calling
    analyze_manifest() (the API route and the CLI's --manifest flag), so a
    naive count of every "dependencies" entry doesn't disagree with what the
    analyzer will actually do: a git/file/url spec or an unresolvable range
    (e.g. "^1 || ^2") is declared but never becomes a target, while a
    lockfile (when present) can pin a range the manifest alone couldn't.
    """
    direct = direct_dependencies_from_manifest(manifest_data)
    lockfile_versions = parse_lockfile_versions(lockfile_data) if lockfile_data else {}
    return sum(
        1
        for pkg_name, range_str in direct.items()
        if lockfile_versions.get(pkg_name) or pin_from_range(range_str)
    )


async def analyze_manifest(
    manifest_data: dict[str, Any],
    lockfile_data: dict[str, Any] | None,
    source_mode: str = "npm",
    client: httpx.AsyncClient | None = None,
    max_direct_dependencies: int | None = DEFAULT_MAX_DIRECT_DEPENDENCIES,
    deadline: float | None = None,
) -> DependencyContext:
    """Analyze every direct dependency declared in a package.json.

    Versions are taken from the lockfile when present (v1/v2/v3 all
    supported); otherwise a caret/tilde range like "^5.3.0" is pinned to its
    literal floor version. Anything else (a range with a space, an OR range,
    a git/file/url spec) is skipped and reported in `.skipped`, since it has
    no single resolvable version. Direct dependencies beyond
    `max_direct_dependencies` are also skipped (deterministically, by sorted
    name) rather than silently analyzed in an unbounded sweep — pass None to
    disable the cap entirely (the CLI's `scan-manifest` does this, to keep
    its own long-standing unlimited behavior; the pipeline's automated
    ANALYZE_DEPENDENCIES step relies on the default cap).

    One dependency's failure (network, a hostile tarball, a filesystem error)
    is captured on its own `PackageAnalysis.error` and never aborts the sweep.

    `deadline` (a `time.monotonic()` timestamp) makes a time-budgeted sweep
    return whatever finished instead of an all-or-nothing failure: a package
    whose turn comes up after the deadline is skipped with reason
    "time_budget" instead of started, and one already running when the
    deadline passes is cancelled individually (skipped the same way) rather
    than aborting every other in-flight package alongside it. None (the
    default) means no budget — the sweep runs to completion.

    `packages` in the returned context is sorted by name — analysis runs
    concurrently, so insertion order would otherwise follow whichever scan
    finishes first, varying run to run. A stable order matters both for the
    deterministic-first contract and because `dependency_context` feeds a
    prompt-cached block (`build_shared_context`); a reordered block would
    invalidate the cache on every run even when nothing changed.
    """
    direct = direct_dependencies_from_manifest(manifest_data)
    lockfile_versions = parse_lockfile_versions(lockfile_data) if lockfile_data else {}

    targets: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for pkg_name, range_str in direct.items():
        pinned = lockfile_versions.get(pkg_name) or pin_from_range(range_str)
        if pinned is None:
            skipped[pkg_name] = "unresolvable_version_range"
        else:
            targets[pkg_name] = pinned

    if max_direct_dependencies is not None and len(targets) > max_direct_dependencies:
        overflow = sorted(targets)[max_direct_dependencies:]
        for name in overflow:
            skipped[name] = "exceeds_direct_dependency_cap"
            del targets[name]

    packages: list[PackageAnalysis] = []
    semaphore = asyncio.Semaphore(_MANIFEST_CONCURRENCY)

    async def _one(pkg_name: str, pkg_version: str, http_client: httpx.AsyncClient) -> None:
        async with semaphore:
            remaining: float | None = None
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    skipped[pkg_name] = "time_budget"
                    return
            try:
                if remaining is not None:
                    result = await asyncio.wait_for(
                        analyze_package(pkg_name, pkg_version, source_mode, http_client),
                        timeout=remaining,
                    )
                else:
                    result = await analyze_package(pkg_name, pkg_version, source_mode, http_client)
                packages.append(result)
            except TimeoutError:
                # The deadline passed mid-analysis for this package — skip it
                # and let the sweep return whatever already finished, instead
                # of the caller's outer wait_for discarding everything.
                skipped[pkg_name] = "time_budget"
            except Exception as e:
                # One dependency's failure must never abort the whole manifest sweep.
                packages.append(
                    PackageAnalysis(
                        ref=PackageRef(name=pkg_name, version=pkg_version),
                        error=f"{type(e).__name__}: {e}",
                    )
                )

    if client is not None:
        await asyncio.gather(*(_one(n, v, client) for n, v in targets.items()))
    else:
        async with httpx.AsyncClient() as owned_client:
            await asyncio.gather(*(_one(n, v, owned_client) for n, v in targets.items()))

    packages.sort(key=lambda pa: pa.ref.name)
    return DependencyContext(packages=packages, skipped=skipped, source_mode=source_mode)


# Cap on `context.skipped` rows turned into DB rows by `dependency_scan_rows()`.
# `skipped` keys are raw, unvalidated package.json keys (a manifest key with an
# unresolvable version range is skipped before any name regex ever runs), so
# without a cap a manifest crafted with thousands of bogus dependency keys
# would become thousands of dependency_scans INSERTs.
MAX_SKIPPED_DEPENDENCY_ROWS = 50


def dependency_scan_rows(
    context: DependencyContext,
) -> list[tuple[str, str, dict[str, Any]]]:
    """Flatten a `DependencyContext` into `(package, version, analysis)` rows
    ready for `backend.db.crud.create_dependency_scan`. Shared by the CLI
    persistence path (`backend.db.persist`) and the API's SSE persistence
    path (`backend.routes.models`) so the row shape and the cap below live
    in exactly one place.

    Every `PackageAnalysis` is included — using `pa.ref`'s name/version when
    resolution failed (`pa.resolved` is None) — so a package that errored
    out is still visible instead of silently dropped.

    `context.skipped` entries (dropped *before* analysis ever ran: no
    resolvable pinned version, or over the manifest's direct-dependency cap)
    get their own row with `skip_reason` set, not `error` — `error` is
    reserved for a `PackageAnalysis` that was actually attempted and failed,
    so the UI can tell "we didn't look at this" from "we looked and it broke".
    Capped at `MAX_SKIPPED_DEPENDENCY_ROWS`, sorted by name for a stable
    order; any excess collapses into one summary row.
    """
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for pa in context.packages:
        package = pa.resolved.name if pa.resolved else pa.ref.name
        version = pa.resolved.version if pa.resolved else pa.ref.version
        rows.append((package, version, pa.model_dump(mode="json")))

    skipped_items = sorted(context.skipped.items())
    for name, reason in skipped_items[:MAX_SKIPPED_DEPENDENCY_ROWS]:
        rows.append((name, "", {"ref": {"name": name, "version": ""}, "skip_reason": reason}))

    overflow = len(skipped_items) - MAX_SKIPPED_DEPENDENCY_ROWS
    if overflow > 0:
        summary_name = f"+{overflow} more skipped"
        rows.append(
            (
                summary_name,
                "",
                {
                    "ref": {"name": summary_name, "version": ""},
                    "skip_reason": (
                        f"{overflow} additional declared dependencies were skipped "
                        "and are not shown individually"
                    ),
                    # Lets display-order sorting (backend.export._common,
                    # the frontend heatmap) push this row last instead of
                    # alphabetically first — "+" sorts before any letter.
                    "skip_summary": True,
                },
            )
        )
    return rows
