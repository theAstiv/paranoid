"""Match a fresh extraction against the context rows the user kept.

Re-extract deletes the pipeline's assets, flows and trust boundaries but keeps
the rows a user edited or added (user_edited = 1), then saves the new
extraction. Without a check, the extractor re-emits what the user already
corrected: rename "DB" to "Postgres" and the model ends up with both.

Each pipeline row records the identity it was generated with (generated_key,
migration 0016): an asset's name, a flow's or boundary's "source → target".
A new row is a duplicate when its identity matches a kept row's current
identity or its generated_key. Flow and boundary endpoints are first rewritten
through the kept assets' renames, so "API → DB" becomes "API → Postgres".

Pure functions over row dicts; the callers do the DB work.
"""

from typing import Any


def normalize_key(text: str | None) -> str:
    """Case- and whitespace-insensitive form of an identity key."""
    return " ".join((text or "").split()).casefold()


def endpoint_key(source: str, target: str) -> str:
    """The identity of a flow or trust boundary, as stored in generated_key."""
    return f"{source} → {target}"


def kept_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows a user edited or added, which Re-extract keeps."""
    return [r for r in rows if r.get("user_edited")]


def asset_renames(assets: list[dict[str, Any]]) -> dict[str, str]:
    """Generated name → current name, for kept assets the user renamed."""
    renames: dict[str, str] = {}
    for asset in kept_rows(assets):
        generated = asset.get("generated_key")
        if generated and normalize_key(generated) != normalize_key(asset["name"]):
            renames[normalize_key(generated)] = asset["name"]
    return renames


def rename_endpoint(name: str, renames: dict[str, str]) -> str:
    return renames.get(normalize_key(name), name)


def _known_keys(rows: list[dict[str, Any]], current_key: str) -> set[str]:
    keys: set[str] = set()
    for row in kept_rows(rows):
        keys.add(normalize_key(row[current_key]))
        if row.get("generated_key"):
            keys.add(normalize_key(row["generated_key"]))
    return keys


def kept_asset_keys(assets: list[dict[str, Any]]) -> set[str]:
    return _known_keys(assets, "name")


def kept_endpoint_keys(rows: list[dict[str, Any]]) -> set[str]:
    """Identities of kept flows or boundaries (current and as generated)."""
    with_current = [
        {**r, "_key": endpoint_key(r["source_entity"], r["target_entity"])} for r in rows
    ]
    return _known_keys(with_current, "_key")
