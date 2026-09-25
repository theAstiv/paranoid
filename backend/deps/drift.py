"""npm-tarball vs GitHub source drift comparison.

Classifies every tarball file into one of five buckets — matched by path,
explained by a source map, explained by a declared build step, a bundled
third-party dependency, or unexplained (further split into `unverifiable`
when the GitHub side couldn't extract the corresponding path at all).

Provenance can narrow where to look, but it never excuses a capability by
itself: every bucket's excuse is a *specific* set of categories (the
matched GitHub file's own categories, the source map's resolved sources'
categories, ...), and any tarball-file category outside that excuse set is
`novel`. A novel category absent from the GitHub scan entirely is a strong
`signal`; one merely relocated within the repo is `weak` (informational —
see `relocated`). This closes the bypasses a purely path-based/bucket-based
drift check missed: a fake source map pointing at `node_modules/` or at an
unrelated real file, a payload appended to an otherwise-matched file, and a
novel-capability file dropped into a declared build directory.
"""

import json
import posixpath
import re
from pathlib import Path

from backend.models.dependencies import CapabilityProfile, DriftReport
from backend.models.enums import CapabilityCategory, PathClass


_IGNORED_DIRS = frozenset({"node_modules", ".git"})
_TS_SOURCE_EXTENSIONS = (".ts", ".tsx", ".mts")
_JS_COMPILED_EXTENSIONS = (".js", ".mjs", ".cjs")
_INLINE_SOURCEMAP_URL_RE = re.compile(rb"//[#@]\s*sourceMappingURL=([^\s]+)\s*$")
_HOOK_KEYS = ("preinstall", "install", "postinstall", "prepare")


def _list_relative_files(root: Path) -> set[str]:
    files = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if _IGNORED_DIRS & set(path.relative_to(root).parts[:-1]):
            continue
        files.add(path.relative_to(root).as_posix())
    return files


def _load_package_json(root: Path) -> dict:
    pkg_path = root / "package.json"
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


def _hook_scripts(package_json: dict) -> dict[str, str]:
    scripts = package_json.get("scripts")
    if not isinstance(scripts, dict):
        return {}
    return {
        key: value
        for key, value in scripts.items()
        if key in _HOOK_KEYS and isinstance(value, str) and value.strip()
    }


def _declared_dependencies(package_json: dict) -> set[str]:
    deps: set[str] = set()
    for field in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        value = package_json.get(field)
        if isinstance(value, dict):
            deps.update(k for k in value if isinstance(k, str))
    return deps


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


def _collapse_dotdot(path: str) -> str:
    """Collapse "a/b/../c" style segments produced by relative sourcemap sources."""
    parts: list[str] = []
    for part in path.split("/"):
        if part == "..":
            if parts:
                parts.pop()
        elif part and part != ".":
            parts.append(part)
    return "/".join(parts)


def _bundled_package_name(normalized: str) -> str | None:
    idx = normalized.find("node_modules/")
    if idx == -1:
        return None
    tail = normalized[idx + len("node_modules/") :]
    parts = tail.split("/")
    if not parts or not parts[0]:
        return None
    if parts[0].startswith("@") and len(parts) > 1 and parts[1]:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def _classify_sourcemap(
    rel_path: str,
    tarball_dir: Path,
    github_files: set[str],
    github_evidence_by_file: dict[str, set[CapabilityCategory]],
    declared_deps: set[str],
    github_categories: set[CapabilityCategory],
) -> tuple[str, set[CapabilityCategory]] | None:
    """Classify `rel_path`'s source map as "sourcemap" or "bundled", together
    with the categories it excuses — or None if there's no map, or the map is
    invalid (every listed source must resolve to a real GitHub file or to a
    GitHub-declared dependency, or the map is ignored entirely and the file
    falls through to the next check).

    A "bundled" verdict excuses the *package-wide* GitHub category set, not
    every category unconditionally — vendored code is legitimately unscanned,
    but a devDependency (nearly every repo declares one) named in a fake map
    must not blanket-excuse a capability the package has never shown anywhere,
    or naming e.g. "typescript" in a bogus map hides an injected payload.
    """
    map_path = _find_map_path(rel_path, tarball_dir)
    if map_path is None:
        return None

    sources = _resolve_sourcemap_sources(map_path)
    if not sources:
        return None

    map_rel = map_path.relative_to(tarball_dir).as_posix()
    map_dir = "/".join(map_rel.split("/")[:-1])

    own_categories: set[CapabilityCategory] = set()
    has_vendor = False
    for src in sources:
        combined = f"{map_dir}/{src}".lstrip("/") if map_dir else src
        normalized = _collapse_dotdot(combined)
        if "node_modules/" in normalized:
            pkg = _bundled_package_name(normalized)
            if pkg is None or pkg not in declared_deps:
                return None
            has_vendor = True
            continue
        if normalized not in github_files:
            return None
        own_categories |= github_evidence_by_file.get(normalized, set())

    if has_vendor:
        # We don't scan the vendored dependency's own source, but that only
        # excuses capabilities the package's real (GitHub) source already
        # shows somewhere — not a blanket pass for anything at all.
        return "bundled", set(github_categories) | own_categories
    return "sourcemap", own_categories


def _classify_build(
    rel_path: str,
    build_dirs: set[str],
    has_build_script: bool,
    github_files: set[str],
    github_evidence_by_file: dict[str, set[CapabilityCategory]],
    github_categories: set[CapabilityCategory],
) -> set[CapabilityCategory] | None:
    """Classify `rel_path` as declared build output, together with the
    categories it excuses — or None if it isn't build output at all."""
    if rel_path.endswith(".d.ts"):
        # A type declaration carries no runtime capability of its own; excuse
        # it against the whole package rather than an empty set, so a rule
        # misfiring on declaration syntax can't manufacture a signal.
        return set(github_categories)

    for js_ext in _JS_COMPILED_EXTENSIONS:
        if rel_path.endswith(js_ext):
            stem = rel_path[: -len(js_ext)]
            for ts_ext in _TS_SOURCE_EXTENSIONS:
                pair = f"{stem}{ts_ext}"
                if pair in github_files:
                    return set(github_evidence_by_file.get(pair, set()))

    # Only a file *inside* a declared build directory can be explained this
    # way. Without the "/" check, a root-level file whose bare name happens
    # to equal a declared "files"/"main" entry (e.g. "main": "evil.js", or
    # "files": ["index.js", "evil.js"]) would be waved through — exactly the
    # event-stream shape this check exists to catch.
    if "/" in rel_path:
        top_dir = rel_path.split("/", 1)[0]
        if has_build_script and top_dir in build_dirs:
            return set(github_categories)

    return None


def _evidence_categories_by_file(profile: CapabilityProfile) -> dict[str, set[CapabilityCategory]]:
    by_file: dict[str, set[CapabilityCategory]] = {}
    for evidence in profile.evidence:
        if evidence.path_class != PathClass.SHIPPED:
            continue
        canonical = posixpath.normpath(evidence.file.replace("\\", "/"))
        by_file.setdefault(canonical, set()).add(evidence.category)
    return by_file


def _evidence_keys_by_file(
    profile: CapabilityProfile,
) -> dict[str, set[tuple[CapabilityCategory, str, str]]]:
    by_file: dict[str, set[tuple[CapabilityCategory, str, str]]] = {}
    for evidence in profile.evidence:
        if evidence.path_class != PathClass.SHIPPED:
            continue
        canonical = posixpath.normpath(evidence.file.replace("\\", "/"))
        key = (evidence.category, evidence.rule_id, evidence.snippet.strip())
        by_file.setdefault(canonical, set()).add(key)
    return by_file


def _scannable(status: str) -> bool:
    """Only a `semgrep_*` status means the scan itself didn't finish —
    `partial_fetch` (some files couldn't be extracted, e.g. Windows path
    limits) still produced a real, usable — if incomplete — profile."""
    return status in ("ok", "partial_fetch")


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
    `status="skipped_scan_incomplete"` when either scan didn't finish at all
    (a `semgrep_*` status) — an incomplete scan's empty/partial category set
    would otherwise make every unexplained file look like a drift signal, or
    hide a signal that's actually there. A `partial_fetch` profile (some
    files couldn't be extracted, but the scan itself ran) is still compared;
    tarball-only files that fall through every explained bucket but whose
    GitHub counterpart is known to be one of the paths GitHub couldn't
    extract are reported as `unverifiable` rather than `unexplained`, since
    "GitHub doesn't have this file" and "GitHub couldn't extract this file"
    are not the same thing.
    """
    if github_dir is None or github_profile is None:
        return DriftReport(name=name, version=version, status="skipped_github_unavailable")
    if not _scannable(tarball_profile.status) or not _scannable(github_profile.status):
        return DriftReport(name=name, version=version, status="skipped_scan_incomplete")

    tarball_files = _list_relative_files(tarball_dir)
    github_files = _list_relative_files(github_dir)

    # Declared build *directories* come from the tarball's package.json —
    # that's what determines which files actually ship. Whether a build
    # *script* exists is checked against the GitHub repo's package.json
    # instead: the attacker controls the published tarball's package.json,
    # so "the repo has a build script" has to mean the repo, not the
    # tarball, or an attacker could add a build/prepare script to their
    # malicious package.json and have it self-certify.
    tarball_package_json = _load_package_json(tarball_dir)
    github_package_json = _load_package_json(github_dir)
    build_dirs = _declared_build_dirs(tarball_package_json)
    has_build_script = _has_build_script(github_package_json)
    declared_deps = _declared_dependencies(github_package_json)

    tarball_evidence_by_file = _evidence_categories_by_file(tarball_profile)
    github_evidence_by_file = _evidence_categories_by_file(github_profile)
    tarball_evidence_keys = _evidence_keys_by_file(tarball_profile)
    github_evidence_keys = _evidence_keys_by_file(github_profile)
    github_categories = github_profile.category_set()

    # Exact names of paths GitHub's fetch/scan couldn't cover — a skipped
    # symlink, or one that would have exceeded the platform's path-length
    # limit. Matched by exact name, not recomputed: the fetcher checks the
    # length limit against a temporary staging path that is reliably longer
    # than the final cache path this module sees (a `tempfile.mkdtemp()`
    # directory plus an `extracted/` segment), so recomputing it here against
    # the final path would silently miss names in the gap between the two —
    # they'd fit by the recomputed check even though the real fetch skipped
    # them.
    github_unverifiable_paths = set(github_profile.skipped_link_names) | set(
        github_profile.skipped_long_path_names
    )

    matched: list[str] = []
    explained_by_sourcemap: list[str] = []
    explained_by_build: list[str] = []
    bundled_dependency: list[str] = []
    unexplained: list[str] = []
    unverifiable: list[str] = []
    new_evidence_in_matched: dict[str, list[dict]] = {}
    signal_files: dict[str, list[CapabilityCategory]] = {}
    relocated: list[dict] = []

    def _record(rel_path: str, excused: set[CapabilityCategory]) -> None:
        tb_categories = tarball_evidence_by_file.get(rel_path, set())
        novel = tb_categories - excused
        if not novel:
            return
        strong = novel - github_categories
        weak = novel - strong
        if strong:
            signal_files[rel_path] = sorted(strong, key=lambda c: c.value)
        if weak:
            relocated.append({"file": rel_path, "categories": sorted(weak, key=lambda c: c.value)})

    for rel_path in sorted(tarball_files):
        # Source maps are metadata *about* a shipped file, not shipped code in
        # their own right — they're consulted (via _classify_sourcemap) to
        # explain their sibling, not classified separately.
        if rel_path.endswith(".map"):
            continue

        if rel_path in github_files:
            matched.append(rel_path)
            _record(rel_path, github_evidence_by_file.get(rel_path, set()))
            new_keys = tarball_evidence_keys.get(rel_path, set()) - github_evidence_keys.get(
                rel_path, set()
            )
            if new_keys:
                new_evidence_in_matched[rel_path] = [
                    {"category": category.value, "rule_id": rule_id, "snippet": snippet}
                    for category, rule_id, snippet in sorted(
                        new_keys, key=lambda k: (k[0].value, k[1])
                    )
                ]
            continue

        sourcemap_verdict = _classify_sourcemap(
            rel_path,
            tarball_dir,
            github_files,
            github_evidence_by_file,
            declared_deps,
            github_categories,
        )
        if sourcemap_verdict is not None:
            kind, excused = sourcemap_verdict
            if kind == "bundled":
                bundled_dependency.append(rel_path)
            else:
                explained_by_sourcemap.append(rel_path)
            _record(rel_path, excused)
            continue

        build_excuse = _classify_build(
            rel_path,
            build_dirs,
            has_build_script,
            github_files,
            github_evidence_by_file,
            github_categories,
        )
        if build_excuse is not None:
            explained_by_build.append(rel_path)
            _record(rel_path, build_excuse)
            continue

        if rel_path in github_unverifiable_paths:
            unverifiable.append(rel_path)
        else:
            unexplained.append(rel_path)
            _record(rel_path, set())

    # Lifecycle hooks the tarball's package.json declares that the GitHub
    # repo's package.json doesn't (added, or changed) — the ua-parser-js
    # shape, caught without needing a previous published version.
    tarball_hooks = _hook_scripts(tarball_package_json)
    github_hooks = _hook_scripts(github_package_json)
    install_hooks_added = sorted(
        key for key, value in tarball_hooks.items() if github_hooks.get(key) != value
    )
    if install_hooks_added:
        signal_files["package.json"] = sorted(
            set(signal_files.get("package.json", [])) | {CapabilityCategory.BUILD_INSTALL},
            key=lambda c: c.value,
        )

    signal_categories = sorted(
        {category for categories in signal_files.values() for category in categories},
        key=lambda c: c.value,
    )

    return DriftReport(
        name=name,
        version=version,
        status="compared",
        matched=matched,
        explained_by_sourcemap=explained_by_sourcemap,
        explained_by_build=explained_by_build,
        bundled_dependency=bundled_dependency,
        unexplained=unexplained,
        unverifiable=unverifiable,
        signal=bool(signal_files),
        signal_files=signal_files,
        signal_categories=signal_categories,
        relocated=relocated,
        new_evidence_in_matched=new_evidence_in_matched,
        install_hooks_added=install_hooks_added,
    )
