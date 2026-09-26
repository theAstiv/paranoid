"""Semgrep-backed capability scanner for a fetched dependency source tree.

Wraps `semgrep scan --config backend/deps/rules/js ...` as a subprocess.
Semgrep missing, crashing, or timing out degrades to a `status` on the
returned profile plus a log line — never an exception to callers, matching
the optional-tool pattern used for context-link (backend/mcp/client.py).
"""

import asyncio
import contextlib
import json
import logging
import posixpath
import re
import shutil
from pathlib import Path

from backend.config import settings
from backend.deps.install_hooks import find_install_hooks, find_install_time_files
from backend.deps.references import find_install_time_closure, find_reachable
from backend.models.dependencies import CapabilityEvidence, CapabilityProfile
from backend.models.enums import CapabilityCategory, PathClass, SourceKind


logger = logging.getLogger(__name__)

RULES_DIR = Path(__file__).resolve().parent / "rules" / "js"
# Per-file limit passed to Semgrep's own --timeout, and a much larger budget
# for the whole run — a package with a few large dist/ bundles must not trip
# the whole-run kill just because each file takes a while.
_PER_FILE_TIMEOUT_S = 30
_SCAN_TIMEOUT_S = 300.0
_SNIPPET_MAX_LEN = 200

# Semgrep error kinds that only mean "part of one file couldn't be parsed" —
# the only errors treated as recoverable, and only at level "warn". Anything
# else (including kinds added in future Semgrep versions) fails closed.
_RECOVERABLE_ERROR_KINDS = frozenset(
    {"PartialParsing", "Syntax error", "Lexical error", "Other syntax error"}
)
# Kinds meaning a file's scan was cut short — evidence from it may be missing.
_TIMEOUT_ERROR_KINDS = frozenset(
    {"Timeout", "Fixpoint timeout", "Timeout during interfile analysis"}
)

_TEST_SEGMENT_RE = re.compile(r"(^|/)(test|tests|__tests__|spec)(/|$)")
_TEST_FILE_RE = re.compile(r"\.(spec|test)\.[^/]+$")
_EXAMPLE_SEGMENT_RE = re.compile(r"(^|/)(examples?|docs?)(/|$)")
# dist/, lib/, build/, esm/, cjs/ are deliberately NOT here: in a published
# npm tarball those directories are usually the code that actually runs
# ("main": "dist/index.js"), so demoting them would hide real capabilities.
# BUILD is only for tooling that ships but never executes at runtime.
_BUILD_SEGMENT_RE = re.compile(r"(^|/)(benchmarks?|bench)(/|$)")
_BUILD_FILE_RE = re.compile(r"(^|/)[^/]*\.config\.(c|m)?[jt]s$")


def resolve_semgrep_binary() -> str | None:
    """Find the Semgrep binary: explicit setting -> PATH. No repo-bundled fallback
    (unlike context-link) — Semgrep is a pip/pipx install, documented in CLAUDE.md."""
    explicit = settings.semgrep_binary.strip()
    if explicit:
        return explicit
    return shutil.which("semgrep")


def classify_path(rel_path: str) -> PathClass:
    """Classify a file's role within a package, by its path alone."""
    normalized = rel_path.replace("\\", "/").lstrip("./")
    if _TEST_SEGMENT_RE.search(normalized) or _TEST_FILE_RE.search(normalized):
        return PathClass.TEST
    if _EXAMPLE_SEGMENT_RE.search(normalized):
        return PathClass.EXAMPLE
    if _BUILD_SEGMENT_RE.search(normalized) or _BUILD_FILE_RE.search(normalized):
        return PathClass.BUILD
    return PathClass.SHIPPED


# Every extra target's absolute path is a separate argv entry; Windows caps a
# process's total command line around ~32K characters (CreateProcess's
# UNICODE_STRING limit). A package that ships hundreds of non-JS-extension
# files reachable via require()/import (see find_reachable_unscanned_files) —
# or an attacker publishing one on purpose, specifically to disable drift —
# could otherwise blow that limit, turn `create_subprocess_exec` into an
# OSError, and degrade the whole scan to `semgrep_error`.
#
# Batched by total *character* length, not count: cache paths vary widely in
# length (deep monorepo directories vs. short ones), so a fixed path count
# doesn't bound argv length — 200 paths at ~250 chars each is already ~50K,
# well past the limit. 28,000 leaves headroom for the binary path, flags, the
# rules config path, and the directory target itself.
_MAX_EXTRA_TARGETS_ARGV_CHARS = 28_000
# Hard cap on the total extra targets scanned per package, regardless of
# batching — unbounded batches mean unbounded scan time (each batch pays its
# own semgrep startup cost and _SCAN_TIMEOUT_S budget). Enforced in
# scan_source(), not here: a package with more reachable non-standard-
# extension files than this has the remainder recorded on the profile as
# CapabilityProfile.unscanned_reachable_files rather than silently dropped —
# a status="ok" profile with unscanned reachable code would otherwise let an
# attacker who knows the cap hide a payload past it. No legitimate package
# needs more than this many non-JS-extension files loaded as code.
_MAX_EXTRA_TARGETS_TOTAL = 2000


def _semgrep_base_args(binary: str, *, scan_unknown_extensions: bool) -> list[str]:
    args = [
        binary,
        "scan",
        "--config",
        str(RULES_DIR),
        "--json",
        "--metrics=off",
        "--disable-version-check",
        "--no-git-ignore",
        # Semgrep's built-in default .semgrepignore silently skips common
        # dirs like test/tests before we ever see them — which would make
        # PathClass.TEST unreachable, since our own classification never
        # gets a chance to run on those files. We scan everything and
        # classify (SHIPPED/TEST/EXAMPLE/BUILD) ourselves.
        "--x-ignore-semgrepignore-files",
        "--timeout",
        str(_PER_FILE_TIMEOUT_S),
    ]
    if scan_unknown_extensions:
        args.append("--scan-unknown-extensions")
    return args


async def _exec_semgrep(args: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=_SCAN_TIMEOUT_S)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        raise
    return (
        proc.returncode or 0,
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
    )


async def _run_semgrep(
    binary: str, target: Path, extra_targets: tuple[Path, ...] = ()
) -> tuple[int, str, str]:
    """`extra_targets` are files reachable via a relative require()/import
    whose extension Semgrep wouldn't otherwise scan (e.g. `require('./lib/data.map')`
    — Node executes whatever a require() resolves to, extension or not).
    `--scan-unknown-extensions` only takes effect for targets named explicitly
    on the command line, which is exactly what these are — it has no effect
    on `target`'s own directory walk, so ordinary unrelated non-JS files
    aren't swept in. Callers with more than fit under
    `_MAX_EXTRA_TARGETS_ARGV_CHARS` must batch via `_run_semgrep_scan` instead
    of calling this directly with the full list."""
    args = _semgrep_base_args(binary, scan_unknown_extensions=bool(extra_targets))
    args += ["--exclude", "node_modules", str(target)]
    args.extend(str(p) for p in extra_targets)
    return await _exec_semgrep(args)


async def _run_semgrep_extra_only(binary: str, targets: tuple[Path, ...]) -> tuple[int, str, str]:
    """One semgrep invocation scanning only explicit `targets` files, with no
    directory target — used for extra-target batches beyond the first (see
    `_run_semgrep_scan`)."""
    args = _semgrep_base_args(binary, scan_unknown_extensions=True)
    args.extend(str(p) for p in targets)
    return await _exec_semgrep(args)


def _batch_by_argv_length(paths: tuple[Path, ...], budget: int) -> list[tuple[Path, ...]]:
    """Split `paths` into batches whose total stringified length (plus one
    separating character per path) stays under `budget`. A fixed per-batch
    *count* isn't safe here — real fetched-package paths vary widely in
    length (a deep monorepo cache path vs. a short one), so only a
    length-based budget actually bounds argv length."""
    batches: list[list[Path]] = []
    current: list[Path] = []
    current_len = 0
    for p in paths:
        p_len = len(str(p)) + 1  # +1 for the separating argv boundary
        if current and current_len + p_len > budget:
            batches.append(current)
            current = []
            current_len = 0
        current.append(p)
        current_len += p_len
    if current:
        batches.append(current)
    return [tuple(b) for b in batches]


async def _run_semgrep_scan(
    binary: str, target: Path, extra_targets: tuple[Path, ...]
) -> list[tuple[int, str, str]]:
    """Run semgrep over `target`'s directory plus every extra target,
    batching extra targets by total argv length so a single command line
    never risks the Windows argv length limit. Returns one
    `(returncode, stdout, stderr)` tuple per invocation — a single-element
    list in the common case (few or no extra targets) — for the caller to
    merge parsed JSON output across.

    Callers must apply `_MAX_EXTRA_TARGETS_TOTAL` themselves before calling
    this — silently dropping targets *here* would mean scan_source's caller
    (and drift) never finds out that some reachable code went unscanned, and
    an attacker who knows the cap could put a payload in file number 2001 and
    have it disappear with the profile still reporting `status="ok"`.
    """
    batches = _batch_by_argv_length(extra_targets, _MAX_EXTRA_TARGETS_ARGV_CHARS)
    if not batches:
        return [await _run_semgrep(binary, target, ())]
    runs = [await _run_semgrep(binary, target, batches[0])]
    for batch in batches[1:]:
        runs.append(await _run_semgrep_extra_only(binary, batch))
    return runs


def _canonicalize(rel_path: str) -> str:
    """`rel_path` (relative to the scan target, which is already the
    package's content root — `fetch_source()` extracts without any wrapper
    directory) normalized to match the root-relative paths
    `references.find_reachable_files` and `install_hooks.find_install_time_files`
    operate on."""
    return posixpath.normpath(rel_path.replace("\\", "/"))


def _read_lines(path: Path, cache: dict[Path, list[str]]) -> list[str]:
    if path not in cache:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        cache[path] = text.split("\n")
    return cache[path]


def _extract_snippet(lines: list[str], start: dict, end: dict) -> str:
    """The real source snippet for a match, windowed to `_SNIPPET_MAX_LEN`
    chars around the match's columns.

    Semgrep CE always redacts `extra.lines` to "requires login", so the
    snippet has to be read from the file itself. A plain `line[:MAX]` would
    just dump the start of the line — useless for a match deep inside a
    minified single-line bundle — so the window is centered on the match.
    """
    start_line = start.get("line", 0)
    end_line = end.get("line", start_line)
    if start_line < 1 or start_line > len(lines):
        return ""

    if start_line == end_line:
        line = lines[start_line - 1]
        match_start = max(start.get("col", 1) - 1, 0)
        match_end = min(max(end.get("col", match_start + 1) - 1, match_start), len(line))
        pad = max((_SNIPPET_MAX_LEN - (match_end - match_start)) // 2, 0)
        window_start = max(match_start - pad, 0)
        window_end = min(window_start + _SNIPPET_MAX_LEN, len(line))
        window_start = max(window_end - _SNIPPET_MAX_LEN, 0)
        prefix = "..." if window_start > 0 else ""
        suffix = "..." if window_end < len(line) else ""
        return f"{prefix}{line[window_start:window_end]}{suffix}".strip()

    joined = "\n".join(lines[start_line - 1 : end_line]).strip()
    if len(joined) > _SNIPPET_MAX_LEN:
        joined = joined[:_SNIPPET_MAX_LEN] + "..."
    return joined


def _build_evidence(
    result: dict,
    target: Path,
    source_kind: SourceKind,
    *,
    line_cache: dict[Path, list[str]],
    promoted: dict[str, str],
    install_time_files: set[str],
) -> CapabilityEvidence | None:
    metadata = result.get("extra", {}).get("metadata", {})
    category_str = metadata.get("category")
    try:
        category = CapabilityCategory(category_str)
    except ValueError:
        logger.warning(
            "Semgrep rule %s has no valid metadata.category — skipping", result.get("check_id")
        )
        return None

    abs_path = Path(result["path"])
    try:
        rel_path = str(abs_path.relative_to(target))
    except ValueError:
        rel_path = str(abs_path)
    canonical = _canonicalize(rel_path)

    snippet = _extract_snippet(
        _read_lines(abs_path, line_cache), result.get("start", {}), result.get("end", {})
    )

    original_class = classify_path(rel_path)
    path_class = original_class
    reclassified_from = None
    reclassified_via = None
    is_install_time = canonical in install_time_files
    if original_class != PathClass.SHIPPED:
        if canonical in promoted:
            reclassified_from = original_class
            reclassified_via = promoted[canonical]
            path_class = PathClass.SHIPPED
        elif is_install_time:
            # A file a lifecycle hook runs directly is SHIPPED by definition
            # — it executes on `npm install` whether or not anything ever
            # require()'s it, so path-based TEST/EXAMPLE/BUILD demotion
            # would otherwise hide it from category_set() entirely.
            reclassified_from = original_class
            reclassified_via = "package.json (install hook)"
            path_class = PathClass.SHIPPED

    return CapabilityEvidence(
        category=category,
        rule_id=result.get("check_id", "unknown"),
        file=rel_path,
        line=result.get("start", {}).get("line", 0),
        snippet=snippet,
        source_kind=source_kind,
        path_class=path_class,
        reclassified_from=reclassified_from,
        reclassified_via=reclassified_via,
        install_time=is_install_time,
    )


def _error_kind(error: dict) -> str:
    """Semgrep reports an error's `type` as either a bare string or
    `[kind, details...]`."""
    kind = error.get("type")
    if isinstance(kind, list) and kind:
        kind = kind[0]
    return kind if isinstance(kind, str) else ""


def _is_recoverable_error(error: dict) -> bool:
    return error.get("level") == "warn" and _error_kind(error) in _RECOVERABLE_ERROR_KINDS


async def scan_source(
    path: Path, source_kind: SourceKind, *, name: str, version: str
) -> CapabilityProfile:
    """Scan `path` (an already-fetched, extracted package source tree) for capabilities.

    `name`/`version` identify the package in the returned profile — `scan_source`
    itself is stateless with respect to package identity, so the caller supplies
    them (matching `fetch_source`'s `ResolvedPackage` input elsewhere in this package).
    """
    binary = resolve_semgrep_binary()
    if binary is None:
        logger.warning(
            "Semgrep binary not found (set SEMGREP_BINARY or install semgrep on PATH) "
            "— skipping capability scan for %s@%s",
            name,
            version,
        )
        return CapabilityProfile(
            name=name, version=version, source_kind=source_kind, status="semgrep_unavailable"
        )

    package_json = path / "package.json"
    install_hooks = find_install_hooks(package_json) if package_json.is_file() else []
    raw_install_time_files = (
        find_install_time_files(package_json) if package_json.is_file() else set()
    )
    raw_install_time_files = frozenset(f.replace("\\", "/") for f in raw_install_time_files)
    install_time_files = (
        find_install_time_closure(path, raw_install_time_files) | raw_install_time_files
    )
    promoted, unscanned_files = (
        find_reachable(path, classify_path, raw_install_time_files)
        if path.is_dir()
        else ({}, set())
    )
    sorted_unscanned = sorted(unscanned_files)
    # Capped *before* scanning, not inside _run_semgrep_scan: the dropped
    # paths must be recorded on the profile, not silently discarded — a
    # non-empty status="ok" profile with unscanned reachable code would let
    # an attacker who knows the cap hide a payload past it (e.g. 2000
    # harmless a0000.txt..a1999.txt files, then the real payload in
    # file 2001) and have drift never find out. See CapabilityProfile
    # .unscanned_reachable_files.
    scanned_unscanned = sorted_unscanned[:_MAX_EXTRA_TARGETS_TOTAL]
    dropped_unscanned = sorted_unscanned[_MAX_EXTRA_TARGETS_TOTAL:]
    if dropped_unscanned:
        logger.warning(
            "%d files reachable via require()/import have non-standard extensions for "
            "%s@%s — capping at %d to bound scan time; the rest are recorded as unscanned",
            len(sorted_unscanned),
            name,
            version,
            _MAX_EXTRA_TARGETS_TOTAL,
        )
    extra_targets = tuple(path / rel for rel in scanned_unscanned)

    try:
        runs = await _run_semgrep_scan(binary, path, extra_targets)
    except TimeoutError:
        logger.warning("Semgrep scan timed out after %ss for %s@%s", _SCAN_TIMEOUT_S, name, version)
        return CapabilityProfile(
            name=name, version=version, source_kind=source_kind, status="semgrep_timeout"
        )
    except OSError as exc:
        logger.warning("Semgrep scan crashed for %s@%s: %s", name, version, exc)
        return CapabilityProfile(
            name=name, version=version, source_kind=source_kind, status="semgrep_error"
        )

    # `runs` is one (returncode, stdout, stderr) per semgrep invocation — a
    # single element in the common case, more when extra_targets was batched
    # (see _run_semgrep_scan). Merge every batch's parsed output before
    # applying the usual returncode/error checks, so a package needing
    # several batches is judged as one scan, not several independent ones.
    combined_results: list[dict] = []
    combined_errors: list[dict] = []
    worst_returncode = 0
    for returncode, stdout, stderr in runs:
        try:
            output = json.loads(stdout)
        except json.JSONDecodeError:
            logger.warning(
                "Semgrep produced non-JSON output for %s@%s: %s", name, version, stderr[:500]
            )
            return CapabilityProfile(
                name=name, version=version, source_kind=source_kind, status="semgrep_error"
            )
        combined_results.extend(output.get("results", []))
        combined_errors.extend(output.get("errors", []))
        if returncode != 0:
            worst_returncode = returncode

    # Semgrep exits 0 for a normal scan regardless of findings (we don't pass
    # --error), so a non-zero code means something broke. Within the "errors"
    # array, only a warn-level parse error on part of a file is recoverable;
    # a per-file timeout (reported at warn level too) means evidence from that
    # file may be missing, so the profile must not claim a clean "ok".
    scan_errors = combined_errors
    timed_out = [e for e in scan_errors if _error_kind(e) in _TIMEOUT_ERROR_KINDS]
    fatal_errors = [e for e in scan_errors if e not in timed_out and not _is_recoverable_error(e)]
    if worst_returncode != 0 or fatal_errors or timed_out:
        status = "semgrep_timeout" if timed_out and not fatal_errors else "semgrep_error"
        logger.warning(
            "Semgrep scan incomplete for %s@%s (exit=%d, %d fatal, %d timed out): %s",
            name,
            version,
            worst_returncode,
            len(fatal_errors),
            len(timed_out),
            (fatal_errors or timed_out or scan_errors)[:3],
        )
        return CapabilityProfile(name=name, version=version, source_kind=source_kind, status=status)
    if scan_errors:
        logger.info(
            "Semgrep reported %d recoverable parse warning(s) for %s@%s",
            len(scan_errors),
            name,
            version,
        )

    line_cache: dict[Path, list[str]] = {}
    evidence = []
    for result in combined_results:
        item = _build_evidence(
            result,
            path,
            source_kind,
            line_cache=line_cache,
            promoted=promoted,
            install_time_files=install_time_files,
        )
        if item is not None:
            evidence.append(item)

    # Matches category_set()'s own BUILD_INSTALL-from-hooks rule so this
    # display field and category_set() never disagree in the CLI/JSON output.
    vector_categories = {e.category for e in evidence}
    if install_hooks:
        vector_categories.add(CapabilityCategory.BUILD_INSTALL)
    capability_vector = sorted(vector_categories, key=lambda c: c.value)

    return CapabilityProfile(
        name=name,
        version=version,
        source_kind=source_kind,
        evidence=evidence,
        install_hooks=install_hooks,
        capability_vector=capability_vector,
        unscanned_reachable_files=dropped_unscanned,
        status="ok",
    )
