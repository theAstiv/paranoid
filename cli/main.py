"""Paranoid CLI - Main entry point.

Command-line interface for iterative threat modeling powered by LLMs.
"""

import io
import sys

import click

from backend import __version__
from cli.commands.config import config
from cli.commands.deps import deps
from cli.commands.models import models
from cli.commands.run import run
from cli.commands.version import version


@click.group()
@click.version_option(version=__version__, prog_name="paranoid")
def cli() -> None:
    """Paranoid - Open-source iterative threat modeling powered by LLMs.

    Run STRIDE and MAESTRO threat modeling on your system descriptions.
    Supports plain text and structured XML templates.

    \b
    Examples:
      paranoid run system.md                    # Basic usage
      paranoid run api-gateway.md --stride-maestro  # Dual framework
      paranoid models list                      # List saved threat models
      paranoid models show a1b2c3d4             # Show threats for a model
      paranoid config init                      # Setup wizard
      paranoid version                          # Show version info

    \b
    Documentation:
      GitHub: https://github.com/theAstiv/paranoid
      Docs:   https://github.com/theAstiv/paranoid#readme
    """
    pass


# Register commands
cli.add_command(run)
cli.add_command(config)
cli.add_command(deps)
cli.add_command(models)
cli.add_command(version)


def _replace_unencodable_output() -> None:
    """Write `?` for characters the output encoding can't represent instead
    of crashing on them.

    Redirected or piped output on Windows uses the ANSI code page (cp1252),
    which has no ✓/✗/→/⚠. click.echo would raise UnicodeEncodeError after the
    command's work was already done and report it as an "Unexpected error".
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")


def main() -> None:
    """Entry point for CLI (called by pyproject.toml script)."""
    _replace_unencodable_output()
    cli()


if __name__ == "__main__":
    main()
