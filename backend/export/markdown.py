"""Markdown export for human-readable threat model documents.

Produces clean Markdown suitable for PRs, Confluence, Notion, and security review docs.
"""

from datetime import UTC, datetime
from typing import Any


def export_markdown(
    threats: list[dict[str, Any]],
    model_id: str,
    framework: str,
    title: str | None = None,
    source_file: str | None = None,
    include_header: bool = True,
    assets: list[dict[str, Any]] | None = None,
    flows: list[dict[str, Any]] | None = None,
    trust_boundaries: list[dict[str, Any]] | None = None,
    attack_trees: dict[str, dict[str, Any]] | None = None,
    test_suites: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Export threats to Markdown format.

    Args:
        threats: List of threat dicts. Accepts both DB row shape (flat DREAD fields:
                 dread_score, dread_damage, ...) and model_dump() shape (nested dread dict).
        model_id: Unique identifier for this threat model run.
        framework: Framework used (STRIDE or MAESTRO).
        title: Optional display title. Falls back to model_id[:8].
        source_file: Optional path to the analyzed input file.
        include_header: If False, skips the H1 heading and metadata block.
                        Useful when embedding into an existing document.
        assets: Optional list of asset dicts from the DB.
        flows: Optional list of data flow dicts from the DB.
        trust_boundaries: Optional list of trust boundary dicts from the DB.
        attack_trees: Optional mapping of threat_id -> AttackTree.model_dump().
        test_suites: Optional mapping of threat_id -> TestSuite.model_dump().

    Returns:
        Markdown string ready to write to a .md file.
    """
    lines: list[str] = []

    display_title = title or model_id[:8]
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    if include_header:
        lines.append(f"# Threat Model: {display_title}")
        lines.append("")
        lines.append(
            f"**Framework:** {framework} | **Model ID:** `{model_id[:8]}` | **Generated:** {generated_at}"
        )
        if source_file:
            lines.append(f"**Source:** `{source_file}`")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Assets
    if assets:
        lines.append("## Assets")
        lines.append("")
        lines.append("| Name | Type | Description |")
        lines.append("|------|------|-------------|")
        for a in assets:
            name = (a.get("name") or "—").replace("|", "\\|")
            atype = (a.get("type") or "—").replace("|", "\\|")
            desc = (a.get("description") or "—").replace("|", "\\|")
            lines.append(f"| {name} | {atype} | {desc} |")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Data Flows
    if flows:
        lines.append("## Data Flows")
        lines.append("")
        lines.append("| Source | Target | Type | Description |")
        lines.append("|--------|--------|------|-------------|")
        for f in flows:
            src = (f.get("source_entity") or "—").replace("|", "\\|")
            tgt = (f.get("target_entity") or "—").replace("|", "\\|")
            ftype = (f.get("flow_type") or "—").replace("|", "\\|")
            desc = (f.get("flow_description") or "—").replace("|", "\\|")
            lines.append(f"| {src} | {tgt} | {ftype} | {desc} |")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Trust Boundaries
    if trust_boundaries:
        lines.append("## Trust Boundaries")
        lines.append("")
        lines.append("| Source | Target | Purpose |")
        lines.append("|--------|--------|---------|")
        for tb in trust_boundaries:
            src = (tb.get("source_entity") or "—").replace("|", "\\|")
            tgt = (tb.get("target_entity") or "—").replace("|", "\\|")
            purpose = (tb.get("purpose") or "—").replace("|", "\\|")
            lines.append(f"| {src} | {tgt} | {purpose} |")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| # | Threat | Category | Target | Likelihood | DREAD |")
    lines.append("|---|--------|----------|--------|------------|-------|")

    if not threats:
        lines.append("")
        lines.append("*No threats recorded.*")
        lines.append("")
        return "\n".join(lines)

    for i, t in enumerate(threats, 1):
        name = t.get("name") or "—"
        category = _category_from_row(t)
        target = t.get("target") or "—"
        likelihood = t.get("likelihood") or "—"
        dread = _dread_score_cell(t)
        lines.append(f"| {i} | {name} | {category} | {target} | {likelihood} | {dread} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Threats by category
    lines.append("## Threats")
    lines.append("")

    grouped = _group_by_category(threats)
    global_idx = 1

    for category, category_threats in grouped.items():
        lines.append(f"### {category}")
        lines.append("")

        for t in category_threats:
            name = t.get("name") or "unnamed"
            target = t.get("target") or "—"
            likelihood = t.get("likelihood") or "—"
            impact = t.get("impact") or "—"
            description = (t.get("description") or "").strip()

            lines.append(f"#### {global_idx}. {name}")
            lines.append("")
            lines.append(
                f"**Target:** {target} | **Likelihood:** {likelihood} | **Impact:** {impact}"
            )

            dread_line = _dread_display(t)
            if dread_line:
                lines.append(dread_line)

            lines.append("")

            if description:
                lines.append(f"> {description}")
                lines.append("")

            mitigations = t.get("mitigations") or []
            if mitigations:
                lines.append("**Mitigations:**")
                for m in mitigations:
                    label, clean = _mitigation_label(m)
                    if label != "Mitigation":
                        lines.append(f"- [{label[0]}] {clean}")
                    else:
                        lines.append(f"- {clean}")
                lines.append("")

            # Attack tree (Mermaid graph)
            tid = str(t.get("id") or "")
            if attack_trees and tid in attack_trees:
                tree = attack_trees[tid]
                mermaid_src = (tree.get("mermaid_source") or "").strip()
                if mermaid_src:
                    lines.append("**Attack Tree:**")
                    lines.append("")
                    lines.append("```mermaid")
                    lines.append(mermaid_src)
                    lines.append("```")
                    lines.append("")

            # Test cases (Gherkin)
            if test_suites and tid in test_suites:
                suite = test_suites[tid]
                gherkin_src = (suite.get("gherkin_source") or "").strip()
                if gherkin_src:
                    lines.append("**Test Cases:**")
                    lines.append("")
                    lines.append("```gherkin")
                    lines.append(gherkin_src)
                    lines.append("```")
                    lines.append("")

            global_idx += 1

    return "\n".join(lines)


def _category_from_row(row: dict[str, Any]) -> str:
    """Return the threat category from a DB row or model_dump dict."""
    return row.get("stride_category") or row.get("maestro_category") or "Unknown"


def _group_by_category(
    threats: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group threats by category, preserving first-seen order."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for t in threats:
        cat = _category_from_row(t)
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(t)
    return grouped


def _dread_score_cell(row: dict[str, Any]) -> str:
    """Return DREAD score string for the summary table cell, or '—' if absent."""
    score = _extract_dread_score(row)
    if score is None:
        return "—"
    return f"**{score:.1f}**"


def _dread_display(row: dict[str, Any]) -> str | None:
    """Return full DREAD line for threat detail section, or None if absent.

    Handles two input shapes:
    - Flat DB rows: row["dread_score"], row["dread_damage"], row["dread_reproducibility"], ...
    - Nested model_dump: row["dread"]["damage"], ... (no "score" key — it's a @property)
    """
    score = _extract_dread_score(row)
    if score is None:
        return None

    # Determine per-dimension values from whichever shape is present
    if row.get("dread_score") is not None:
        d = row.get("dread_damage")
        r = row.get("dread_reproducibility")
        e = row.get("dread_exploitability")
        a = row.get("dread_affected_users")
        di = row.get("dread_discoverability")
    else:
        dread_dict = row.get("dread") or {}
        d = dread_dict.get("damage")
        r = dread_dict.get("reproducibility")
        e = dread_dict.get("exploitability")
        a = dread_dict.get("affected_users")
        di = dread_dict.get("discoverability")

    if all(v is not None for v in [d, r, e, a, di]):
        return f"**DREAD:** {score:.1f}/10 *(D:{d} R:{r} E:{e} A:{a} Di:{di})*"
    return f"**DREAD:** {score:.1f}/10"


def _extract_dread_score(row: dict[str, Any]) -> float | None:
    """Extract DREAD composite score from either flat or nested dict shape.

    Flat DB row: uses the pre-computed dread_score column.
    Nested model_dump: computes average from the 5 dimension fields.
    The nested shape has no "score" key because DreadScore.score is a @property.
    """
    # Flat DB row shape
    if row.get("dread_score") is not None:
        return float(row["dread_score"])

    # Nested model_dump shape (no "score" key)
    dread = row.get("dread")
    if isinstance(dread, dict) and dread:
        try:
            return sum(dread.values()) / 5.0
        except (TypeError, ZeroDivisionError):
            return None

    return None


def _mitigation_label(m: str) -> tuple[str, str]:
    """Parse [P]/[D]/[C] mitigation tag. Returns (label, clean_text)."""
    if m.startswith("[P]"):
        return "Preventive", m[3:].strip()
    if m.startswith("[D]"):
        return "Detective", m[3:].strip()
    if m.startswith("[C]"):
        return "Containment", m[3:].strip()
    return "Mitigation", m.strip()
