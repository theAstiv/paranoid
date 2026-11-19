"""Generate a Mermaid flowchart from a model's assets, flows and trust boundaries.

Used by the Markdown and PDF exports (BB-69) and, in Phase 2 B2, by Review
Context's diagram tab. Deterministic: the same context always gives the same
text, byte for byte, so two exports of a model diff cleanly.

A trust boundary in this codebase is a *pair* (source_entity, target_entity,
purpose): a crossing between two components, not a set of components inside
it. Mermaid places a node in at most one subgraph, so overlapping pairs can't
be drawn as subgraphs; each boundary is a dotted, labelled link between its
two ends instead, coloured apart from the data flows.
"""

from typing import Any

from backend.export._common import mermaid_label


# Amber, like the UI's warning colour; dashed so it never reads as a flow.
_BOUNDARY_LINK_STYLE = "stroke:#d97706,stroke-width:2px,stroke-dasharray:5 4"
_NODE_LABEL_MAX = 60
_EDGE_LABEL_MAX = 50


def _key(name: str | None) -> str:
    """Case- and whitespace-insensitive identity for an entity name."""
    return " ".join(str(name or "").split()).casefold()


def context_to_mermaid(
    assets: list[dict[str, Any]] | None,
    flows: list[dict[str, Any]] | None,
    trust_boundaries: list[dict[str, Any]] | None,
) -> str:
    """Return Mermaid ``flowchart LR`` source for the context, or "" if there is none.

    Nodes are the assets (``Entity`` rows as rounded stadiums) plus any flow or
    boundary endpoint that names no asset. An endpoint is matched to an asset
    by its ``*_asset_id`` link first (migration 0013), then by name ignoring
    case and spacing. Nodes, flows and boundaries are each sorted, and
    duplicates (same ends, same label) are drawn once.
    """
    assets = assets or []
    flows = flows or []
    trust_boundaries = trust_boundaries or []

    labels: dict[str, str] = {}  # key -> display name (first spelling seen)
    entity_keys: set[str] = set()
    key_by_asset_id: dict[str, str] = {}

    for asset in sorted(assets, key=lambda a: (_key(a.get("name")), str(a.get("name") or ""))):
        key = _key(asset.get("name"))
        if not key:
            continue
        labels.setdefault(key, " ".join(str(asset["name"]).split()))
        if str(asset.get("type") or "").casefold() == "entity":
            entity_keys.add(key)
        if asset.get("id"):
            key_by_asset_id[str(asset["id"])] = key

    def endpoint(name: str | None, asset_id: str | None) -> str | None:
        if asset_id and str(asset_id) in key_by_asset_id:
            return key_by_asset_id[str(asset_id)]
        key = _key(name)
        if not key:
            return None
        labels.setdefault(key, " ".join(str(name).split()))
        return key

    edges: set[tuple[str, str, str]] = set()
    for flow in flows:
        source = endpoint(flow.get("source_entity"), flow.get("source_asset_id"))
        target = endpoint(flow.get("target_entity"), flow.get("target_asset_id"))
        if source and target:
            edges.add(
                (source, target, mermaid_label(flow.get("flow_description") or "", _EDGE_LABEL_MAX))
            )

    crossings: set[tuple[str, str, str]] = set()
    for boundary in trust_boundaries:
        ends = [
            endpoint(boundary.get("source_entity"), boundary.get("source_asset_id")),
            endpoint(boundary.get("target_entity"), boundary.get("target_asset_id")),
        ]
        if not all(ends):
            continue
        low, high = sorted(ends)  # a crossing has no direction
        purpose = " ".join(str(boundary.get("purpose") or "").split())
        crossings.add((low, high, mermaid_label(purpose or "Trust boundary", _EDGE_LABEL_MAX)))

    if not labels:
        return ""

    node_ids = {key: f"n{i}" for i, key in enumerate(sorted(labels), 1)}
    lines = ["flowchart LR"]
    for key in sorted(labels):
        label = mermaid_label(labels[key], _NODE_LABEL_MAX)
        shape = f'(["{label}"])' if key in entity_keys else f'["{label}"]'
        lines.append(f"    {node_ids[key]}{shape}")

    for source, target, label in sorted(edges):
        arrow = f'-->|"{label}"|' if label else "-->"
        lines.append(f"    {node_ids[source]} {arrow} {node_ids[target]}")

    for low, high, label in sorted(crossings):
        lines.append(f'    {node_ids[low]} -.-|"{label}"| {node_ids[high]}')

    if crossings:
        # linkStyle counts links in the order they were written: flows come first.
        first = len(edges)
        indices = ",".join(str(i) for i in range(first, first + len(crossings)))
        lines.append(f"    linkStyle {indices} {_BOUNDARY_LINK_STYLE}")

    return "\n".join(lines) + "\n"
