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
    default_iterations: int = 3

    # Embedding settings
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    # Database settings
    db_path: str = "./data/paranoid.db"

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: Literal["debug", "info", "warning", "error"] = "info"

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


# Global settings instance
settings = Settings()
