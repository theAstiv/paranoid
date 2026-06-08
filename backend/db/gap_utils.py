"""Shared helpers for the gap_summaries column on threat_models.

``gap_summaries`` is stored as a JSON-encoded list[str] — one entry per
pipeline iteration.  Centralising the decode here removes the two identical
private functions that were duplicated in backend/routes/models.py and
backend/routes/export.py.
"""

import json


def decode_gap_summaries(raw: str | None) -> list[str]:
    """Decode the threat_model.gap_summaries column into a list of strings.

    Returns an empty list when the column is NULL, empty, or not parseable —
    the frontend treats a missing list and an empty list identically.
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(g) for g in parsed] if isinstance(parsed, list) else []
