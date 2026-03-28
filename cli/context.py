"""Configuration file management for CLI.

Loads and saves configuration to ~/.paranoid/config.json with secure permissions.
"""

import json
import os
from pathlib import Path
from typing import Any

from cli.errors import ConfigurationError


# Configuration file location
CONFIG_DIR = Path.home() / ".paranoid"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Default model names — single source of truth for the CLI layer
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
DEFAULT_OPENAI_MODEL = "gpt-4"
DEFAULT_OLLAMA_MODEL = "llama3"

# Default configuration
DEFAULT_CONFIG = {
    "version": "1.0.0",
    "default_provider": "anthropic",
    "default_model": DEFAULT_ANTHROPIC_MODEL,
    "default_iterations": 3,
    "providers": {
        "anthropic": {"api_key": None, "model": DEFAULT_ANTHROPIC_MODEL},
        "openai": {"api_key": None, "model": DEFAULT_OPENAI_MODEL},
        "ollama": {"base_url": "http://localhost:11434", "model": DEFAULT_OLLAMA_MODEL},
    },
}


def load_config() -> dict[str, Any]:
    """Load configuration from file.

    Returns:
        Configuration dictionary

    Raises:
        ConfigurationError: If config file exists but is invalid
    """
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()

    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            config = json.load(f)

        # Validate version
        if "version" not in config:
            raise ConfigurationError(
                "Invalid configuration file: missing version field\\n\\n"
                f"Config file: {CONFIG_FILE}\\n\\n"
                "Run the setup wizard to recreate:\\n"
                "  paranoid config init"
            )

        return config

    except json.JSONDecodeError as e:
        raise ConfigurationError(
            f"Failed to parse configuration file\\n\\n"
            f"Config file: {CONFIG_FILE}\\n"
            f"Error: {e}\\n\\n"
            "Run the setup wizard to recreate:\\n"
            "  paranoid config init"
        ) from e
    except Exception as e:
        raise ConfigurationError(
            f"Failed to load configuration file\\n\\n"
            f"Config file: {CONFIG_FILE}\\n"
            f"Error: {e}"
        ) from e


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to file with secure permissions.

    Args:
        config: Configuration dictionary to save

    Raises:
        ConfigurationError: If save fails
    """
    try:
        # Create config directory if it doesn't exist
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Write config file
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        # Set secure permissions (user read/write only)
        # On Windows, this is less relevant, but we still set it
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except (OSError, NotImplementedError):
            # Windows may not support chmod - that's OK
            pass

    except Exception as e:
        raise ConfigurationError(
            f"Failed to save configuration file\\n\\n"
            f"Config file: {CONFIG_FILE}\\n"
            f"Error: {e}"
        ) from e


def get_provider_config(provider: str) -> dict[str, Any]:
    """Get configuration for a specific provider.

    Args:
        provider: Provider name (anthropic, openai, ollama)

    Returns:
        Provider configuration dictionary

    Raises:
        ConfigurationError: If provider not configured
    """
    config = load_config()

    if provider not in config.get("providers", {}):
        raise ConfigurationError(
            f"Provider '{provider}' not configured\\n\\n"
            f"Run the setup wizard to configure:\\n"
            f"  paranoid config init"
        )

    return config["providers"][provider]


def update_provider_config(provider: str, **kwargs: Any) -> None:
    """Update configuration for a specific provider.

    Args:
        provider: Provider name
        **kwargs: Configuration values to update

    Raises:
        ConfigurationError: If update fails
    """
    config = load_config()

    if "providers" not in config:
        config["providers"] = {}

    if provider not in config["providers"]:
        config["providers"][provider] = {}

    config["providers"][provider].update(kwargs)
    save_config(config)


def config_exists() -> bool:
    """Check if configuration file exists.

    Returns:
        True if config file exists, False otherwise
    """
    return CONFIG_FILE.exists()
