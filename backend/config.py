"""Application configuration using pydantic-settings."""

import sys
from typing import Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM Provider settings
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://host.docker.internal:11434"
    default_provider: Literal["anthropic", "openai", "ollama"] = "anthropic"
    default_model: str = "claude-sonnet-4-20250514"
    # Fast model is used for cheaper extraction steps (assets/flows) and
    # enrichment (attack trees / test cases).  Only applies when
    # default_provider == 'anthropic'.  Set FAST_MODEL="" to disable.
    fast_model: str = "claude-haiku-4-5-20251001"
    default_iterations: int = 3

    # Embedding settings
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    # Database settings
    db_path: str = "./data/paranoid.db"

    # MCP settings
    context_link_binary: str = (
        ""  # Empty = auto-detect; set CONTEXT_LINK_BINARY env var to override
    )

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    cors_origins: str = "*"  # Comma-separated origins, or "*" for all

    # Prompt configuration
    summary_max_words: int = 40
    threat_description_min_words: int = 35
    threat_description_max_words: int = 50
    mitigation_min_items: int = 2
    mitigation_max_items: int = 5

    # Pipeline configuration
    max_iteration_count: int = 15
    min_iteration_count: int = 1
    # gt=0: timeout=0 would make _check_time_limit() fire immediately on the
    # first call, aborting every pipeline run before any threat is generated.
    pipeline_timeout_minutes: int = Field(default=30, gt=0)
    # ge/le bounds match the strictest provider: Anthropic caps at 1.0.
    # Values above 1.0 cause an Anthropic API 400 that manifests as a silent
    # rule-engine-only fallback with no indication the config is to blame.
    default_temperature: float = Field(default=0.2, ge=0.0, le=1.0)

    # Rule engine / RAG
    # gt=0: rag_top_k=0 → scored[:0]=[] → rule engine always returns empty,
    # neutering the deterministic safety net with no visible warning.
    rag_top_k: int = Field(default=10, gt=0)

    # Deduplication threshold for rule engine
    similarity_threshold: float = 0.85

    # Optional shared secret for PATCH /config.  When set, callers must
    # supply a matching X-Config-Secret header.  Empty string = no auth
    # required (default; safe for local / Docker single-user deployments).
    config_secret: str = ""

    # CSRF allowlist — comma-separated concrete origins (no "*").  Applied
    # only to non-GET requests that carry an Origin / Referer header; calls
    # without either (CLI, server-to-server) pass through unconditionally.
    # Empty string disables CSRF protection entirely — documented escape
    # hatch for CLI-only setups.
    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    # Git host allowlist for code sources. The built-in set covers
    # github.com, gitlab.com, and bitbucket.org. Additional exact hostnames
    # (no wildcards, no subdomain matching) can be appended here.
    # Example: ADDITIONAL_GIT_HOSTS=git.company.com,git.internal.net
    additional_git_hosts: str = ""


# Global settings instance.
# Wrap Settings() so that an invalid env var produces a readable startup error
# instead of a raw Pydantic ValidationError traceback that buries the field
# path in JSON.  sys.exit(1) is intentional — a misconfigured container should
# fail fast rather than run in a half-broken state.
try:
    settings = Settings()
except ValidationError as _exc:
    _lines = ["[paranoid] Invalid configuration — fix the following env vars and restart:"]
    for _err in _exc.errors():
        _field = " → ".join(str(loc) for loc in _err["loc"])
        _lines.append(f"  {_field}: {_err['msg']}")
    print("\n".join(_lines), file=sys.stderr)
    sys.exit(1)

# Single source of truth for the application version.
# Keep in sync with pyproject.toml when bumping releases.
VERSION = "1.5.0"


# Provider → (env var name, settings attribute / config-table DB key).
# The settings attribute and DB key share the same string by convention;
# the tuple guards against future divergence (e.g. vendor renames).
# Imported by backend.routes.config and backend.main (lifespan hydration)
# so both read the same authoritative mapping.
API_KEY_FIELDS: dict[str, tuple[str, str]] = {
    "anthropic": ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    "openai": ("OPENAI_API_KEY", "openai_api_key"),
}
