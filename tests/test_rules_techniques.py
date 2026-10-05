"""Tests for backend.rules.techniques: deterministic ATT&CK/ATLAS matching.

Three layers, mirroring backend/rules/techniques.py's three sources:
- the generated catalog files (seeds/techniques/*.json) are well-formed
- dependency-sourced threats resolve via the fixed rule_id table
- rule-engine-sourced threats resolve via the parenthesized-ID regex
- everything else resolves via embedding similarity (mocked embed_text —
  see tests/conftest.py's mock_technique_embeddings autouse fixture)
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.models.state import DependencyRef, Threat
from backend.rules import techniques


CATALOG_DIR = Path(__file__).parent.parent / "seeds" / "techniques"


def _threat(**overrides) -> Threat:
    defaults = {
        "name": "Some LLM-authored threat",
        "stride_category": "Tampering",
        "description": "x " * 40,
        "target": "A service",
        "impact": "High",
        "likelihood": "Medium",
        "mitigations": ["mitigate one", "mitigate two"],
    }
    defaults.update(overrides)
    return Threat(**defaults)


@pytest.fixture(autouse=True)
def _clear_catalog_cache():
    """lru_cache-backed catalog loaders must not leak state between tests."""
    techniques._load_catalog.cache_clear()
    techniques._catalog_by_id.cache_clear()
    techniques._embedded_catalog.cache_clear()
    yield
    techniques._load_catalog.cache_clear()
    techniques._catalog_by_id.cache_clear()
    techniques._embedded_catalog.cache_clear()


class TestCatalogFiles:
    def test_catalog_files_exist(self):
        for name in techniques._CATALOG_FILES:
            assert (CATALOG_DIR / name).exists(), f"missing {name}"

    def test_every_entry_has_required_fields(self):
        for name in techniques._CATALOG_FILES:
            payload = json.loads((CATALOG_DIR / name).read_text(encoding="utf-8"))
            assert "techniques" in payload
            for tech in payload["techniques"]:
                assert tech["id"]
                assert tech["name"]
                assert isinstance(tech["tactics"], list)
                assert "url" in tech

    def test_dependency_rule_technique_ids_resolve_in_catalog(self):
        """Every ID backend.deps.threats' rule_ids map to must exist in the
        generated catalog — scripts/build_techniques.py's explicit-include
        list is exactly what guarantees this."""
        by_id = techniques._catalog_by_id()
        for entries in techniques.DEPENDENCY_RULE_TECHNIQUES.values():
            for tech_id, _confidence in entries:
                assert tech_id in by_id, f"{tech_id} missing from catalog"


class TestDependencyTechniqueMapping:
    """Deterministic table lookup — no embedding call."""

    def test_drift_signal_maps_to_supply_chain_compromise(self):
        threat = _threat(
            source="dependency",
            dependency_ref=DependencyRef(
                package="evil-pkg", version="1.0.0", rule_id="drift_signal"
            ),
        )
        result = techniques.match_techniques(threat)
        assert [t.id for t in result] == ["T1195.002"]

    def test_install_hook_added_maps_to_command_and_scripting_interpreter(self):
        threat = _threat(
            source="dependency",
            dependency_ref=DependencyRef(
                package="evil-pkg", version="1.0.0", rule_id="install_hook_added"
            ),
        )
        result = techniques.match_techniques(threat)
        assert [t.id for t in result] == ["T1059"]

    def test_unknown_rule_id_returns_empty(self):
        threat = _threat(
            source="dependency",
            dependency_ref=DependencyRef(
                package="evil-pkg", version="1.0.0", rule_id="not_a_real_rule"
            ),
        )
        assert techniques.match_techniques(threat) == []

    def test_dependency_threat_with_no_dependency_ref_returns_empty(self):
        threat = _threat(source="dependency", dependency_ref=None)
        assert techniques.match_techniques(threat) == []


class TestRuleEngineTechniqueExtraction:
    """Seed-pattern-derived threats carry the ID in their name."""

    def test_extracts_attack_id_from_name(self):
        threat = _threat(
            source="rule_engine",
            name="Cloud Account Takeover via Stolen or Leaked Credentials (T1078.004)",
        )
        # T1078.004 may not be in the generated catalog slice (platform
        # filter); assert on the regex extraction behavior via a guaranteed
        # in-catalog id instead.
        threat.name = "Compromise Software Supply Chain (T1195.002)"
        result = techniques.match_techniques(threat)
        assert [t.id for t in result] == ["T1195.002"]

    def test_extracts_atlas_id_from_name(self):
        by_id = techniques._catalog_by_id()
        atlas_id = next(iter(tid for tid in by_id if tid.startswith("AML.")))
        threat = _threat(source="rule_engine", name=f"Some ATLAS pattern ({atlas_id})")
        result = techniques.match_techniques(threat)
        assert [t.id for t in result] == [atlas_id]

    def test_falls_back_to_embedding_when_no_id_in_name(self):
        threat = _threat(source="rule_engine", name="A generic seed pattern with no ID")
        # Should not raise, and should go through the embedding path
        # (mocked in conftest) rather than returning early.
        result = techniques.match_techniques(threat)
        assert isinstance(result, list)

    def test_unresolvable_id_in_name_falls_back_to_embedding(self):
        threat = _threat(source="rule_engine", name="Retired technique (T9999.999)")
        result = techniques.match_techniques(threat)
        assert isinstance(result, list)


class TestEmbeddingMatch:
    """LLM/seeded-sourced threats use the tactic prior + cosine similarity."""

    def test_returns_at_most_top_k(self):
        threat = _threat(source="llm")
        result = techniques.match_techniques(threat)
        assert len(result) <= techniques.TOP_K

    def test_all_results_above_min_confidence(self):
        threat = _threat(source="llm")
        result = techniques.match_techniques(threat)
        assert all(t.confidence >= techniques.MIN_CONFIDENCE for t in result)

    def test_tactic_prior_narrows_candidates(self):
        """A STRIDE category with a narrow prior should not rank candidates
        whose tactics never intersect it, when a same-score alternative with
        a matching tactic exists — verified indirectly via the prior lookup
        itself rather than exact output (embeddings are mocked/meaningless)."""
        threat = _threat(stride_category="Denial of Service")
        prior = techniques._tactic_prior(threat)
        assert prior == ["Impact"]

    def test_embed_failure_degrades_to_empty_list(self):
        threat = _threat(source="llm")
        with patch("backend.rules.techniques.embed_text", side_effect=ValueError("boom")):
            assert techniques.match_techniques(threat) == []

    def test_missing_catalog_degrades_to_empty_list(self, tmp_path):
        with patch("backend.rules.techniques._CATALOG_DIR", tmp_path):
            techniques._load_catalog.cache_clear()
            techniques._embedded_catalog.cache_clear()
            threat = _threat(source="llm")
            assert techniques.match_techniques(threat) == []


class TestEmbeddingModelMismatch:
    """A catalog file's precomputed vectors are only trusted when its
    recorded embedding_model matches the currently configured one — a
    silent mismatch would otherwise crash cosine_similarity (different
    dimension) or produce meaningless matches with no warning (same
    dimension, different model)."""

    def _write_catalog(self, tmp_path: Path, embedding_model: str) -> None:
        payload = {
            "embedding_model": embedding_model,
            "embedding_dim": 3,
            "techniques": [
                {
                    "id": "T0001",
                    "name": "Fake Technique",
                    "tactics": ["Impact"],
                    "description": "A fake technique for testing.",
                    "url": "https://example.invalid/T0001",
                    "embedding": [1.0, 0.0, 0.0],
                }
            ],
        }
        (tmp_path / "attack_enterprise.json").write_text(json.dumps(payload), encoding="utf-8")
        (tmp_path / "atlas.json").write_text(json.dumps({"techniques": []}), encoding="utf-8")

    def test_matching_model_uses_precomputed_vector_without_embedding(self, tmp_path):
        self._write_catalog(tmp_path, "BAAI/bge-small-en-v1.5")
        with (
            patch("backend.rules.techniques._CATALOG_DIR", tmp_path),
            patch("backend.rules.techniques.settings.embedding_model", "BAAI/bge-small-en-v1.5"),
            patch("backend.rules.techniques.embed_text") as mock_embed,
        ):
            techniques._load_catalog.cache_clear()
            techniques._embedded_catalog.cache_clear()
            embedded = techniques._embedded_catalog()
            assert embedded[0][1] == (1.0, 0.0, 0.0)
            mock_embed.assert_not_called()

    def test_mismatched_model_recomputes_instead_of_using_stale_vector(self, tmp_path, caplog):
        caplog.set_level("WARNING", logger="backend.rules.techniques")
        self._write_catalog(tmp_path, "some-other-model")
        with (
            patch("backend.rules.techniques._CATALOG_DIR", tmp_path),
            patch("backend.rules.techniques.settings.embedding_model", "BAAI/bge-small-en-v1.5"),
            patch(
                "backend.rules.techniques.embed_text", return_value=[0.0, 1.0, 0.0]
            ) as mock_embed,
        ):
            techniques._load_catalog.cache_clear()
            techniques._embedded_catalog.cache_clear()
            embedded = techniques._embedded_catalog()
            # Recomputed, not the stale [1.0, 0.0, 0.0] from the mismatched file —
            # and not silently dropped either (the entry is still present).
            assert len(embedded) == 1
            assert embedded[0][1] == (0.0, 1.0, 0.0)
            mock_embed.assert_called_once()
        assert "some-other-model" in caplog.text
        assert "recomputing" in caplog.text.lower()
