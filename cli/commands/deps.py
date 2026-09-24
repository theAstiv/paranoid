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

from backend.deps.delta import compute_delta
from backend.deps.drift import compare_sources
from backend.deps.fetcher import FetchError, fetch_source
from backend.deps.resolver import (
    fetch_registry_doc,
    previous_version,
    resolve_github_ref,
    resolve_npm,
)
from backend.deps.scanner import resolve_semgrep_binary, scan_source
from backend.models.dependencies import (
    CapabilityProfile,
    DriftReport,
    ResolvedPackage,
    VersionDelta,
)
from backend.models.enums import SourceKind


logger = logging.getLogger(__name__)

_SPEC_RE = re.compile(r"^(?P<name>@[^/@]+/[^/@]+|[^/@]+)@(?P<version>.+)$")
_MANIFEST_CONCURRENCY = 4


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


async def _resolve_one(
    name: str, version: str, want_github: bool, client: httpx.AsyncClient
) -> ResolvedPackage:
    resolved = await resolve_npm(name, version, client)
    if want_github:
        resolved = await resolve_github_ref(resolved, client)
    return resolved


async def _fetch_and_scan(
    resolved: ResolvedPackage, kind: SourceKind, client: httpx.AsyncClient
) -> tuple[Path | None, CapabilityProfile | None]:
    """Fetch + scan one source.

    For GitHub only, a hostile/corrupt tarball degrades this source to
    "unavailable" rather than raising — the same outcome as GitHub not
    resolving — so a real repo tripping the safety net on one file (e.g. a
    legitimate symlink) never discards results already obtained from the npm
    side in `_scan_one`. The npm tarball is the primary, integrity-checked
    source: a hostile/tampered *npm* tarball (integrity mismatch, path
    traversal, symlink member) is exactly the kind of finding this command
    exists to surface, so it still raises — silently reporting it as
    "(not scanned)" would hide a flagged dependency behind an ordinary miss.
    """
    if kind == SourceKind.GITHUB:
        try:
            path = await fetch_source(resolved, kind, client)
        except FetchError as e:
            logger.warning(
                "GitHub fetch rejected for %s@%s: %s — treating GitHub source as unavailable",
                resolved.name,
                resolved.version,
                e,
            )
            return None, None
    else:
        path = await fetch_source(resolved, kind, client)
    if path is None:
        return None, None
    profile = await scan_source(path, kind, name=resolved.name, version=resolved.version)
    return path, profile


async def _scan_one(
    name: str, version: str, source: str, client: httpx.AsyncClient
) -> tuple[ResolvedPackage, CapabilityProfile | None, CapabilityProfile | None, DriftReport | None]:
    """Resolve + fetch + scan one `name@version` for the requested source(s).

    Returns (resolved, npm_profile, github_profile, drift) — `drift` is only
    computed when both sources were requested (`source == "both"`); it is
    None (not attempted) rather than a status otherwise.
    """
    want_npm = source in ("npm", "both")
    want_github = source in ("github", "both")

    resolved = await _resolve_one(name, version, want_github, client)

    tarball_path = tarball_profile = None
    if want_npm:
        tarball_path, tarball_profile = await _fetch_and_scan(
            resolved, SourceKind.NPM_TARBALL, client
        )

    github_path = github_profile = None
    if want_github:
        github_path, github_profile = await _fetch_and_scan(resolved, SourceKind.GITHUB, client)

    drift = None
    if want_npm and want_github:
        if tarball_path is None or tarball_profile is None:
            # compare_sources requires a resolved tarball dir/profile — this is
            # the npm side failing to fetch, not GitHub, so it gets its own label.
            drift = DriftReport(name=name, version=version, status="skipped_npm_unavailable")
        else:
            drift = compare_sources(
                name, version, tarball_path, tarball_profile, github_path, github_profile
            )

    return resolved, tarball_profile, github_profile, drift


def _profile_dict(profile: CapabilityProfile | None) -> dict | None:
    return profile.model_dump(mode="json") if profile is not None else None


def _render_capability_grid(label: str, profile: CapabilityProfile | None) -> None:
    click.secho(f"  {label}:", fg="cyan", bold=True)
    if profile is None:
        click.echo("    (not scanned)")
        return
    if profile.status != "ok":
        click.secho(f"    status: {profile.status}", fg="yellow")
        return
    categories = profile.category_set()
    if not categories:
        click.echo("    (no capabilities detected)")
    else:
        for category in sorted(categories, key=lambda c: c.value):
            count = sum(1 for e in profile.evidence if e.category == category)
            click.echo(f"    {category.value:<16} {count} finding(s)")
    if profile.install_hooks:
        click.secho("    install hooks:", fg="yellow")
        for hook in profile.install_hooks:
            click.echo(f"      - {hook}")


def _render_drift(drift: DriftReport | None) -> None:
    if drift is None:
        return
    click.secho("  Drift (npm tarball vs GitHub source):", fg="cyan", bold=True)
    if drift.status == "skipped_github_unavailable":
        click.echo("    GitHub source unavailable — drift skipped.")
        return
    if drift.status == "skipped_npm_unavailable":
        click.echo("    npm tarball unavailable — drift skipped.")
        return
    if drift.status == "skipped_scan_incomplete":
        click.echo("    One or both scans did not finish cleanly — drift skipped.")
        return
    click.echo(
        f"    matched={len(drift.matched)} sourcemap={len(drift.explained_by_sourcemap)} "
        f"build={len(drift.explained_by_build)} bundled={len(drift.bundled_dependency)} "
        f"unexplained={len(drift.unexplained)}"
    )
    if drift.signal:
        click.secho(
            f"    SIGNAL: capabilities only in tarball: "
            f"{', '.join(c.value for c in drift.unexplained_categories)}",
            fg="red",
            bold=True,
        )
    else:
        click.echo("    no drift signal")


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
            return await _scan_one(name, version, source.lower(), client)

    try:
        resolved, npm_profile, github_profile, drift = asyncio.run(_run())
    except (httpx.HTTPError, FetchError, ValueError) as e:
        raise DepsCLIError(f"{type(e).__name__}: {e}")

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
            _, prev_tarball_profile = await _fetch_and_scan(
                prev_resolved, SourceKind.NPM_TARBALL, client
            )

            curr_resolved, curr_npm_profile, curr_github_profile, curr_drift = await _scan_one(
                name, v2, "both" if want_github_for_current else "npm", client
            )
            return (
                prev_resolved,
                prev_tarball_profile,
                curr_resolved,
                curr_npm_profile,
                curr_github_profile,
                curr_drift,
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
    if prev_profile.status != "ok" or curr_npm_profile.status != "ok":
        # An incomplete scan's empty/partial category set would otherwise make
        # every capability on the other side look "added" or "removed" —
        # refuse to diff rather than report a delta that isn't real.
        raise DepsCLIError(
            f"Scan did not finish cleanly for {name} "
            f"(previous: {prev_profile.status}, current: {curr_npm_profile.status}) — refusing to diff."
        )

    delta = compute_delta(prev_resolved, curr_resolved, prev_profile, curr_npm_profile)

    result = {
        "delta": delta.model_dump(mode="json"),
        "current_github_profile": _profile_dict(curr_github_profile),
        "drift": curr_drift.model_dump(mode="json") if curr_drift is not None else None,
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
    _render_delta(delta)
    _render_drift(curr_drift)
    click.echo()

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        click.echo(f"Wrote {output}")


def _parse_lockfile_versions(lock_path: Path) -> dict[str, str]:
    """Extract {name: pinned_version} from a v1, v2, or v3 package-lock.json."""
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}

    versions: dict[str, str] = {}
    packages = data.get("packages")
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

    dependencies = data.get("dependencies")
    if isinstance(dependencies, dict):
        # v1
        for dep_name, info in dependencies.items():
            if isinstance(info, dict) and isinstance(info.get("version"), str):
                versions[dep_name] = info["version"]
    return versions


_EXACT_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def _pin_from_range(range_str: str) -> str | None:
    """Best-effort literal version from a semver range, when there's no lockfile.

    Only strips a leading ^ or ~ — anything else (a range with a space, an
    'x'/'*' wildcard, a git/file/url spec, an OR range) is not a single
    pinnable version, so it's left for the caller to skip.
    """
    stripped = range_str.strip().lstrip("^~")
    return stripped if _EXACT_VERSION_RE.match(stripped) else None


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

    direct: dict[str, str] = {}
    for section in ("dependencies", "devDependencies"):
        entries = manifest_data.get(section)
        if isinstance(entries, dict):
            direct.update({k: v for k, v in entries.items() if isinstance(v, str)})

    if not direct:
        raise DepsCLIError(f"No dependencies found in {manifest}")

    lockfile_versions = _parse_lockfile_versions(manifest.parent / "package-lock.json")

    targets: dict[str, str] = {}
    skipped: list[str] = []
    for pkg_name, range_str in direct.items():
        pinned = lockfile_versions.get(pkg_name) or _pin_from_range(range_str)
        if pinned is None:
            skipped.append(pkg_name)
        else:
            targets[pkg_name] = pinned

    _warn_if_semgrep_missing()

    async def _run():
        semaphore = asyncio.Semaphore(_MANIFEST_CONCURRENCY)
        results: dict[str, dict] = {}

        async def _one(pkg_name: str, pkg_version: str, client: httpx.AsyncClient) -> None:
            async with semaphore:
                try:
                    resolved, npm_profile, github_profile, drift = await _scan_one(
                        pkg_name, pkg_version, source.lower(), client
                    )
                    results[pkg_name] = {
                        "version": resolved.version,
                        "npm": _profile_dict(npm_profile),
                        "github": _profile_dict(github_profile),
                        "drift": drift.model_dump(mode="json") if drift is not None else None,
                        "error": None,
                    }
                except Exception as e:
                    # One dependency's failure (network, a hostile tarball, a
                    # filesystem error moving the cache, ...) must never abort
                    # the whole manifest sweep.
                    results[pkg_name] = {"error": f"{type(e).__name__}: {e}"}

        async with httpx.AsyncClient() as client:
            await asyncio.gather(*(_one(n, v, client) for n, v in targets.items()))
        return results

    results = asyncio.run(_run())

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
