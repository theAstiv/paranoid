"""Shared constants and helpers for PDF and Markdown export modules."""

from typing import Any

from pydantic import ValidationError

from backend.scoring.cvss31 import Cvss31Metrics, to_vector_string


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
    # `skip_reason` is a dependency that was never analyzed at all (no
    # resolvable pinned version, over the manifest's direct-dependency cap) —
    # distinct from `error`, which is a `PackageAnalysis` that was actually
    # attempted and failed. Conflating the two would flag an ordinary
    # git/file-spec dependency the same as a real analysis failure.
    if analysis.get("skip_reason"):
        flags.append("skipped")
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
    dropped/errored dependency was never resolved to a version.

    `package` may be a raw, unvalidated package.json key (a `context.skipped`
    entry is skipped *before* any name regex runs, so it never goes through
    `backend.deps.fetcher`'s npm-shaped validation) — collapse embedded
    newlines so one hostile manifest key can't break a table row across both
    export formats. Markdown's own `|` escaping happens at the call site in
    `backend.export.markdown`, since a literal `\\|` would be meaningless in
    the PDF export's Paragraph cells.
    """
    name = " ".join(package.split())
    return f"{name}@{version}" if version else name


def attack_techniques_display(threat: dict[str, Any]) -> str | None:
    """ "T1078.004, T1059 (suggested: AML.T0020)" label for a threat's
    technique matches, or None if it has none. Shared by markdown.py and
    pdf.py. Confirmed (table/seed) and suggested (embedding) matches are
    kept visually separate — an embedding match is a similarity guess the
    golden-set test measures well below the project's accuracy bar (see
    tests/live/test_attack_mapping_golden.py), not a confirmed lookup.
    """
    techniques = threat.get("attack_techniques") or []
    if not techniques:
        return None
    confirmed = [
        t["id"] for t in techniques if t.get("id") and t.get("method", "embedding") != "embedding"
    ]
    suggested = [
        t["id"] for t in techniques if t.get("id") and t.get("method", "embedding") == "embedding"
    ]
    parts = []
    if confirmed:
        parts.append(", ".join(confirmed))
    if suggested:
        parts.append(f"(suggested: {', '.join(suggested)})")
    return " ".join(parts) if parts else None


def cvss_display(row: dict[str, Any]) -> str | None:
    """ "7.5 (High) AV:N/AC:L/..." plain-text value for a threat's CVSS
    score, or None if it has none. Shared by markdown.py and pdf.py —
    mirrors attack_techniques_display()'s dual-shape handling and, like it,
    returns an unlabeled value; callers prepend their own format-specific
    "**CVSS:**"/"<b>CVSS:</b>" label.

    Handles two input shapes: a flat DB row (`cvss_score`, `cvss_severity`,
    `cvss_vector` columns) and a nested model_dump (`cvss_score`/
    `cvss_severity` are still flat Threat fields, but there's no
    `cvss_vector` string — only the nested `cvss` metrics dict, rendered
    back to the canonical vector string here).
    """
    score = row.get("cvss_score")
    if score is None:
        return None

    vector = row.get("cvss_vector")
    if not vector:
        metrics = row.get("cvss")
        if isinstance(metrics, dict) and metrics:
            try:
                vector = to_vector_string(Cvss31Metrics(**metrics))
            except (TypeError, ValidationError):
                vector = None

    severity = row.get("cvss_severity")
    label = f"{score:.1f}" + (f" ({severity.capitalize()})" if severity else "")
    return f"{label} {vector}" if vector else label


def cvss_security_severity(row: dict[str, Any]) -> str | None:
    """The numeric string SARIF's `security-severity` property expects
    (GitHub code scanning reads this for its own severity sort/badge), or
    None if the threat has no computed CVSS score."""
    score = row.get("cvss_score")
    return str(score) if score is not None else None


def dependency_findings_rows(
    dependency_scans: list[dict[str, Any]] | None,
) -> list[tuple[str, str, str]]:
    """Return (package@version, categories, flags) display rows for one export.

    `dependency_scans` is the raw `dependency_scans` DB row list (each row's
    `analysis` field already `json.loads`-decoded into a `PackageAnalysis`-
    shaped dict) — see `backend.db.crud.list_dependency_scans`.

    Rows are sorted case-insensitively by package name — `list_dependency_scans`
    orders by `created_at DESC`, which is meaningless for display (skipped
    rows are inserted last, so they'd sort first; everything else is reverse
    alphabetical) — except the `dependency_scan_rows()` "+N more skipped"
    summary row, which sorts last regardless of its name (a leading "+"
    would otherwise put it first).
    """

    def _sort_key(scan: dict[str, Any]) -> tuple[bool, str]:
        analysis = scan.get("analysis") or {}
        name = dependency_display_name(scan.get("package", ""), scan.get("version", ""))
        return (bool(analysis.get("skip_summary")), name.lower())

    rows: list[tuple[str, str, str]] = []
    for scan in sorted(dependency_scans or [], key=_sort_key):
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
