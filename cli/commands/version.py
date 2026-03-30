"""Version command - show version and dependency information."""

import sys
from importlib import metadata

import click

from cli.context import config_exists, load_config


@click.command()
def version() -> None:
    """Show version, Python version, and dependency information.

    Displays:
      - Paranoid CLI version
      - Python version
      - Key dependency versions
      - Current configuration (if available)

    Examples:

        \b
        # Show version information
        paranoid version
    """
    try:
        # Get package version
        try:
            pkg_version = metadata.version("paranoid")
        except metadata.PackageNotFoundError:
            pkg_version = "dev (not installed)"

        # Get Python version
        python_version = (
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )

        # Get key dependency versions
        dependencies = {}
        for pkg in ["anthropic", "openai", "click", "pydantic", "httpx"]:
            try:
                dependencies[pkg] = metadata.version(pkg)
            except metadata.PackageNotFoundError:
                dependencies[pkg] = "not installed"

        # Display version information
        click.echo()
        click.secho("Paranoid Threat Modeling CLI", fg="cyan", bold=True)
        click.echo(f"Version:       {pkg_version}")
        click.echo(f"Python:        {python_version}")
        click.echo()

        click.secho("Dependencies:", fg="cyan", bold=True)
        for pkg, ver in dependencies.items():
            click.echo(f"  {pkg:<12} {ver}")
        click.echo()

        # Show current configuration if available
        if config_exists():
            try:
                config = load_config()
                click.secho("Configuration:", fg="cyan", bold=True)
                click.echo(f"  Provider:    {config.get('default_provider', 'not set')}")
                click.echo(f"  Model:       {config.get('default_model', 'not set')}")
                click.echo(f"  Iterations:  {config.get('default_iterations', 'not set')}")
                click.echo()
            except Exception:
                # Config file exists but couldn't be loaded
                pass
        else:
            click.secho("Configuration:", fg="cyan", bold=True)
            click.echo("  Not configured. Run 'paranoid config init' to set up.")
            click.echo()

    except Exception as e:
        click.secho(f"Error displaying version info: {e}", fg="red", err=True)
        raise SystemExit(1) from e
