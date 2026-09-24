"""npm-tarball vs GitHub source drift comparison.

Classifies every file present only in the npm tarball into one of four
explained buckets (matched by path, explained by a source map, explained by
a declared build step, or a bundled third-party dependency) or leaves it
`unexplained`. The only thing this module treats as a *signal* worth acting
on is an `unexplained` file that carries a capability category absent from
the GitHub scan entirely — everything else is informational, per the
Session 0 sizing spike (most unmatched files are ordinary build output).
"""

import json
import re
from pathlib import Path

from backend.deps.paths import content_root as _fetched_content_root
from backend.models.dependencies import CapabilityProfile, DriftReport
from backend.models.enums import CapabilityCategory, PathClass


_IGNORED_DIRS = frozenset({"node_modules", ".git"})
_TS_SOURCE_EXTENSIONS = (".ts", ".tsx", ".mts")
_JS_COMPILED_EXTENSIONS = (".js", ".mjs", ".cjs")
_INLINE_SOURCEMAP_URL_RE = re.compile(rb"//[#@]\s*sourceMappingURL=([^\s]+)\s*$")


def _wrapper_prefix(root: Path, content_root: Path) -> str:
    if content_root == root:
        return ""
    return content_root.relative_to(root).as_posix() + "/"


def _strip_wrapper(rel_path: str, wrapper: str) -> str:
    return rel_path[len(wrapper) :] if wrapper and rel_path.startswith(wrapper) else rel_path


def _list_relative_files(content_root: Path) -> set[str]:
    files = set()
    for path in content_root.rglob("*"):
        if not path.is_file():
            continue
        if _IGNORED_DIRS & set(path.relative_to(content_root).parts[:-1]):
            continue
        files.add(path.relative_to(content_root).as_posix())
    return files


def _load_package_json(content_root: Path) -> dict:
    pkg_path = content_root / "package.json"
    if not pkg_path.is_file():
        return {}
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _top_dir(value: str) -> str | None:
    """The first path segment of a package.json path-shaped value, tolerating
    a leading "./" (very common: "main": "./dist/index.js"). A bare filename
    with no slash (e.g. a "files" entry naming a single file, or a directory
    name given directly) is returned as-is — harmless if it never matches a
    real top-level directory, and exactly what "files": ["dist"] needs."""
    v = value.strip()
    if v.startswith("./"):
        v = v[2:]
    return v.split("/", 1)[0] if v else None


def _iter_export_strings(value: object) -> list[str]:
    """Flatten every string leaf out of a package.json "exports" value —
    which can be a bare string, or arbitrarily nested condition maps/arrays
    (`{".": {"import": "./dist/index.mjs", "require": "./dist/index.cjs"}}`)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _iter_export_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _iter_export_strings(v)]
    return []


def _declared_build_dirs(package_json: dict) -> set[str]:
    """Top-level directory actually named by main/module/types/typings/files/
    exports — never a blanket conventional-name list (a package that keeps
    source in lib/ while running an unrelated "build" script, e.g. bundling
    its docs, would otherwise have an injected lib/evil.js explained away).
    Only meaningful alongside a declared build script (checked by the caller)."""
    dirs: set[str] = set()
    for field in ("main", "module", "types", "typings"):
        value = package_json.get(field)
        if isinstance(value, str):
            top = _top_dir(value)
            if top:
                dirs.add(top)

    files = package_json.get("files")
    if isinstance(files, list):
        for entry in files:
            if isinstance(entry, str):
                top = _top_dir(entry)
                if top:
                    dirs.add(top)

    for value in _iter_export_strings(package_json.get("exports")):
        top = _top_dir(value)
        if top:
            dirs.add(top)

    return dirs


_BUILD_SCRIPT_NAMES = ("build", "prepare", "prepublishOnly", "compile")


def _has_build_script(package_json: dict) -> bool:
    scripts = package_json.get("scripts")
    if not isinstance(scripts, dict):
        return False
    return any(scripts.get(name) for name in _BUILD_SCRIPT_NAMES)


def _resolve_sourcemap_sources(map_path: Path) -> list[str]:
    """Return the sourcemap's `sources` entries, resolved relative to the map's
    own directory. Empty on any parse failure — never raises."""
    try:
        data = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    sources = data.get("sources")
    if not isinstance(sources, list):
        return []

    source_root = data.get("sourceRoot") or ""
    resolved = []
    for src in sources:
        if not isinstance(src, str):
            continue
        combined = f"{source_root}/{src}" if source_root else src
        # Strip common non-filesystem prefixes emitted by bundlers. The ".."
        # segments that remain (e.g. tsc's usual outDir dist/ / rootDir src/
        # emitting "../src/index.ts") are resolved by the caller, which
        # already normalizes "a/b/../c" — stripping "./"/"../" here would
        # destroy that information before the caller ever sees it.
        combined = re.sub(r"^webpack://[^/]*/", "", combined)
        resolved.append(combined)
    return resolved


def _find_map_path(rel_path: str, root: Path) -> Path | None:
    """Locate `rel_path`'s source map: an adjacent `<file>.map` sibling (the
    standard convention), or an inline `//# sourceMappingURL=...` comment
    pointing at a relative file (a `data:` URI has no separate file to
    resolve). Never returns a path outside `root`."""
    sibling = root / f"{rel_path}.map"
    if sibling.is_file():
        return sibling

    try:
        tail = (root / rel_path).read_bytes()[-2000:]
    except OSError:
        return None
    m = _INLINE_SOURCEMAP_URL_RE.search(tail)
    if not m:
        return None
    url = m.group(1).decode("utf-8", errors="replace")
    if url.startswith("data:"):
        return None

    file_dir = "/".join(rel_path.split("/")[:-1])
    candidate = (root / file_dir / url) if file_dir else (root / url)
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return candidate if candidate.is_file() else None


def _classify_sourcemap(rel_path: str, content_root: Path, github_files: set[str]) -> str | None:
    """Return "sourcemap" | "bundled" | None by inspecting `rel_path`'s source map
    (an adjacent `.map` file, or an inline `sourceMappingURL` comment)."""
    map_path = _find_map_path(rel_path, content_root)
    if map_path is None:
        return None

    sources = _resolve_sourcemap_sources(map_path)
    if not sources:
        return None

    if any("node_modules/" in s for s in sources):
        return "bundled"

    # Sources are resolved relative to the map file's own directory, which
    # isn't always rel_path's directory (an inline sourceMappingURL can point
    # at a map in a different subdirectory).
    map_rel = map_path.relative_to(content_root).as_posix()
    map_dir = "/".join(map_rel.split("/")[:-1])
    for src in sources:
        candidate = f"{map_dir}/{src}".lstrip("/") if map_dir else src
        # Collapse "a/b/../c" style segments produced by relative sourcemap sources.
        parts: list[str] = []
        for part in candidate.split("/"):
            if part == "..":
                if parts:
                    parts.pop()
            elif part and part != ".":
                parts.append(part)
        normalized = "/".join(parts)
        if normalized in github_files:
            return "sourcemap"
    return None


def _classify_build_output(
    rel_path: str, build_dirs: set[str], has_build_script: bool, github_files: set[str]
) -> bool:
    # Only a file *inside* a declared build directory can be explained this
    # way. Without the "/" check, a root-level file whose bare name happens
    # to equal a declared "files"/"main" entry (e.g. "main": "evil.js", or
    # "files": ["index.js", "evil.js"]) would be waved through — exactly the
    # event-stream shape this check exists to catch.
    if "/" in rel_path:
        top_dir = rel_path.split("/", 1)[0]
        if has_build_script and top_dir in build_dirs:
            return True
    if rel_path.endswith(".d.ts"):
        return True
    for js_ext in _JS_COMPILED_EXTENSIONS:
        if rel_path.endswith(js_ext):
            stem = rel_path[: -len(js_ext)]
            if any(f"{stem}{ts_ext}" in github_files for ts_ext in _TS_SOURCE_EXTENSIONS):
                return True
    return False


def _evidence_categories_by_file(
    profile: CapabilityProfile, wrapper: str
) -> dict[str, set[CapabilityCategory]]:
    by_file: dict[str, set[CapabilityCategory]] = {}
    for evidence in profile.evidence:
        if evidence.path_class != PathClass.SHIPPED:
            continue
        canonical = _strip_wrapper(evidence.file.replace("\\", "/"), wrapper)
        by_file.setdefault(canonical, set()).add(evidence.category)
    return by_file


def compare_sources(
    name: str,
    version: str,
    tarball_dir: Path,
    tarball_profile: CapabilityProfile,
    github_dir: Path | None,
    github_profile: CapabilityProfile | None,
) -> DriftReport:
    """Compare `tarball_dir`'s source against `github_dir`'s.

    Returns `status="skipped_github_unavailable"` (all classification lists
    empty, `signal=False`) when GitHub source wasn't fetched/scanned, and
    `status="skipped_scan_incomplete"` when either scan didn't finish cleanly
    (status != "ok") — an incomplete scan's empty/partial category set would
    otherwise make every unexplained file look like a drift signal, or hide
    a signal that's actually there.
    """
    if github_dir is None or github_profile is None:
        return DriftReport(name=name, version=version, status="skipped_github_unavailable")
    if tarball_profile.status != "ok" or github_profile.status != "ok":
        return DriftReport(name=name, version=version, status="skipped_scan_incomplete")

    tarball_content_root = _fetched_content_root(tarball_dir)
    tarball_wrapper = _wrapper_prefix(tarball_dir, tarball_content_root)
    github_content_root = _fetched_content_root(github_dir)

    tarball_files = _list_relative_files(tarball_content_root)
    github_files = _list_relative_files(github_content_root)

    # Declared build *directories* come from the tarball's package.json —
    # that's what determines which files actually ship. Whether a build
    # *script* exists is checked against the GitHub repo's package.json
    # instead: the attacker controls the published tarball's package.json,
    # so "the repo has a build script" (the plan's own wording) has to mean
    # the repo, not the tarball, or an attacker could add a build/prepare
    # script to their malicious package.json and have it self-certify.
    tarball_package_json = _load_package_json(tarball_content_root)
    github_package_json = _load_package_json(github_content_root)
    build_dirs = _declared_build_dirs(tarball_package_json)
    has_build_script = _has_build_script(github_package_json)

    matched: list[str] = []
    explained_by_sourcemap: list[str] = []
    explained_by_build: list[str] = []
    bundled_dependency: list[str] = []
    unexplained: list[str] = []

    for rel_path in sorted(tarball_files):
        # Source maps are metadata *about* a shipped file, not shipped code in
        # their own right — they're consulted (via _classify_sourcemap) to
        # explain their sibling, not classified separately.
        if rel_path.endswith(".map"):
            continue
        if rel_path in github_files:
            matched.append(rel_path)
            continue

        sourcemap_verdict = _classify_sourcemap(rel_path, tarball_content_root, github_files)
        if sourcemap_verdict == "sourcemap":
            explained_by_sourcemap.append(rel_path)
            continue
        if sourcemap_verdict == "bundled":
            bundled_dependency.append(rel_path)
            continue
        if _classify_build_output(rel_path, build_dirs, has_build_script, github_files):
            explained_by_build.append(rel_path)
            continue
        unexplained.append(rel_path)

    tarball_evidence_by_file = _evidence_categories_by_file(tarball_profile, tarball_wrapper)
    github_categories = github_profile.category_set()
    unexplained_categories: set[CapabilityCategory] = set()
    for rel_path in unexplained:
        unexplained_categories |= tarball_evidence_by_file.get(rel_path, set()) - github_categories

    return DriftReport(
        name=name,
        version=version,
        status="compared",
        matched=matched,
        explained_by_sourcemap=explained_by_sourcemap,
        explained_by_build=explained_by_build,
        bundled_dependency=bundled_dependency,
        unexplained=unexplained,
        signal=bool(unexplained_categories),
        unexplained_categories=sorted(unexplained_categories, key=lambda c: c.value),
    )
