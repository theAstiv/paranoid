"""Tests for the pure entity-text -> asset resolver (component IDs, B1)."""

import pytest

from backend.pipeline.nodes.entities import normalize_name, resolve_asset, resolve_asset_with_tier


ASSETS = [
    ("a-redis", "Redis job queue"),
    ("a-worker", "Resize worker"),
    ("a-store", "Object Store"),
    ("a-api", "API Gateway"),
    ("a-db", "PostgreSQL Database"),
    ("a-user", "End User"),
]


# --- tier 1: exact ---------------------------------------------------------


def test_exact_match_ignores_case_and_whitespace():
    assert resolve_asset("  api   GATEWAY ", ASSETS) == "a-api"


def test_exact_match_reports_tier_one():
    assert resolve_asset_with_tier("End User", ASSETS) == ("a-user", 1)


# --- tier 2: normalised ----------------------------------------------------


def test_parenthesised_suffix_is_ignored():
    assert resolve_asset("PostgreSQL Database (primary)", ASSETS) == "a-db"


def test_punctuation_and_filler_words_are_ignored():
    assets = [("a-auth", "Auth"), ("a-db", "Postgres")]
    assert resolve_asset("Auth Service", assets) == "a-auth"
    assert resolve_asset("Postgres container", assets) == "a-db"


def test_normalised_match_reports_tier_two():
    assert resolve_asset_with_tier("PostgreSQL Database (primary)", ASSETS) == ("a-db", 2)


def test_normalize_name_keeps_text_when_only_filler_remains():
    assert normalize_name("Service") == "service"


# --- tier 3: contained name ------------------------------------------------


def test_p12_style_description_resolves_to_leading_entity():
    text = "Object Store (S3-compatible) / thumbnails bucket. Data: raw image bytes"
    assert resolve_asset_with_tier(text, ASSETS) == ("a-store", 3)


def test_earliest_mention_wins_over_longer_later_mention():
    text = "Redis job queue -> Resize worker. Sensitive data: job payload. Criticality: Medium"
    assert resolve_asset(text, ASSETS) == "a-redis"


def test_longer_name_wins_when_both_start_at_the_same_place():
    assets = [("a-api", "API"), ("a-gw", "API Gateway")]
    assert resolve_asset("API Gateway terminates TLS", assets) == "a-gw"


def test_contained_name_needs_word_boundaries():
    assets = [("a-auth", "Auth")]
    assert resolve_asset("OAuth provider", assets) is None


def test_short_single_word_names_are_not_matched_by_containment():
    assets = [("a-db", "DB"), ("a-user", "User"), ("a-api", "API")]
    assert resolve_asset("DB credentials stored in the vault", assets) is None
    assert resolve_asset("Admin user session tokens", assets) is None
    assert resolve_asset("Public API docs", assets) is None


def test_known_leftover_single_word_names_of_five_or_more_characters_still_match():
    # Documented limit: a specific-looking single word inside a sentence can win.
    assert resolve_asset("Admin user session tokens", [("a1", "Admin")]) == "a1"


def test_asset_name_longer_than_the_text_is_not_matched():
    # "Intent Classifier" does not resolve to "Intent Classifier Model": tiers 1-3 look for
    # an asset name inside the text, and tier 4 only accepts the text as the *tail* of a name
    # (a prefix such as this names something else more often than not).
    assert resolve_asset("Intent Classifier", [("a1", "Intent Classifier Model")]) is None


def test_short_names_still_match_exactly():
    assert resolve_asset("User", [("a-user", "User")]) == "a-user"


def test_two_word_short_names_count_as_specific():
    assert resolve_asset("calls the S3 API often", [("a1", "S3 API")]) == "a1"


def test_generic_short_name_does_not_beat_the_real_target_in_a_threat_sentence():
    assets = [("a-user", "User"), ("a-db", "Database")]
    text = "Attacker impersonating user to reach Database"
    assert resolve_asset(text, assets) == "a-db"


def test_composite_target_resolves_to_the_leading_entity():
    assets = [("a-ui", "Admin UI"), ("a-keys", "Partner API Keys")]
    assert resolve_asset("Admin UI / Partner API Keys", assets) == "a-ui"


# --- tier 4: the text is the tail of an asset name ---------------------------
# Diagram-label shorthand drops the leading modifiers of the extracted name.


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("API container", "Express API container"),
        ("Worker container", "Resize worker container"),
        ("Redis", "Session Memory - Redis"),
        ("API container", "Express API (API container)"),
        ("pgvector", "Policy RAG Vector Database - pgvector"),
    ],
)
def test_text_that_is_the_tail_of_one_asset_name_resolves_at_tier_four(text, name):
    assets = [("a-target", name), ("a-other", "Admin Console"), ("a-db", "PostgreSQL Database")]
    assert resolve_asset_with_tier(text, assets) == ("a-target", 4)


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Admin", "Admin Credentials"),
        ("User", "User Profile Database"),
        ("Client", "Client Secret"),
        ("Redis", "Redis job queue"),
    ],
)
def test_text_that_is_the_start_of_an_asset_name_does_not_resolve(text, name):
    assert resolve_asset_with_tier(text, [("a1", name)]) == (None, 0)


def test_two_assets_with_the_same_tail_stay_unlinked():
    assets = [("a1", "Express API container"), ("a2", "Admin API container")]
    assert resolve_asset_with_tier("API container", assets) == (None, 0)


@pytest.mark.parametrize("text", ["container", "service", "The Container", "server component"])
def test_filler_only_text_never_resolves_by_tail(text):
    assets = [("a1", "Express API container"), ("a2", "Billing service component")]
    assert resolve_asset_with_tier(text, assets) == (None, 0)


def test_tail_match_is_not_used_when_an_earlier_tier_matches():
    assets = [("a1", "Express API container"), ("a2", "API container")]
    assert resolve_asset_with_tier("API container", assets) == ("a2", 1)


def test_tail_match_needs_whole_words():
    assert resolve_asset_with_tier("PI container", [("a1", "Express API container")]) == (None, 0)


# --- ambiguity and misses --------------------------------------------------


def test_duplicate_asset_names_are_ambiguous():
    assets = [("a1", "Web App"), ("a2", "web app")]
    assert resolve_asset("Web App", assets) is None


def test_two_assets_tied_at_the_same_position_are_ambiguous():
    assets = [("a1", "Gateway (public)"), ("a2", "Gateway (private)")]
    assert resolve_asset("Gateway", assets) is None


def test_two_assets_sharing_only_a_word_do_not_match():
    assets = [("a1", "Public API"), ("a2", "Internal API")]
    assert resolve_asset("API", assets) is None


@pytest.mark.parametrize("text", ["", "   ", "Unknown Thing", "Kubernetes cluster"])
def test_no_match_returns_none(text):
    assert resolve_asset_with_tier(text, ASSETS) == (None, 0)


def test_no_assets_returns_none():
    assert resolve_asset("API Gateway", []) is None


def test_asset_with_blank_name_is_skipped():
    assert resolve_asset("API Gateway", [("x", ""), ("a-api", "API Gateway")]) == "a-api"
