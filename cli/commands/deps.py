"""Deps command - dependency capability scanning, version diffing, and manifest sweeps.

Wraps backend.deps (resolver/fetcher/scanner/delta/drift) as `paranoid deps scan`,
`paranoid deps diff`, and `paranoid deps scan-manifest`. All package source is
fetched read-only (backend.deps.fetcher never executes package code); this
command only ever runs Semgrep against it.
"""

import asyncio
import json
import logging
import re
from pathlib import Path

import click
import httpx

from backend.deps import analyze
from backend.deps.delta import compute_delta
from backend.deps.fetcher import FetchError
from backend.deps.resolver import fetch_registry_doc, previous_version, resolve_npm
from backend.deps.scanner import resolve_semgrep_binary
from backend.models.dependencies import (
    CapabilityProfile,
    DriftReport,
    VersionDelta,
)
from backend.models.enums import CapabilityCategory, SourceKind


logger = logging.getLogger(__name__)

_SPEC_RE = re.compile(r"^(?P<name>@[^/@]+/[^/@]+|[^/@]+)@(?P<version>.+)$")
# A package that crosses backend.deps.scanner._MAX_EXTRA_TARGETS_TOTAL could
# have thousands of unscanned file names to list; the console output stays
# readable by showing only the first few, with a count for the rest. JSON
# output (below) is never truncated.
_MAX_LISTED_UNSCANNED_FILES = 20
# Only a `semgrep_*` status means the scan itself didn't finish. A
# "partial_fetch" profile (some files couldn't be extracted, e.g. Windows
# path-length limits) still ran a real scan against what it did get.
_SCANNABLE_STATUSES = ("ok", "partial_fetch")


class DepsCLIError(click.ClickException):
    """A dependency-engine error surfaced as a clean CLI message (exit code 1)."""

    exit_code = 1


def parse_package_spec(spec: str) -> tuple[str, str]:
    """Parse `name@version` (scoped or unscoped) into (name, version).

    Raises ValueError on anything else — including a bare package name with
    no version, which this command always requires explicitly.
    """
    m = _SPEC_RE.match(spec)
    if not m:
        raise ValueError(
            f"Invalid package spec {spec!r} — expected NAME@VERSION (e.g. 'chalk@5.3.0' "
            f"or '@babel/core@7.24.0')"
        )
    return m.group("name"), m.group("version")


def _profile_dict(profile: CapabilityProfile | None) -> dict | None:
    return profile.model_dump(mode="json") if profile is not None else None


def _echo_file_list(files: list[str], *, indent: str = "      - ") -> None:
    """Print `files`, one per line, truncated to `_MAX_LISTED_UNSCANNED_FILES`
    with a summary count for the rest — a package that crosses the scan's
    target cap could otherwise dump thousands of lines to the console. JSON
    output (built separately from the untruncated model) is unaffected."""
    for name in files[:_MAX_LISTED_UNSCANNED_FILES]:
        click.echo(f"{indent}{name}")
    remaining = len(files) - _MAX_LISTED_UNSCANNED_FILES
    if remaining > 0:
        click.echo(f"{indent}...and {remaining} more")


def _render_capability_grid(label: str, profile: CapabilityProfile | None) -> None:
    click.secho(f"  {label}:", fg="cyan", bold=True)
    if profile is None:
        click.echo("    (not scanned)")
        return
    if profile.status not in ("ok", "partial_fetch"):
        click.secho(f"    status: {profile.status}", fg="yellow")
        return
    if profile.status == "partial_fetch":
        click.secho(
            f"    partial: {profile.skipped_long_paths} file(s) skipped "
            "(path exceeds Windows path-length limits)",
            fg="yellow",
        )
    if profile.discovered_directory is not None:
        click.secho(
            f"    GitHub package found at {profile.discovered_directory or '(repo root)'}/",
            fg="yellow",
        )
    if profile.external_build_markers:
        click.secho(
            f"    repo build markers: {', '.join(profile.external_build_markers)}",
            fg="yellow",
        )
    categories = profile.category_set()
    if not categories:
        click.echo("    (no capabilities detected)")
    else:
        for category in sorted(categories, key=lambda c: c.value):
            count = sum(e.count for e in profile.evidence if e.category == category)
            # BUILD_INSTALL can come purely from a flagged install hook, with
            # no matching Semgrep evidence at all (see category_set()).
            if count == 0 and category == CapabilityCategory.BUILD_INSTALL:
                count = len(profile.install_hooks)
            click.echo(f"    {category.value:<16} {count} finding(s)")
    if profile.install_hooks:
        click.secho("    install hooks:", fg="yellow")
        for hook in profile.install_hooks:
            click.echo(f"      - {hook}")
    reclassified = {
        e.file: (e.reclassified_from, e.reclassified_via)
        for e in profile.evidence
        if e.reclassified_from is not None
    }
    if reclassified:
        click.secho("    reclassified as shipped:", fg="yellow")
        for file, (was, via) in sorted(reclassified.items()):
            click.echo(f"      - {file} (was {was.value}, loaded from {via})")
    if profile.skipped_link_names:
        click.secho("    skipped symlinks/hardlinks:", fg="yellow")
        for name in profile.skipped_link_names:
            click.echo(f"      - {name}")
    if profile.skipped_long_path_names:
        click.secho("    skipped (path too long):", fg="yellow")
        for name in profile.skipped_long_path_names:
            click.echo(f"      - {name}")
    if profile.unscanned_reachable_files:
        click.secho("    unscanned (exceeded scan target cap):", fg="red", bold=True)
        _echo_file_list(profile.unscanned_reachable_files)


def _render_drift(drift: DriftReport | None) -> None:
    if drift is None:
        return
    click.secho("  Drift (npm tarball vs GitHub source):", fg="cyan", bold=True)
    if drift.status == "skipped_github_unavailable":
        suffix = f" ({drift.skip_reason})" if drift.skip_reason else ""
        click.echo(f"    GitHub source unavailable{suffix} — drift skipped.")
        return
    if drift.status == "skipped_npm_unavailable":
        suffix = f" ({drift.skip_reason})" if drift.skip_reason else ""
        click.echo(f"    npm tarball unavailable{suffix} — drift skipped.")
        return
    if drift.status == "skipped_scan_incomplete":
        suffix = f" ({drift.skip_reason})" if drift.skip_reason else ""
        click.echo(f"    One or both scans did not finish cleanly{suffix} — drift skipped.")
        return
    click.echo(
        f"    matched={len(drift.matched)} sourcemap={len(drift.explained_by_sourcemap)} "
        f"build={len(drift.explained_by_build)} bundled={len(drift.bundled_dependency)} "
        f"unexplained={len(drift.unexplained)} unverifiable={len(drift.unverifiable)} "
        f"generated_unverifiable={len(drift.generated_unverifiable)}"
    )
    if drift.signal:
        if drift.tarball_declared_name_mismatch is not None:
            declared = (
                f"{drift.tarball_declared_name_mismatch!r}"
                if drift.tarball_declared_name_mismatch
                else "(no name declared)"
            )
            click.secho(
                f"    SIGNAL: tarball package.json declares name {declared}, "
                f"published as {drift.name!r}",
                fg="red",
                bold=True,
            )
        if drift.unscanned_reachable_files:
            click.secho(
                f"    SIGNAL: {len(drift.unscanned_reachable_files)} reachable file(s) "
                "exceeded the scan's target cap and were never checked:",
                fg="red",
                bold=True,
            )
            _echo_file_list(drift.unscanned_reachable_files)
        if drift.signal_categories:
            click.secho(
                f"    SIGNAL: capabilities only in tarball: "
                f"{', '.join(c.value for c in drift.signal_categories)}",
                fg="red",
                bold=True,
            )
        for file, categories in sorted(drift.signal_files.items()):
            click.echo(f"      - {file}: {', '.join(c.value for c in categories)}")
        if drift.install_hooks_added:
            click.echo(f"      - install hooks added: {', '.join(drift.install_hooks_added)}")
    else:
        click.echo("    no drift signal")
    if drift.relocated:
        click.secho("    informational: capability relocated within the repo:", fg="yellow")
        for entry in drift.relocated:
            click.echo(f"      - {entry['file']}: {', '.join(entry['categories'])}")
    if drift.new_evidence_in_matched:
        click.secho("    informational: new evidence on matched files:", fg="yellow")
        for file, items in sorted(drift.new_evidence_in_matched.items()):
            for item in items:
                click.echo(f"      - {file} [{item['category']}] {item['rule_id']}")
    if drift.install_hooks_added_benign:
        click.secho(
            "    informational: install hooks added (allowlisted commands only): ", fg="yellow"
        )
        click.echo(f"      - {', '.join(drift.install_hooks_added_benign)}")
    if drift.generated_unverifiable:
        click.secho(
            "    informational: shipped code generated outside npm; "
            "cannot be verified against source:",
            fg="yellow",
        )
        for file in drift.generated_unverifiable[:_MAX_LISTED_UNSCANNED_FILES]:
            categories = drift.generated_unverifiable_categories.get(file)
            suffix = f": {', '.join(c.value for c in categories)}" if categories else ""
            click.echo(f"      - {file}{suffix}")
        remaining = len(drift.generated_unverifiable) - _MAX_LISTED_UNSCANNED_FILES
        if remaining > 0:
            click.echo(f"      ...and {remaining} more")


def _render_delta(delta: VersionDelta) -> None:
    click.secho(
        f"  Delta {delta.previous_version} -> {delta.current_version} ({delta.semver_jump}):",
        fg="cyan",
        bold=True,
    )
    if delta.categories_added:
        click.secho(
            f"    + added:   {', '.join(c.value for c in delta.categories_added)}", fg="red"
        )
    if delta.categories_removed:
        click.echo(f"    - removed: {', '.join(c.value for c in delta.categories_removed)}")
    if not delta.categories_added and not delta.categories_removed:
        click.echo("    (no capability change)")
    if delta.publisher_changed:
        click.secho(
            f"    publisher changed: {delta.previous_publisher} -> {delta.current_publisher}",
            fg="yellow",
        )
    if delta.install_hooks_added:
        click.secho("    install hooks added:", fg="yellow")
        for hook in delta.install_hooks_added:
            click.echo(f"      - {hook}")
    if delta.flags:
        click.secho(f"    FLAGS: {', '.join(delta.flags)}", fg="red", bold=True)


def _warn_if_semgrep_missing() -> None:
    if resolve_semgrep_binary() is None:
        click.secho(
            "Warning: Semgrep not found (set SEMGREP_BINARY or install semgrep on PATH). "
            "Capability results will be empty.",
            fg="yellow",
            err=True,
        )


@click.group()
def deps() -> None:
    """Dependency capability scanning — what can this package actually do?

    Fetches real npm/GitHub source (never executes it) and runs Semgrep to
    detect network, filesystem, process, and other capabilities. Diffs two
    versions to catch the supply-chain pattern of a small release quietly
    adding a risky capability.

    \b
    Examples:
      paranoid deps scan chalk@5.3.0
      paranoid deps diff ua-parser-js 0.7.28 0.7.30 --source both
      paranoid deps scan-manifest package.json
    """


@deps.command("scan")
@click.argument("spec")
@click.option(
    "--source",
    type=click.Choice(["github", "npm", "both"], case_sensitive=False),
    default="both",
    help="Which source(s) to fetch and scan (default: both).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["console", "json"], case_sensitive=False),
    default="console",
    help="Output format (default: console).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Write JSON output to this file (in addition to console output, unless --format json).",
)
def scan(spec: str, source: str, output_format: str, output: Path | None) -> None:
    """Scan one package: SPEC is NAME@VERSION (e.g. 'chalk@5.3.0')."""
    try:
        name, version = parse_package_spec(spec)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="'SPEC'")

    _warn_if_semgrep_missing()

    async def _run():
        async with httpx.AsyncClient() as client:
            return await analyze.analyze_package(name, version, source.lower(), client)

    try:
        analysis = asyncio.run(_run())
    except (httpx.HTTPError, FetchError, ValueError) as e:
        raise DepsCLIError(f"{type(e).__name__}: {e}")

    resolved, npm_profile, github_profile, drift = (
        analysis.resolved,
        analysis.npm_profile,
        analysis.github_profile,
        analysis.drift,
    )

    result = {
        "name": resolved.name,
        "version": resolved.version,
        "github_status": resolved.github_status,
        "npm": _profile_dict(npm_profile),
        "github": _profile_dict(github_profile),
        "drift": drift.model_dump(mode="json") if drift is not None else None,
    }

    if output_format.lower() == "json":
        text = json.dumps(result, indent=2)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text, encoding="utf-8")
            click.echo(f"Wrote {output}")
        else:
            click.echo(text)
        return

    click.echo()
    click.secho(f"{resolved.name}@{resolved.version}", fg="green", bold=True)
    click.echo(
        f"  GitHub status: {resolved.github_status}"
        + (f" ({resolved.github_ref})" if resolved.github_ref else "")
    )
    if npm_profile is not None or source.lower() in ("npm", "both"):
        _render_capability_grid("npm tarball", npm_profile)
    if github_profile is not None or source.lower() in ("github", "both"):
        _render_capability_grid("GitHub source", github_profile)
    _render_drift(drift)
    click.echo()

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        click.echo(f"Wrote {output}")


@deps.command("diff")
@click.argument("name")
@click.argument("versions", nargs=-1, required=True)
@click.option(
    "--source",
    type=click.Choice(["github", "npm", "both"], case_sensitive=False),
    default="npm",
    help=(
        "Which source(s) to additionally fetch for the CURRENT version's drift "
        "comparison (default: npm-only, no drift). The capability delta itself "
        "always uses the npm tarball for both versions."
    ),
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["console", "json"], case_sensitive=False),
    default="console",
    help="Output format (default: console).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Write JSON output to this file.",
)
def diff(
    name: str, versions: tuple[str, ...], source: str, output_format: str, output: Path | None
) -> None:
    """Diff a package's capabilities between two versions.

    \b
    NAME VERSIONS: either
      paranoid deps diff <name> <v1> <v2>
      paranoid deps diff <name> <v2>          (v1 defaults to the previous published version)
    """
    if len(versions) == 1:
        v1, v2 = None, versions[0]
    elif len(versions) == 2:
        v1, v2 = versions
    else:
        raise click.BadParameter(
            "Expected one or two version arguments (v2, or v1 v2).", param_hint="'VERSIONS'"
        )

    _warn_if_semgrep_missing()
    want_github_for_current = source.lower() in ("github", "both")

    async def _run():
        async with httpx.AsyncClient() as client:
            prev_version = v1
            if prev_version is None:
                doc = await fetch_registry_doc(name, client)
                prev_version = previous_version(doc, v2)
                if prev_version is None:
                    raise ValueError(f"No published version before {v2} found for {name}")

            prev_resolved = await resolve_npm(name, prev_version, client)
            _, prev_tarball_profile, _ = await analyze.fetch_and_scan_one(
                prev_resolved, SourceKind.NPM_TARBALL, client
            )

            curr_analysis = await analyze.analyze_package(
                name, v2, "both" if want_github_for_current else "npm", client
            )
            return (
                prev_resolved,
                prev_tarball_profile,
                curr_analysis.resolved,
                curr_analysis.npm_profile,
                curr_analysis.github_profile,
                curr_analysis.drift,
            )

    try:
        (
            prev_resolved,
            prev_profile,
            curr_resolved,
            curr_npm_profile,
            curr_github_profile,
            curr_drift,
        ) = asyncio.run(_run())
    except (httpx.HTTPError, FetchError, ValueError) as e:
        raise DepsCLIError(f"{type(e).__name__}: {e}")

    if prev_profile is None or curr_npm_profile is None:
        raise DepsCLIError(
            f"Could not fetch npm tarball source for {name} "
            f"{prev_resolved.version} / {curr_resolved.version}"
        )
    if (
        prev_profile.status not in _SCANNABLE_STATUSES
        or curr_npm_profile.status not in _SCANNABLE_STATUSES
    ):
        # An incomplete *scan* (semgrep_*) means an empty/partial category set
        # that would otherwise make every capability on the other side look
        # "added" or "removed" — refuse to diff. A partial_fetch (some files
        # simply couldn't be extracted, e.g. Windows path limits) still ran a
        # real scan, so it's allowed through, just noted below.
        raise DepsCLIError(
            f"Scan did not finish cleanly for {name} "
            f"(previous: {prev_profile.status}, current: {curr_npm_profile.status}) — refusing to diff."
        )

    delta = compute_delta(prev_resolved, curr_resolved, prev_profile, curr_npm_profile)
    partial_sides = [
        label
        for label, profile in (("previous", prev_profile), ("current", curr_npm_profile))
        if profile.status == "partial_fetch"
    ]

    result = {
        "delta": delta.model_dump(mode="json"),
        "current_github_profile": _profile_dict(curr_github_profile),
        "drift": curr_drift.model_dump(mode="json") if curr_drift is not None else None,
        "partial_sides": partial_sides,
    }

    if output_format.lower() == "json":
        text = json.dumps(result, indent=2)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text, encoding="utf-8")
            click.echo(f"Wrote {output}")
        else:
            click.echo(text)
        return

    click.echo()
    click.secho(f"{name}", fg="green", bold=True)
    if partial_sides:
        click.secho(
            f"  Warning: {', '.join(partial_sides)} version scan was partial "
            "(some files couldn't be extracted) — delta may be incomplete.",
            fg="yellow",
        )
    _render_delta(delta)
    _render_drift(curr_drift)
    click.echo()

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        click.echo(f"Wrote {output}")


@deps.command("scan-manifest")
@click.argument("manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--source",
    type=click.Choice(["github", "npm", "both"], case_sensitive=False),
    default="npm",
    help="Which source(s) to scan each dependency with (default: npm, for speed).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["console", "json"], case_sensitive=False),
    default="console",
    help="Output format (default: console).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Write JSON output to this file.",
)
def scan_manifest(manifest: Path, source: str, output_format: str, output: Path | None) -> None:
    """Scan every direct dependency in a package.json.

    Versions are taken from the adjacent package-lock.json when present
    (v1, v2, and v3 lockfile formats are all supported); otherwise a caret/tilde
    range like "^5.3.0" is pinned to its literal floor version. Anything else
    (a range with a space, an OR range, a git/file/url spec) is skipped and
    reported, since it has no single resolvable version.
    """
    try:
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise DepsCLIError(f"Could not parse {manifest}: {e}")

    if not analyze.direct_dependencies_from_manifest(manifest_data):
        raise DepsCLIError(f"No dependencies found in {manifest}")

    lockfile_path = manifest.parent / "package-lock.json"
    lockfile_data = None
    if lockfile_path.exists():
        try:
            lockfile_data = json.loads(lockfile_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            lockfile_data = None

    _warn_if_semgrep_missing()

    # No cap: `scan-manifest` has always swept every direct dependency
    # unconditionally. The 50-package default only applies to the pipeline's
    # automated ANALYZE_DEPENDENCIES step, not this explicit CLI invocation.
    context = asyncio.run(
        analyze.analyze_manifest(
            manifest_data, lockfile_data, source_mode=source.lower(), max_direct_dependencies=None
        )
    )

    results: dict[str, dict] = {}
    for pa in context.packages:
        if pa.error:
            results[pa.ref.name] = {"error": pa.error}
            continue
        results[pa.ref.name] = {
            "version": pa.resolved.version,
            "npm": _profile_dict(pa.npm_profile),
            "github": _profile_dict(pa.github_profile),
            "drift": pa.drift.model_dump(mode="json") if pa.drift is not None else None,
            "error": None,
        }
    skipped = sorted(context.skipped)

    output_data = {"scanned": results, "skipped": skipped}
    if output_format.lower() == "json":
        text = json.dumps(output_data, indent=2)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text, encoding="utf-8")
            click.echo(f"Wrote {output}")
        else:
            click.echo(text)
        return

    click.echo()
    click.secho(
        f"Scanned {len(results)} direct dependenc{'y' if len(results) == 1 else 'ies'} from {manifest}",
        fg="green",
        bold=True,
    )
    for pkg_name in sorted(results):
        entry = results[pkg_name]
        click.echo()
        if entry.get("error"):
            click.secho(f"{pkg_name}: {entry['error']}", fg="red")
            continue
        click.secho(f"{pkg_name}@{entry['version']}", fg="cyan", bold=True)
        npm_profile = CapabilityProfile.model_validate(entry["npm"]) if entry["npm"] else None
        _render_capability_grid("npm tarball", npm_profile)
        if entry["github"]:
            github_profile = CapabilityProfile.model_validate(entry["github"])
            _render_capability_grid("GitHub source", github_profile)
        if entry["drift"]:
            _render_drift(DriftReport.model_validate(entry["drift"]))
    if skipped:
        click.echo()
        click.secho(
            f"Skipped (no resolvable pinned version): {', '.join(sorted(skipped))}", fg="yellow"
        )
    click.echo()

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(output_data, indent=2), encoding="utf-8")
        click.echo(f"Wrote {output}")
