"""Reachability-lite: promote TEST/EXAMPLE/BUILD files that are actually
loaded by shipped code, without running Semgrep.

`PathClass` (backend/deps/scanner.py `classify_path`) sorts a file into
SHIPPED/TEST/EXAMPLE/BUILD by path alone, and `CapabilityProfile.category_set()`
only counts SHIPPED evidence. That's the right default — most code under
test/ or docs/ never runs in production — but it also means a payload
planted in `test/payload.js` and `require()`'d from `index.js` is invisible.

This module resolves relative `require()`/`import`/`export ... from`
specifiers (string literals only — no bundler, no type checker) starting
from a package's declared entry points and its SHIPPED files, and follows
them to a fixed point. Any TEST/EXAMPLE/BUILD file reached this way is
reachable from code that ships, so `backend.deps.scanner` reclassifies it
SHIPPED.
"""

import json
import re
from collections.abc import Callable
from pathlib import Path

from backend.models.enums import PathClass


_IGNORED_DIRS = frozenset({"node_modules", ".git"})
_RESOLVE_EXTENSIONS = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json")
_SPECIFIER_RE = re.compile(
    r"""
    \b(?:require|import)\(\s*['"](\.[^'"]+)['"]  |  # require('./x') / import('./x')
    \bimport\b[^'"();]*?\bfrom\b\s*['"](\.[^'"]+)['"]  |  # import ... from './x'
    \bimport\s+['"](\.[^'"]+)['"]  |  # import './x' (side-effect)
    \bexport\b[^'"();]*?\bfrom\b\s*['"](\.[^'"]+)['"]  # export ... from './x'
    """,
    re.VERBOSE,
)


def _extract_specifiers(text: str) -> list[str]:
    specs = []
    for match in _SPECIFIER_RE.finditer(text):
        specs.append(next(g for g in match.groups() if g is not None))
    return specs


def _iter_strings(value: object) -> list[str]:
    """Flatten every string leaf out of a package.json field that may be a
    bare string or an arbitrarily nested conditions/array map (e.g. "exports")."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _iter_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _iter_strings(v)]
    return []


def _entry_specifiers(root: Path) -> list[str]:
    package_json = root / "package.json"
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []

    specs: list[str] = []
    for field in ("main", "module", "browser", "bin"):
        specs.extend(_iter_strings(data.get(field)))
    specs.extend(_iter_strings(data.get("exports")))
    return specs


def _resolve(root: Path, from_dir: Path, specifier: str) -> Path | None:
    """Resolve a relative specifier the way Node's CommonJS/ESM loader would:
    the literal path, then each extension appended, then `<path>/index.<ext>`.
    Never returns a path outside `root` (a `../../etc/passwd`-shaped
    specifier resolving outside the package tree is simply unresolvable).

    `root` must already be resolved (`Path.resolve()`) — this function
    resolves every candidate to compare against it, and an unresolved `root`
    would make `relative_to` raise on every match.
    """
    base = (from_dir / specifier).resolve()
    candidates = [base]
    if base.suffix == "" or base.suffix not in _RESOLVE_EXTENSIONS:
        candidates += [Path(f"{base}{ext}") for ext in _RESOLVE_EXTENSIONS]
    candidates += [base / f"index{ext}" for ext in _RESOLVE_EXTENSIONS]

    for candidate in candidates:
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def find_reachable_files(root: Path, classify: Callable[[str], PathClass]) -> dict[str, str]:
    """Return `{promoted_rel_path: via_rel_path}` for every TEST/EXAMPLE/BUILD
    file reachable, through relative require()/import specifiers, from a
    declared package.json entry point or another SHIPPED file. A declared
    entry point that is itself TEST/EXAMPLE/BUILD-classified is promoted too
    (`via` = "package.json").

    `classify` is `backend.deps.scanner.classify_path`, injected rather than
    imported directly — `scanner` imports this module, so importing it back
    would create a cycle.
    """
    try:
        root = root.resolve()
        all_files = [
            p
            for p in root.rglob("*")
            if p.is_file() and not _IGNORED_DIRS & set(p.relative_to(root).parts[:-1])
        ]
    except OSError:
        return {}

    shipped = [
        p for p in all_files if classify(p.relative_to(root).as_posix()) == PathClass.SHIPPED
    ]

    promoted: dict[str, str] = {}
    queue: list[Path] = list(shipped)
    visited: set[Path] = set(queue)
    for spec in _entry_specifiers(root):
        resolved = _resolve(root, root, spec)
        if resolved is None or resolved in visited:
            continue
        visited.add(resolved)
        rel = resolved.relative_to(root).as_posix()
        if classify(rel) != PathClass.SHIPPED:
            promoted.setdefault(rel, "package.json")
        queue.append(resolved)

    idx = 0
    while idx < len(queue):
        current = queue[idx]
        idx += 1
        try:
            text = current.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for spec in _extract_specifiers(text):
            target = _resolve(root, current.parent, spec)
            if target is None or target in visited:
                continue
            visited.add(target)
            rel = target.relative_to(root).as_posix()
            if classify(rel) != PathClass.SHIPPED:
                promoted.setdefault(rel, current.relative_to(root).as_posix())
            queue.append(target)

    return promoted
