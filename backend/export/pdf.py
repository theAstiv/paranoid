"""PDF export for human-readable threat model documents.

Produces a structured PDF suitable for sharing, archiving, and security review sign-off.
Uses reportlab platypus for layout — no external binaries required.
"""

from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def export_pdf(
    threats: list[dict[str, Any]],
    model_id: str,
    framework: str,
    title: str | None = None,
    source_file: str | None = None,
    assets: list[dict[str, Any]] | None = None,
    flows: list[dict[str, Any]] | None = None,
    trust_boundaries: list[dict[str, Any]] | None = None,
    attack_trees: dict[str, dict[str, Any]] | None = None,
    test_suites: dict[str, dict[str, Any]] | None = None,
) -> bytes:
    """Export threats to PDF format.

    Args:
        threats: List of threat dicts. Accepts both DB row shape (flat DREAD fields:
                 dread_score, dread_damage, ...) and model_dump() shape (nested dread dict).
        model_id: Unique identifier for this threat model run.
        framework: Framework used (STRIDE or MAESTRO).
        title: Optional display title. Falls back to model_id[:8].
        source_file: Optional path to the analyzed input file.
        assets: Optional list of asset dicts from the DB.
        flows: Optional list of data flow dicts from the DB.
        trust_boundaries: Optional list of trust boundary dicts from the DB.
        attack_trees: Optional mapping of threat_id -> AttackTree.model_dump().
        test_suites: Optional mapping of threat_id -> TestSuite.model_dump().

    Returns:
        PDF content as bytes, ready to write to a .pdf file.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
    )

    styles = _build_styles()
    story: list[Any] = []

    display_title = title or model_id[:8]
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    # --- Header ---
    story.append(Paragraph(f"Threat Model: {display_title}", styles["h1"]))
    story.append(Spacer(1, 4))

    meta_parts = [
        f"<b>Framework:</b> {framework}",
        f"<b>Model ID:</b> {model_id[:8]}",
        f"<b>Generated:</b> {generated_at}",
    ]
    if source_file:
        meta_parts.append(f"<b>Source:</b> {source_file}")
    story.append(Paragraph("&nbsp;&nbsp;|&nbsp;&nbsp;".join(meta_parts), styles["meta"]))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#374151")))
    story.append(Spacer(1, 12))

    # --- Assets ---
    if assets:
        story.append(Paragraph("Assets", styles["h2"]))
        story.append(Spacer(1, 6))
        story.append(_build_assets_table(assets))
        story.append(Spacer(1, 14))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#9ca3af")))
        story.append(Spacer(1, 10))

    # --- Data Flows ---
    if flows:
        story.append(Paragraph("Data Flows", styles["h2"]))
        story.append(Spacer(1, 6))
        story.append(_build_flows_table(flows))
        story.append(Spacer(1, 14))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#9ca3af")))
        story.append(Spacer(1, 10))

    # --- Trust Boundaries ---
    if trust_boundaries:
        story.append(Paragraph("Trust Boundaries", styles["h2"]))
        story.append(Spacer(1, 6))
        story.append(_build_trust_boundaries_table(trust_boundaries))
        story.append(Spacer(1, 14))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#9ca3af")))
        story.append(Spacer(1, 10))

    # --- Summary table ---
    story.append(Paragraph("Summary", styles["h2"]))
    story.append(Spacer(1, 6))
    story.append(_build_summary_table(threats, styles))
    story.append(Spacer(1, 18))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#9ca3af")))
    story.append(Spacer(1, 12))

    # --- Threat details by category ---
    story.append(Paragraph("Threats", styles["h2"]))
    story.append(Spacer(1, 8))

    if not threats:
        story.append(Paragraph("No threats recorded.", styles["body"]))
    else:
        grouped = _group_by_category(threats)
        global_idx = 1
        for category, category_threats in grouped.items():
            story.append(Paragraph(category, styles["h3"]))
            story.append(Spacer(1, 4))
            for t in category_threats:
                tid = str(t.get("id") or "")
                tree = attack_trees.get(tid) if attack_trees else None
                suite = test_suites.get(tid) if test_suites else None
                story.extend(
                    _threat_flowables(t, global_idx, styles, attack_tree=tree, test_suite=suite)
                )
                global_idx += 1
            story.append(Spacer(1, 6))

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TABLE_STYLE_BASE = [
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, 0), 8),
    ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
    ("TOPPADDING", (0, 0), (-1, 0), 6),
    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
    ("FONTSIZE", (0, 1), (-1, -1), 8),
    ("TOPPADDING", (0, 1), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
]


def _build_assets_table(assets: list[dict[str, Any]]) -> Table:
    rows = [["Name", "Type", "Description"]]
    for a in assets:
        rows.append(
            [
                a.get("name") or "—",
                a.get("type") or "—",
                a.get("description") or "—",
            ]
        )
    col_widths = [1.5 * inch, 1.2 * inch, 3.6 * inch]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(_TABLE_STYLE_BASE))
    return table


def _build_flows_table(flows: list[dict[str, Any]]) -> Table:
    rows = [["Source", "Target", "Type", "Description"]]
    for f in flows:
        rows.append(
            [
                f.get("source_entity") or "—",
                f.get("target_entity") or "—",
                f.get("flow_type") or "—",
                f.get("flow_description") or "—",
            ]
        )
    col_widths = [1.4 * inch, 1.4 * inch, 1.0 * inch, 2.5 * inch]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(_TABLE_STYLE_BASE))
    return table


def _build_trust_boundaries_table(trust_boundaries: list[dict[str, Any]]) -> Table:
    rows = [["Source", "Target", "Purpose"]]
    for tb in trust_boundaries:
        rows.append(
            [
                tb.get("source_entity") or "—",
                tb.get("target_entity") or "—",
                tb.get("purpose") or "—",
            ]
        )
    col_widths = [1.6 * inch, 1.6 * inch, 3.1 * inch]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(_TABLE_STYLE_BASE))
    return table


def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()

    h1 = ParagraphStyle(
        "h1",
        parent=base["Normal"],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#111827"),
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    h2 = ParagraphStyle(
        "h2",
        parent=base["Normal"],
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#1f2937"),
        spaceBefore=6,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    h3 = ParagraphStyle(
        "h3",
        parent=base["Normal"],
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#374151"),
        spaceBefore=8,
        spaceAfter=2,
        fontName="Helvetica-Bold",
    )
    h4 = ParagraphStyle(
        "h4",
        parent=base["Normal"],
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#111827"),
        spaceBefore=6,
        spaceAfter=2,
        fontName="Helvetica-Bold",
    )
    body = ParagraphStyle(
        "body",
        parent=base["Normal"],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#374151"),
    )
    meta = ParagraphStyle(
        "meta",
        parent=base["Normal"],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#6b7280"),
    )
    quote = ParagraphStyle(
        "quote",
        parent=base["Normal"],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#4b5563"),
        leftIndent=12,
        borderPad=4,
    )
    mitigation = ParagraphStyle(
        "mitigation",
        parent=base["Normal"],
        fontSize=8,
        leading=12,
        textColor=colors.HexColor("#374151"),
        leftIndent=16,
        spaceAfter=1,
    )

    return {
        "h1": h1,
        "h2": h2,
        "h3": h3,
        "h4": h4,
        "body": body,
        "meta": meta,
        "quote": quote,
        "mitigation": mitigation,
    }


def _build_summary_table(threats: list[dict[str, Any]], styles: dict[str, ParagraphStyle]) -> Table:
    header = ["#", "Threat", "Category", "Target", "Likelihood", "DREAD"]
    rows = [header]

    for i, t in enumerate(threats, 1):
        dread = _extract_dread_score(t)
        rows.append(
            [
                str(i),
                t.get("name") or "—",
                _category_from_row(t),
                t.get("target") or "—",
                t.get("likelihood") or "—",
                f"{dread:.1f}" if dread is not None else "—",
            ]
        )

    col_widths = [0.3 * inch, 2.0 * inch, 1.2 * inch, 1.2 * inch, 0.9 * inch, 0.7 * inch]

    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                # Header row
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("TOPPADDING", (0, 0), (-1, 0), 6),
                # Data rows
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("TOPPADDING", (0, 1), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
                # Grid
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def _threat_flowables(
    t: dict[str, Any],
    idx: int,
    styles: dict[str, ParagraphStyle],
    attack_tree: dict[str, Any] | None = None,
    test_suite: dict[str, Any] | None = None,
) -> list[Any]:
    parts: list[Any] = []

    name = t.get("name") or "unnamed"
    target = t.get("target") or "—"
    likelihood = t.get("likelihood") or "—"
    impact = t.get("impact") or "—"
    description = (t.get("description") or "").strip()

    parts.append(Paragraph(f"{idx}. {name}", styles["h4"]))

    meta_line = f"<b>Target:</b> {target}&nbsp;&nbsp;|&nbsp;&nbsp;<b>Likelihood:</b> {likelihood}&nbsp;&nbsp;|&nbsp;&nbsp;<b>Impact:</b> {impact}"
    dread_line = _dread_display(t)
    if dread_line:
        meta_line += f"&nbsp;&nbsp;|&nbsp;&nbsp;{dread_line}"
    parts.append(Paragraph(meta_line, styles["body"]))

    if description:
        parts.append(Spacer(1, 3))
        parts.append(Paragraph(description, styles["quote"]))

    mitigations = t.get("mitigations") or []
    if mitigations:
        parts.append(Spacer(1, 3))
        parts.append(Paragraph("<b>Mitigations:</b>", styles["body"]))
        for m in mitigations:
            label, clean = _mitigation_label(m)
            if label != "Mitigation":
                parts.append(Paragraph(f"[{label[0]}] {clean}", styles["mitigation"]))
            else:
                parts.append(Paragraph(clean, styles["mitigation"]))

    # Attack tree (Mermaid source shown as preformatted text; PDF has no native Mermaid renderer)
    if attack_tree:
        mermaid_src = (attack_tree.get("mermaid_source") or "").strip()
        if mermaid_src:
            parts.append(Spacer(1, 4))
            parts.append(Paragraph("<b>Attack Tree (Mermaid):</b>", styles["body"]))
            # Render each line as a small monospaced paragraph
            for line in mermaid_src.splitlines():
                parts.append(
                    Paragraph(
                        line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        or "&nbsp;",
                        styles["mitigation"],
                    )
                )

    # Test cases (Gherkin source)
    if test_suite:
        gherkin_src = (test_suite.get("gherkin_source") or "").strip()
        if gherkin_src:
            parts.append(Spacer(1, 4))
            parts.append(Paragraph("<b>Test Cases (Gherkin):</b>", styles["body"]))
            for line in gherkin_src.splitlines():
                parts.append(
                    Paragraph(
                        line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        or "&nbsp;",
                        styles["mitigation"],
                    )
                )

    parts.append(Spacer(1, 6))
    return parts


def _category_from_row(row: dict[str, Any]) -> str:
    return row.get("stride_category") or row.get("maestro_category") or "Unknown"


def _group_by_category(
    threats: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for t in threats:
        cat = _category_from_row(t)
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(t)
    return grouped


def _extract_dread_score(row: dict[str, Any]) -> float | None:
    if row.get("dread_score") is not None:
        return float(row["dread_score"])
    dread = row.get("dread")
    if isinstance(dread, dict) and dread:
        try:
            return sum(dread.values()) / 5.0
        except (TypeError, ZeroDivisionError):
            return None
    return None


def _dread_display(row: dict[str, Any]) -> str | None:
    score = _extract_dread_score(row)
    if score is None:
        return None

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
        return f"<b>DREAD:</b> {score:.1f}/10 (D:{d} R:{r} E:{e} A:{a} Di:{di})"
    return f"<b>DREAD:</b> {score:.1f}/10"


def _mitigation_label(m: str) -> tuple[str, str]:
    if m.startswith("[P]"):
        return "Preventive", m[3:].strip()
    if m.startswith("[D]"):
        return "Detective", m[3:].strip()
    if m.startswith("[C]"):
        return "Containment", m[3:].strip()
    return "Mitigation", m.strip()
