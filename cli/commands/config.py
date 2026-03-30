"""Config command - interactive setup wizard and configuration display.

Provides commands to initialize and view CLI configuration.
"""

import click

from cli.context import (
    CONFIG_FILE,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_CONFIG,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OPENAI_MODEL,
    config_exists,
    load_config,
    save_config,
)
from cli.errors import CLIError


@click.group()
def config() -> None:
    """Manage CLI configuration.

    Configure LLM providers, API keys, and default settings.

    Examples:

        \\b
        # Interactive setup wizard
        paranoid config init

        \\b
        # Display current configuration
        paranoid config show
    """
    pass


@config.command()
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing configuration",
)
def init(force: bool) -> None:
    """Interactive setup wizard for CLI configuration.

    Prompts for provider selection, API keys, model names, and default settings.
    Creates configuration file at ~/.paranoid/config.json.

    Examples:

        \\b
        # First-time setup
        paranoid config init

        \\b
        # Reconfigure (overwrite existing)
        paranoid config init --force
    """
    try:
        # Check if config exists
        if config_exists() and not force:
            click.echo()
            click.secho("Configuration already exists", fg="yellow")
            click.echo(f"Config file: {CONFIG_FILE}")
            click.echo()
            click.echo("To reconfigure, use:")
            click.echo("  paranoid config init --force")
            click.echo()
            click.echo("To view current configuration:")
            click.echo("  paranoid config show")
            click.echo()
            return

        # Load existing config or use defaults
        if config_exists():
            config = load_config()
        else:
            config = DEFAULT_CONFIG.copy()

        # Welcome message
        click.echo()
        click.secho("Paranoid CLI Configuration Wizard", fg="cyan", bold=True)
        click.secho("=" * 80, fg="white")
        click.echo()

        # Provider selection
        click.echo("Select your default LLM provider:")
        click.echo("  1. Anthropic (Claude)")
        click.echo("  2. OpenAI (GPT-4)")
        click.echo("  3. Ollama (Local)")
        click.echo()

        provider_choice = click.prompt(
            "Choose provider",
            type=click.Choice(["1", "2", "3"]),
            default="1",
        )

        provider_map = {
            "1": "anthropic",
            "2": "openai",
            "3": "ollama",
        }
        provider = provider_map[provider_choice]
        config["default_provider"] = provider

        click.echo()

        # Provider-specific configuration
        if provider == "anthropic":
            click.secho("Anthropic Configuration", fg="cyan", bold=True)
            click.echo("Get your API key at: https://console.anthropic.com/settings/keys")
            click.echo()

            api_key = click.prompt(
                "Anthropic API key",
                type=str,
                default=config["providers"]["anthropic"].get("api_key") or "",
                hide_input=True,
            )
            config["providers"]["anthropic"]["api_key"] = api_key

            model = click.prompt(
                "Model name",
                type=str,
                default=config["providers"]["anthropic"].get("model") or DEFAULT_ANTHROPIC_MODEL,
            )
            config["providers"]["anthropic"]["model"] = model
            config["default_model"] = model

        elif provider == "openai":
            click.secho("OpenAI Configuration", fg="cyan", bold=True)
            click.echo("Get your API key at: https://platform.openai.com/api-keys")
            click.echo()

            api_key = click.prompt(
                "OpenAI API key",
                type=str,
                default=config["providers"]["openai"].get("api_key") or "",
                hide_input=True,
            )
            config["providers"]["openai"]["api_key"] = api_key

            model = click.prompt(
                "Model name",
                type=str,
                default=config["providers"]["openai"].get("model") or DEFAULT_OPENAI_MODEL,
            )
            config["providers"]["openai"]["model"] = model
            config["default_model"] = model

        elif provider == "ollama":
            click.secho("Ollama Configuration", fg="cyan", bold=True)
            click.echo("Make sure Ollama is running locally")
            click.echo()

            base_url = click.prompt(
                "Ollama base URL",
                type=str,
                default=config["providers"]["ollama"].get("base_url") or "http://localhost:11434",
            )
            config["providers"]["ollama"]["base_url"] = base_url

            model = click.prompt(
                "Model name",
                type=str,
                default=config["providers"]["ollama"].get("model") or DEFAULT_OLLAMA_MODEL,
            )
            config["providers"]["ollama"]["model"] = model
            config["default_model"] = model

        click.echo()

        # Default iterations
        iterations = click.prompt(
            "Default iterations (1-15)",
            type=click.IntRange(1, 15),
            default=config.get("default_iterations", 3),
        )
        config["default_iterations"] = iterations

        # Save configuration
        save_config(config)

        # Success message
        click.echo()
        click.secho("=" * 80, fg="white")
        click.secho("✓ Configuration saved successfully", fg="green", bold=True)
        click.echo(f"Config file: {CONFIG_FILE}")
        click.echo()
        click.echo("You can now run threat modeling:")
        click.echo("  paranoid run system.md")
        click.echo()
        click.echo("To view your configuration:")
        click.echo("  paranoid config show")
        click.echo()

    except CLIError as e:
        click.echo()
        click.secho(f"✗ Error: {e.message}", fg="red", err=True)
        click.echo()
        raise SystemExit(e.exit_code) from e
    except KeyboardInterrupt:
        click.echo()
        click.secho("✗ Configuration cancelled", fg="yellow")
        raise SystemExit(130) from None
    except Exception as e:
        click.echo()
        click.secho(f"✗ Unexpected error: {e}", fg="red", err=True)
        raise SystemExit(1) from e


@config.command()
def show() -> None:
    """Display current configuration.

    Shows configured providers, API keys (masked), models, and default settings.

    Examples:

        \\b
        paranoid config show
    """
    try:
        if not config_exists():
            click.echo()
            click.secho("No configuration found", fg="yellow")
            click.echo(f"Config file: {CONFIG_FILE}")
            click.echo()
            click.echo("Run the setup wizard to configure:")
            click.echo("  paranoid config init")
            click.echo()
            return

        config = load_config()

        click.echo()
        click.secho("Paranoid CLI Configuration", fg="cyan", bold=True)
        click.secho("=" * 80, fg="white")
        click.echo()

        # General settings
        click.secho("General Settings:", fg="cyan")
        click.echo(f"  Version:          {config.get('version', 'unknown')}")
        click.echo(f"  Default Provider: {config.get('default_provider', 'not set')}")
        click.echo(f"  Default Model:    {config.get('default_model', 'not set')}")
        click.echo(f"  Default Iterations: {config.get('default_iterations', 'not set')}")
        click.echo()

        # Provider configurations
        click.secho("Provider Configurations:", fg="cyan")

        providers = config.get("providers", {})

        # Anthropic
        if "anthropic" in providers:
            click.echo()
            click.secho("  Anthropic:", fg="white", bold=True)
            api_key = providers["anthropic"].get("api_key")
            if api_key:
                masked_key = f"{api_key[:7]}...{api_key[-4:]}" if len(api_key) > 11 else "***"
            else:
                masked_key = "not set"
            click.echo(f"    API Key: {masked_key}")
            click.echo(f"    Model:   {providers['anthropic'].get('model', 'not set')}")

        # OpenAI
        if "openai" in providers:
            click.echo()
            click.secho("  OpenAI:", fg="white", bold=True)
            api_key = providers["openai"].get("api_key")
            if api_key:
                masked_key = f"{api_key[:7]}...{api_key[-4:]}" if len(api_key) > 11 else "***"
            else:
                masked_key = "not set"
            click.echo(f"    API Key: {masked_key}")
            click.echo(f"    Model:   {providers['openai'].get('model', 'not set')}")

        # Ollama
        if "ollama" in providers:
            click.echo()
            click.secho("  Ollama:", fg="white", bold=True)
            click.echo(f"    Base URL: {providers['ollama'].get('base_url', 'not set')}")
            click.echo(f"    Model:    {providers['ollama'].get('model', 'not set')}")

        click.echo()
        click.secho("=" * 80, fg="white")
        click.echo(f"Config file: {CONFIG_FILE}")
        click.echo()
        click.echo("To reconfigure:")
        click.echo("  paranoid config init --force")
        click.echo()

    except CLIError as e:
        click.echo()
        click.secho(f"✗ Error: {e.message}", fg="red", err=True)
        click.echo()
        raise SystemExit(e.exit_code) from e
    except Exception as e:
        click.echo()
        click.secho(f"✗ Unexpected error: {e}", fg="red", err=True)
        raise SystemExit(1) from e
