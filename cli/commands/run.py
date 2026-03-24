"""Run command - execute threat modeling pipeline.

Main CLI command that runs the threat modeling pipeline on an input file.
"""

import asyncio
import os
from pathlib import Path

import click

from backend.config import Settings
from backend.models.enums import Framework
from backend.pipeline.runner import PipelineEvent, PipelineStep, run_pipeline_for_model
from backend.providers import create_provider
from cli.context import config_exists, load_config
from cli.errors import CLIError, ConfigurationError, InputFileError, PipelineExecutionError
from cli.input.file_loader import load_input_file
from cli.output.console import ConsoleRenderer


def _load_merged_settings() -> Settings:
    """Load configuration from .env and config file with proper precedence.

    Precedence: Environment variables > Config file > Defaults

    Returns:
        Settings object with merged configuration

    Raises:
        ConfigurationError: If no valid configuration found
    """
    # Try loading from .env (uses environment variables)
    try:
        settings = Settings()
    except Exception:
        # .env doesn't exist or is invalid, create empty settings
        settings = None

    # If .env doesn't provide API key, try config file
    if config_exists():
        config = load_config()

        # Create settings from config file if .env failed
        if settings is None:
            # Build environment dict from config file
            provider = config.get("default_provider", "anthropic")
            model = config.get("default_model", "claude-sonnet-4-20250514")
            iterations = config.get("default_iterations", 3)

            # Get provider-specific config
            provider_config = config.get("providers", {}).get(provider, {})

            # Set environment variables temporarily for Settings initialization
            env_updates = {
                "DEFAULT_PROVIDER": provider,
                "DEFAULT_MODEL": model,
                "DEFAULT_ITERATIONS": str(iterations),
            }

            if provider == "anthropic" and provider_config.get("api_key"):
                env_updates["ANTHROPIC_API_KEY"] = provider_config["api_key"]
            elif provider == "openai" and provider_config.get("api_key"):
                env_updates["OPENAI_API_KEY"] = provider_config["api_key"]
            elif provider == "ollama" and provider_config.get("base_url"):
                env_updates["OLLAMA_BASE_URL"] = provider_config["base_url"]

            # Update environment and create settings
            original_env = {}
            for key, value in env_updates.items():
                original_env[key] = os.environ.get(key)
                os.environ[key] = value

            try:
                settings = Settings()
            finally:
                # Restore original environment
                for key, value in original_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

        # If .env exists but doesn't have API key, supplement from config file
        elif settings:
            provider = settings.default_provider
            provider_config = config.get("providers", {}).get(provider, {})

            # Supplement missing API keys from config file
            if provider == "anthropic" and not settings.anthropic_api_key:
                if provider_config.get("api_key"):
                    # Create new settings with supplemented API key
                    os.environ["ANTHROPIC_API_KEY"] = provider_config["api_key"]
                    settings = Settings()
            elif provider == "openai" and not settings.openai_api_key:
                if provider_config.get("api_key"):
                    os.environ["OPENAI_API_KEY"] = provider_config["api_key"]
                    settings = Settings()
            elif provider == "ollama" and not settings.ollama_base_url:
                if provider_config.get("base_url"):
                    os.environ["OLLAMA_BASE_URL"] = provider_config["base_url"]
                    settings = Settings()

    # Validate we have settings
    if settings is None:
        raise ConfigurationError(
            "No configuration found\n\n"
            "Run the setup wizard to configure:\n"
            "  paranoid config init\n\n"
            "Or create a .env file with:\n"
            "  ANTHROPIC_API_KEY=sk-ant-xxx\n"
            "  DEFAULT_PROVIDER=anthropic\n"
            "  DEFAULT_MODEL=claude-sonnet-4-20250514"
        )

    # Validate API key is present for the selected provider
    if settings.default_provider == "anthropic" and not settings.anthropic_api_key:
        raise ConfigurationError(
            "Anthropic API key not configured\n\n"
            "Run the setup wizard:\n"
            "  paranoid config init\n\n"
            "Or set ANTHROPIC_API_KEY in your .env file:\n"
            "  ANTHROPIC_API_KEY=sk-ant-xxx\n\n"
            "Get an API key at: https://console.anthropic.com/settings/keys"
        )
    elif settings.default_provider == "openai" and not settings.openai_api_key:
        raise ConfigurationError(
            "OpenAI API key not configured\n\n"
            "Run the setup wizard:\n"
            "  paranoid config init\n\n"
            "Or set OPENAI_API_KEY in your .env file:\n"
            "  OPENAI_API_KEY=sk-xxx\n\n"
            "Get an API key at: https://platform.openai.com/api-keys"
        )

    return settings


@click.command()
@click.argument("input_file", type=click.Path(exists=True, path_type=Path))
def run(input_file: Path) -> None:
    """Execute threat modeling on INPUT_FILE.

    INPUT_FILE: Path to .txt or .md file with system description

    Examples:

        \b
        # Basic usage
        paranoid run system.md

        \b
        # With structured template
        paranoid run examples/stride-example-api-gateway.md
    """
    try:
        # Initialize console renderer
        renderer = ConsoleRenderer(verbose=False)

        # Load configuration from .env and config file
        # Precedence: Environment variables > Config file > Defaults
        settings = _load_merged_settings()

        # Load input file
        try:
            description = load_input_file(input_file)
        except InputFileError:
            raise  # Re-raise with original message
        except Exception as e:
            raise InputFileError(f"Failed to load input file: {e}") from e

        # Create provider
        try:
            provider = create_provider(
                provider_type=settings.default_provider,
                model=settings.default_model,
                api_key=(
                    settings.anthropic_api_key
                    if settings.default_provider == "anthropic"
                    else settings.openai_api_key
                    if settings.default_provider == "openai"
                    else None
                ),
                base_url=(
                    settings.ollama_base_url if settings.default_provider == "ollama" else None
                ),
            )
        except Exception as e:
            raise ConfigurationError(f"Failed to initialize LLM provider: {e}") from e

        # Show configuration
        click.echo()
        click.secho("Configuration:", fg="cyan", bold=True)
        click.echo(f"  Provider: {settings.default_provider}")
        click.echo(f"  Model: {settings.default_model}")
        click.echo(f"  Iterations: {settings.default_iterations}")
        click.echo(f"  Input: {input_file.name}")
        click.echo()

        # Generate model ID
        from datetime import datetime

        model_id = f"{input_file.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Run pipeline (async)
        asyncio.run(
            _run_pipeline_async(
                model_id=model_id,
                description=description,
                settings=settings,
                provider=provider,
                renderer=renderer,
                input_file=input_file,
            )
        )

    except CLIError as e:
        # Known CLI errors - show message and exit with code
        click.echo()
        click.secho(f"✗ Error: {e.message}", fg="red", err=True)
        click.echo()
        raise SystemExit(e.exit_code) from e
    except KeyboardInterrupt:
        click.echo()
        click.secho("✗ Interrupted by user", fg="yellow")
        raise SystemExit(130) from None
    except Exception as e:
        # Unexpected errors - show full traceback in development
        click.echo()
        click.secho(f"✗ Unexpected error: {e}", fg="red", err=True)
        import traceback

        traceback.print_exc()
        raise SystemExit(1) from e


async def _run_pipeline_async(
    model_id: str,
    description: str,
    settings: Settings,
    provider,
    renderer: ConsoleRenderer,
    input_file: Path,
) -> None:
    """Run pipeline asynchronously and render events.

    Args:
        model_id: Unique model identifier
        description: System description
        settings: Application settings
        provider: LLM provider instance
        renderer: Console renderer
        input_file: Input file path
    """
    # Track results
    total_threats = 0
    iterations_completed = 0
    start_time = asyncio.get_event_loop().time()

    try:
        # Run pipeline
        async for event in run_pipeline_for_model(
            model_id=model_id,
            description=description,
            framework=Framework.STRIDE,  # Default to STRIDE for Phase 1
            provider=provider,
            max_iterations=settings.default_iterations,
        ):
            # Render event
            renderer.render_event(event)

            # Track threat generation events
            if event.step == PipelineStep.GENERATE_THREATS and event.status == "completed":
                if event.data and "threat_count" in event.data:
                    # Accumulate threats from each iteration
                    total_threats += event.data["threat_count"]

            # Track iteration completion
            if event.step == PipelineStep.GAP_ANALYSIS and event.status == "completed":
                if event.iteration:
                    iterations_completed = event.iteration

            # Track final completion
            if event.step == PipelineStep.COMPLETE and event.status == "completed":
                # Extract final stats from event data if available
                if event.data:
                    if "total_threats" in event.data:
                        total_threats = event.data["total_threats"]
                    if "iterations_completed" in event.data:
                        iterations_completed = event.data["iterations_completed"]

    except Exception as e:
        raise PipelineExecutionError(
            f"Pipeline execution failed: {e}\n\n"
            f"This may be due to:\n"
            f"  - LLM API timeout or rate limit\n"
            f"  - Invalid API key\n"
            f"  - Network connectivity issues\n\n"
            f"Check your API key and try again."
        ) from e

    # Calculate duration
    duration = asyncio.get_event_loop().time() - start_time

    # Render final summary
    renderer.render_final_summary(
        total_threats=total_threats,
        iterations=iterations_completed,
        duration=duration,
        output_file=None,  # No JSON export in Phase 1
    )
