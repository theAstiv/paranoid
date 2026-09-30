"""Shared constants and helpers for PDF and Markdown export modules."""

from typing import Any


# Mermaid diagram type prefixes used to distinguish diagram source from prose.
# Both pdf.py and markdown.py use this tuple — keep it here to avoid drift.
MERMAID_DIAGRAM_PREFIXES = (
    "graph ",
    "flowchart ",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "erDiagram",
    "gantt",
    "pie ",
    "mindmap",
    "journey",
)


def dependency_category_set(profile: dict[str, Any] | None) -> set[str]:
    """Categories a `CapabilityProfile` dict shows shipped-path evidence for.

    Mirrors `CapabilityProfile.category_set()` on the backend model and the
    frontend's `dependencyCategorySet()` — only `path_class == "shipped"`
    evidence counts, and a flagged install hook always contributes
    `build_install` even without its own evidence entry.
    """
    categories: set[str] = set()
    if not profile:
        return categories
    for e in profile.get("evidence") or []:
        if e.get("path_class") == "shipped":
            categories.add(e["category"])
    if profile.get("install_hooks"):
        categories.add("build_install")
    return categories


def dependency_flags(analysis: dict[str, Any] | None) -> list[str]:
    """Short flag labels summarizing one package's dependency-engine analysis.

    Mirrors the frontend's `dependencyFlags()` in `frontend/src/lib/utils.js`
    — keep the two in sync.
    """
    flags: list[str] = []
    if not analysis:
        return flags
    if analysis.get("error"):
        flags.append("error")
    drift = analysis.get("drift") or {}
    if drift.get("signal"):
        flags.append("drift")
    npm_profile = analysis.get("npm_profile") or {}
    if npm_profile.get("install_hooks"):
        flags.append("install-hook")
    for profile in (analysis.get("npm_profile"), analysis.get("github_profile")):
        status = (profile or {}).get("status")
        if status and status != "ok":
            flags.append(status)
    return list(dict.fromkeys(flags))


def dependency_display_name(package: str, version: str) -> str:
    """Format a package's display label — omits a dangling "@" when a
    dropped/errored dependency was never resolved to a version."""
    return f"{package}@{version}" if version else package


def dependency_findings_rows(
    dependency_scans: list[dict[str, Any]] | None,
) -> list[tuple[str, str, str]]:
    """Return (package@version, categories, flags) display rows for one export.

    `dependency_scans` is the raw `dependency_scans` DB row list (each row's
    `analysis` field already `json.loads`-decoded into a `PackageAnalysis`-
    shaped dict) — see `backend.db.crud.list_dependency_scans`.
    """
    rows: list[tuple[str, str, str]] = []
    for scan in dependency_scans or []:
        analysis = scan.get("analysis") or {}
        categories = dependency_category_set(analysis.get("npm_profile")) | dependency_category_set(
            analysis.get("github_profile")
        )
        flags = dependency_flags(analysis)
        rows.append(
            (
                dependency_display_name(scan.get("package", ""), scan.get("version", "")),
                ", ".join(sorted(categories)) or "—",
                ", ".join(flags) or "—",
            )
        )
    return rows
