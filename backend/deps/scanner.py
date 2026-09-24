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
import re
import shutil
from pathlib import Path

from backend.config import settings
from backend.deps.install_hooks import find_install_hooks
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


async def _run_semgrep(binary: str, target: Path) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
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
        "--exclude",
        "node_modules",
        str(target),
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


def _build_evidence(
    result: dict, target: Path, source_kind: SourceKind
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

    snippet = result.get("extra", {}).get("lines", "").strip()
    if len(snippet) > _SNIPPET_MAX_LEN:
        snippet = snippet[:_SNIPPET_MAX_LEN] + "..."

    return CapabilityEvidence(
        category=category,
        rule_id=result.get("check_id", "unknown"),
        file=rel_path,
        line=result.get("start", {}).get("line", 0),
        snippet=snippet,
        source_kind=source_kind,
        path_class=classify_path(rel_path),
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

    try:
        returncode, stdout, stderr = await _run_semgrep(binary, path)
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

    try:
        output = json.loads(stdout)
    except json.JSONDecodeError:
        logger.warning(
            "Semgrep produced non-JSON output for %s@%s: %s", name, version, stderr[:500]
        )
        return CapabilityProfile(
            name=name, version=version, source_kind=source_kind, status="semgrep_error"
        )

    # Semgrep exits 0 for a normal scan regardless of findings (we don't pass
    # --error), so a non-zero code means something broke. Within the "errors"
    # array, only a warn-level parse error on part of a file is recoverable;
    # a per-file timeout (reported at warn level too) means evidence from that
    # file may be missing, so the profile must not claim a clean "ok".
    scan_errors = output.get("errors", [])
    timed_out = [e for e in scan_errors if _error_kind(e) in _TIMEOUT_ERROR_KINDS]
    fatal_errors = [e for e in scan_errors if e not in timed_out and not _is_recoverable_error(e)]
    if returncode != 0 or fatal_errors or timed_out:
        status = "semgrep_timeout" if timed_out and not fatal_errors else "semgrep_error"
        logger.warning(
            "Semgrep scan incomplete for %s@%s (exit=%d, %d fatal, %d timed out): %s",
            name,
            version,
            returncode,
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

    evidence = []
    for result in output.get("results", []):
        item = _build_evidence(result, path, source_kind)
        if item is not None:
            evidence.append(item)

    package_json = path / "package.json"
    install_hooks = find_install_hooks(package_json) if package_json.is_file() else []

    capability_vector = sorted({e.category for e in evidence}, key=lambda c: c.value)

    return CapabilityProfile(
        name=name,
        version=version,
        source_kind=source_kind,
        evidence=evidence,
        install_hooks=install_hooks,
        capability_vector=capability_vector,
        status="ok",
    )
