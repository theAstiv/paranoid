"""Integrity checks for all seed JSON files.

Validates that every seed file:
  - Parses as valid JSON
  - Every entry has all required fields (name, stride_category, description,
    target, impact, likelihood, mitigations)
  - Every stride_category is a valid StrideCategory enum value
  - Every maestro_category (if present) is a value in the expected set
  - mitigations is a non-empty list
  - No duplicate names within the same file

Run with: pytest tests/test_seeds_integrity.py -v
"""

import json
from pathlib import Path

import pytest

from backend.models.enums import MaestroCategory, StrideCategory


SEEDS_DIR = Path(__file__).parent.parent / "seeds"

_VALID_STRIDE = {s.value for s in StrideCategory}
_VALID_MAESTRO = {m.value for m in MaestroCategory}
# Fields that must always be present.
# Note: stride_category is NOT in this set because maestro_patterns.json
# contains MAESTRO-only entries that have maestro_category but no stride_category.
# The engine's framework filter handles this correctly. Each entry must have
# at least one of stride_category or maestro_category (checked separately).
_REQUIRED_FIELDS = {"name", "description", "target", "impact", "likelihood", "mitigations"}
_VALID_IMPACT = {"Critical", "High", "Medium", "Low"}
_VALID_LIKELIHOOD = {"High", "Medium", "Low"}


def _load_seed_file(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list), f"{path.name}: root must be a JSON array"
    return data


def seed_files() -> list[Path]:
    return sorted(SEEDS_DIR.glob("*.json"))


@pytest.mark.parametrize("seed_path", seed_files(), ids=lambda p: p.name)
def test_seed_file_parses(seed_path: Path) -> None:
    """Every seed file must be valid JSON."""
    _load_seed_file(seed_path)


@pytest.mark.parametrize("seed_path", seed_files(), ids=lambda p: p.name)
def test_seed_entries_have_required_fields(seed_path: Path) -> None:
    """Every entry must have all required fields and none may be empty strings."""
    patterns = _load_seed_file(seed_path)
    for i, p in enumerate(patterns):
        missing = _REQUIRED_FIELDS - p.keys()
        assert not missing, (
            f"{seed_path.name}[{i}] '{p.get('name', '?')}': missing fields {missing}"
        )

        for field in ("name", "description", "target"):
            assert p[field], f"{seed_path.name}[{i}]: field '{field}' must not be empty"


@pytest.mark.parametrize("seed_path", seed_files(), ids=lambda p: p.name)
def test_seed_has_at_least_one_category(seed_path: Path) -> None:
    """Every entry must have at least stride_category or maestro_category."""
    patterns = _load_seed_file(seed_path)
    for i, p in enumerate(patterns):
        name = p.get("name", "?")
        has_stride = bool(p.get("stride_category"))
        has_maestro = bool(p.get("maestro_category"))
        assert has_stride or has_maestro, (
            f"{seed_path.name}[{i}] '{name}': must have stride_category or maestro_category"
        )


@pytest.mark.parametrize("seed_path", seed_files(), ids=lambda p: p.name)
def test_seed_stride_categories_valid(seed_path: Path) -> None:
    """Every stride_category (when present) must be a valid StrideCategory enum value."""
    patterns = _load_seed_file(seed_path)
    for i, p in enumerate(patterns):
        cat = p.get("stride_category")
        if not cat:
            continue  # MAESTRO-only entries are valid
        assert cat in _VALID_STRIDE, (
            f"{seed_path.name}[{i}] '{p.get('name', '?')}': "
            f"invalid stride_category '{cat}' (valid: {sorted(_VALID_STRIDE)})"
        )


@pytest.mark.parametrize("seed_path", seed_files(), ids=lambda p: p.name)
def test_seed_maestro_categories_valid(seed_path: Path) -> None:
    """Every maestro_category (if present) must be a known MAESTRO category."""
    patterns = _load_seed_file(seed_path)
    for i, p in enumerate(patterns):
        if "maestro_category" not in p:
            continue
        cat = p["maestro_category"]
        assert cat in _VALID_MAESTRO, (
            f"{seed_path.name}[{i}] '{p.get('name', '?')}': "
            f"unknown maestro_category '{cat}' (valid: {sorted(_VALID_MAESTRO)})"
        )


@pytest.mark.parametrize("seed_path", seed_files(), ids=lambda p: p.name)
def test_seed_impact_and_likelihood_valid(seed_path: Path) -> None:
    """impact and likelihood must be within the expected value sets."""
    patterns = _load_seed_file(seed_path)
    for i, p in enumerate(patterns):
        name = p.get("name", "?")
        impact = p.get("impact", "")
        assert impact in _VALID_IMPACT, f"{seed_path.name}[{i}] '{name}': invalid impact '{impact}'"
        likelihood = p.get("likelihood", "")
        assert likelihood in _VALID_LIKELIHOOD, (
            f"{seed_path.name}[{i}] '{name}': invalid likelihood '{likelihood}'"
        )


@pytest.mark.parametrize("seed_path", seed_files(), ids=lambda p: p.name)
def test_seed_mitigations_non_empty(seed_path: Path) -> None:
    """mitigations must be a non-empty list with non-empty strings."""
    patterns = _load_seed_file(seed_path)
    for i, p in enumerate(patterns):
        name = p.get("name", "?")
        mits = p.get("mitigations", [])
        assert isinstance(mits, list), f"{seed_path.name}[{i}] '{name}': mitigations must be a list"
        assert len(mits) > 0, f"{seed_path.name}[{i}] '{name}': mitigations must not be empty"
        for j, m in enumerate(mits):
            assert isinstance(m, str), (
                f"{seed_path.name}[{i}] '{name}': mitigations[{j}] must be a string"
            )
            assert m.strip(), f"{seed_path.name}[{i}] '{name}': mitigations[{j}] must not be blank"


@pytest.mark.parametrize("seed_path", seed_files(), ids=lambda p: p.name)
def test_seed_no_duplicate_names(seed_path: Path) -> None:
    """No two entries in the same file may share a name."""
    patterns = _load_seed_file(seed_path)
    names = [p.get("name", "") for p in patterns]
    seen: set[str] = set()
    dupes: list[str] = []
    for name in names:
        if name in seen:
            dupes.append(name)
        seen.add(name)
    assert not dupes, f"{seed_path.name}: duplicate names found: {dupes}"
