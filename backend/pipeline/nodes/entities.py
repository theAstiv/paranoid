"""Resolve free-text entity names (flow endpoints, threat targets) to asset IDs.

Pure functions, no IO. Extraction output stays free text; links are derived
afterwards so a model can't forge or break them. Unresolved beats guessed:
any tie at the winning tier returns None.

Tiers, first hit wins:
  1. exact match, ignoring case and whitespace
  2. normalised match (parenthesised suffixes, punctuation and filler words dropped)
  3. an asset name contained in the text on word boundaries. Only specific
     names count (5+ characters or two+ words), so "User" or "API" inside a
     sentence can't win. The earliest mention wins, then the longest, so
     "Redis job queue -> Resize worker. ..." and composite threat targets such
     as "Admin UI / Partner API Keys" resolve to the leading entity (name length
     says nothing about which of two listed entities is the target)
"""

import re
from collections.abc import Sequence


_PARENTHESISED_RE = re.compile(r"\([^)]*\)")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_FILLER_WORDS = frozenset({"the", "service", "container", "server", "component"})
_MIN_CONTAINED_LENGTH = 5

type AssetRef = tuple[str, str]


def _collapse(text: str) -> str:
    return " ".join(text.lower().split())


def _words(text: str) -> str:
    return " ".join(_NON_ALNUM_RE.sub(" ", text.lower()).split())


def normalize_name(text: str) -> str:
    """Lowercase; drop parenthesised suffixes, punctuation and filler words.

    Falls back to the punctuation-stripped text when only filler remains, so
    an asset literally named "Service" still has a usable key.
    """
    words = _words(_PARENTHESISED_RE.sub(" ", text))
    kept = " ".join(w for w in words.split() if w not in _FILLER_WORDS)
    return kept or words


def _unique(matches: list[str]) -> tuple[str | None, bool]:
    """Return (id, True) for exactly one distinct match; (None, True) if ambiguous."""
    distinct = set(matches)
    if len(distinct) == 1:
        return matches[0], True
    return None, bool(distinct)


def _specific_enough(needle: str) -> bool:
    return len(needle) >= _MIN_CONTAINED_LENGTH or len(needle.split()) >= 2


def _contained(text: str, assets: Sequence[AssetRef]) -> str | None:
    haystack = _words(text)
    best: tuple[int, int] | None = None
    best_ids: set[str] = set()
    for asset_id, name in assets:
        needle = _words(name)
        if not needle or not _specific_enough(needle):
            continue
        match = re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack)
        if match is None:
            continue
        key = (match.start(), -len(needle))
        if best is None or key < best:
            best, best_ids = key, {asset_id}
        elif key == best:
            best_ids.add(asset_id)
    return next(iter(best_ids)) if len(best_ids) == 1 else None


def resolve_asset_with_tier(text: str, assets: Sequence[AssetRef]) -> tuple[str | None, int]:
    """Resolve text to an asset ID. Returns (asset_id, tier); (None, 0) if unresolved."""
    if not text or not text.strip():
        return None, 0
    named = [(asset_id, name) for asset_id, name in assets if name and name.strip()]

    key = _collapse(text)
    found, decided = _unique([a for a, n in named if _collapse(n) == key])
    if decided:
        return (found, 1) if found else (None, 0)

    norm = normalize_name(text)
    if norm:
        found, decided = _unique([a for a, n in named if normalize_name(n) == norm])
        if decided:
            return (found, 2) if found else (None, 0)

    found = _contained(text, named)
    return (found, 3) if found else (None, 0)


def resolve_asset(text: str, assets: Sequence[AssetRef]) -> str | None:
    """Resolve text to an asset ID, or None when unresolved or ambiguous."""
    return resolve_asset_with_tier(text, assets)[0]
