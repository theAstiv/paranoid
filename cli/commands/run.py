"""Run command - execute threat modeling pipeline.

Main CLI command that runs the threat modeling pipeline on an input file.
"""

import asyncio
from pathlib import Path

import click

from backend.config import Settings
from backend.models.enums import Framework
from backend.pipeline.runner import PipelineEvent, PipelineStep, run_pipeline_for_model
from backend.providers import create_provider
from cli.context import config_exists, load_config
from cli.errors import CLIError, ConfigurationError, InputFileError, PipelineExecutionError
from cli.input.file_loader import detect_framework_from_input, load_input_file, parse_structured_input
from cli.output.console import ConsoleRenderer
from cli.output.json_writer import JSONWriter, get_default_output_path


def _load_merged_settings() -> Settings:
    """Load configuration with proper precedence, no environment mutation.

    Precedence (highest to lowest):
    1. Environment variables (os.environ)
    2. .env file (read by pydantic-settings)
    3. Config file (~/.paranoid/config.toml) — supplements missing values
    4. Field defaults

    Returns:
        Settings object with merged configuration

    Raises:
        ConfigurationError: If no valid configuration found
    """
    # First pass: load from env vars + .env file (no config file)
    try:
        base_settings = Settings()
    except Exception:
        base_settings = None

    # Second pass: supplement gaps from config file
    if config_exists():
        config = load_config()
        supplement = _get_config_supplement(base_settings, config)

        if supplement:
            try:
                base_settings = Settings(**supplement)
            except Exception:
                raise ConfigurationError(
                    "Invalid configuration\n\n"
                    "Check your config file and .env for conflicting values.\n"
                    "Run 'paranoid config init' to reconfigure."
                )

    if base_settings is None:
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
    if base_settings.default_provider == "anthropic" and not base_settings.anthropic_api_key:
        raise ConfigurationError(
            "Anthropic API key not configured\n\n"
            "Run the setup wizard:\n"
            "  paranoid config init\n\n"
            "Or set ANTHROPIC_API_KEY in your .env file:\n"
            "  ANTHROPIC_API_KEY=sk-ant-xxx\n\n"
            "Get an API key at: https://console.anthropic.com/settings/keys"
        )
    elif base_settings.default_provider == "openai" and not base_settings.openai_api_key:
        raise ConfigurationError(
            "OpenAI API key not configured\n\n"
            "Run the setup wizard:\n"
            "  paranoid config init\n\n"
            "Or set OPENAI_API_KEY in your .env file:\n"
            "  OPENAI_API_KEY=sk-xxx\n\n"
            "Get an API key at: https://platform.openai.com/api-keys"
        )

    return base_settings


def _get_config_supplement(
    base_settings: Settings | None,
    config: dict,
) -> dict:
    """Extract config file values that should supplement (not override) base settings.

    Only includes values for fields that are empty or at default in base_settings.
    When base_settings is None (.env failed), includes all config file values.

    Args:
        base_settings: Settings from env vars + .env, or None if loading failed
        config: Parsed config file dict

    Returns:
        Dict of field values to pass as Settings constructor kwargs
    """
    overrides = {}
    defaults = Settings.model_fields

    # General settings — only supplement if base didn't provide a non-default value
    field_map = {
        "default_provider": "default_provider",
        "default_model": "default_model",
        "default_iterations": "default_iterations",
    }
    for config_key, field_name in field_map.items():
        if config_key not in config:
            continue
        if base_settings is None or getattr(base_settings, field_name) == defaults[field_name].default:
            overrides[field_name] = config[config_key]

    # Provider-specific API keys — only supplement if missing (empty string)
    provider = overrides.get("default_provider") or (
        base_settings.default_provider if base_settings else "anthropic"
    )
    provider_config = config.get("providers", {}).get(provider, {})

    if provider == "anthropic" and provider_config.get("api_key"):
        if base_settings is None or not base_settings.anthropic_api_key:
            overrides["anthropic_api_key"] = provider_config["api_key"]
    elif provider == "openai" and provider_config.get("api_key"):
        if base_settings is None or not base_settings.openai_api_key:
            overrides["openai_api_key"] = provider_config["api_key"]
    elif provider == "ollama" and provider_config.get("base_url"):
        if base_settings is None or base_settings.ollama_base_url == defaults["ollama_base_url"].default:
            overrides["ollama_base_url"] = provider_config["base_url"]

    return overrides


@click.command()
@click.argument("input_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output JSON file path (default: {input_basename}_threats.json)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["simple", "full"], case_sensitive=False),
    default="simple",
    help="JSON output format: simple (lightweight results) or full (complete models + events)",
)
@click.option(
    "--maestro",
    is_flag=True,
    default=False,
    help="Force dual framework execution (STRIDE + MAESTRO in parallel)",
)
@click.option(
    "--iterations",
    "-n",
    type=click.IntRange(1, 15),
    default=None,
    help="Override iteration count (1-15, default from config)",
)
@click.option(
    "--framework",
    type=click.Choice(["STRIDE", "MAESTRO"], case_sensitive=False),
    default=None,
    help="Override framework auto-detection",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    default=False,
    help="Suppress real-time output (only show final summary)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Show detailed event data (assets, flows, gap analysis)",
)
def run(
    input_file: Path,
    output: Path | None,
    output_format: str,
    maestro: bool,
    iterations: int | None,
    framework: str | None,
    quiet: bool,
    verbose: bool,
) -> None:
    """Execute threat modeling on INPUT_FILE.

    INPUT_FILE: Path to .txt or .md file with system description

    Auto-detects framework from XML tags:
      - <component_description> → STRIDE
      - <maestro_component_description> → MAESTRO
      - Plain text → STRIDE (default)

    Examples:

        \b
        # Basic usage (auto-detects framework)
        paranoid run system.md

        \b
        # STRIDE structured template
        paranoid run examples/stride-example-api-gateway.md

        \b
        # MAESTRO structured template
        paranoid run examples/maestro-example-rag-chatbot.md

        \b
        # Force dual framework (STRIDE + MAESTRO)
        paranoid run system.md --maestro

        \b
        # With JSON output
        paranoid run system.md --output threats.json --format full
    """
    try:
        # Initialize console renderer with verbosity settings
        # quiet mode suppresses output, verbose shows detailed data
        renderer = ConsoleRenderer(verbose=verbose)
        if quiet:
            # In quiet mode, we'll skip rendering most events
            renderer = None

        # Load configuration from .env and config file
        # Precedence: Environment variables > Config file > Defaults
        settings = _load_merged_settings()

        # Override iterations if specified
        if iterations is not None:
            settings.default_iterations = iterations

        # Load input file
        try:
            content = load_input_file(input_file)
        except InputFileError:
            raise  # Re-raise with original message
        except Exception as e:
            raise InputFileError(f"Failed to load input file: {e}") from e

        # Detect framework from input (auto-detection)
        detected_framework = detect_framework_from_input(content)

        # Override framework if specified
        if framework is not None:
            detected_framework = Framework.STRIDE if framework.upper() == "STRIDE" else Framework.MAESTRO

        # Parse structured input if present
        description, assumptions = parse_structured_input(content)

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

        # Show configuration (unless quiet mode)
        if not quiet:
            click.echo()
            click.secho("Configuration:", fg="cyan", bold=True)
            click.echo(f"  Provider: {settings.default_provider}")
            click.echo(f"  Model: {settings.default_model}")
            iterations_str = f"{settings.default_iterations}"
            if iterations is not None:
                iterations_str += " (overridden)"
            click.echo(f"  Iterations: {iterations_str}")
            framework_str = detected_framework.value
            if framework is not None:
                framework_str += " (overridden)"
            click.echo(f"  Framework: {framework_str}")
            if maestro:
                click.echo(f"  Mode: Dual framework (STRIDE + MAESTRO)")
            click.echo(f"  Input: {input_file.name}")
            click.echo()

        # Generate model ID
        from datetime import datetime

        model_id = f"{input_file.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Determine output path
        output_path = output if output else get_default_output_path(input_file)

        # Show output configuration (unless quiet mode)
        if output_path and not quiet:
            click.echo(f"  Output: {output_path}")
            click.echo(f"  Format: {output_format}")
            click.echo()

        # Run pipeline (async)
        asyncio.run(
            _run_pipeline_async(
                model_id=model_id,
                description=description,
                assumptions=assumptions,
                framework=detected_framework,
                has_ai_components=maestro,
                settings=settings,
                provider=provider,
                renderer=renderer,
                input_file=input_file,
                output_path=output_path,
                output_format=output_format,
                quiet=quiet,
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
    assumptions: list[str] | None,
    framework: Framework,
    has_ai_components: bool,
    settings: Settings,
    provider,
    renderer: ConsoleRenderer | None,
    input_file: Path,
    output_path: Path | None,
    output_format: str,
    quiet: bool,
) -> None:
    """Run pipeline asynchronously and render events.

    Args:
        model_id: Unique model identifier
        description: System description (formatted from structured template or plain text)
        assumptions: Optional assumptions list from structured template
        framework: Detected framework (STRIDE or MAESTRO)
        has_ai_components: Whether to run dual framework (STRIDE + MAESTRO)
        settings: Application settings
        provider: LLM provider instance
        renderer: Console renderer (None in quiet mode)
        input_file: Input file path
        output_path: JSON output file path (if specified)
        output_format: JSON format (simple or full)
        quiet: Whether to suppress real-time output
    """
    # Track results
    total_threats = 0
    iterations_completed = 0
    start_time = asyncio.get_event_loop().time()

    # Initialize JSON writer if output requested
    json_writer = None
    if output_path:
        json_writer = JSONWriter(
            model_id=model_id,
            input_file=input_file,
            framework=framework,
        )

    try:
        # Run pipeline
        async for event in run_pipeline_for_model(
            model_id=model_id,
            description=description,
            framework=framework,
            provider=provider,
            assumptions=assumptions,
            max_iterations=settings.default_iterations,
            has_ai_components=has_ai_components,
        ):
            # Render event (unless quiet mode)
            if renderer:
                renderer.render_event(event)

            # Add to JSON writer if enabled
            if json_writer:
                json_writer.add_event(event)

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

    # Export JSON if requested
    output_file_str = None
    if json_writer and output_path:
        try:
            if output_format == "simple":
                json_writer.export_simple(output_path)
            else:  # full
                json_writer.export_full(output_path)
            output_file_str = str(output_path)
        except Exception as e:
            # Non-fatal error - show warning but don't fail
            click.echo()
            click.secho(f"⚠ Warning: Failed to write JSON output: {e}", fg="yellow")
            click.echo()

    # Render final summary (always show, even in quiet mode)
    if renderer:
        renderer.render_final_summary(
            total_threats=total_threats,
            iterations=iterations_completed,
            duration=duration,
            output_file=output_file_str,
        )
    elif quiet:
        # In quiet mode, show minimal summary
        click.echo()
        click.secho("THREAT MODEL COMPLETE", fg="green", bold=True)
        click.echo(f"Total Threats:      {total_threats}")
        click.echo(f"Iterations:         {iterations_completed}")
        click.echo(f"Duration:           {duration:.1f} seconds")
        if output_file_str:
            click.echo(f"Output:             {output_file_str}")
        click.echo()
