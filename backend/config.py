"""Application configuration using pydantic-settings."""

from typing import Literal

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


# Global settings instance
settings = Settings()

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
