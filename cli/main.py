"""Paranoid CLI - Main entry point.

Command-line interface for iterative threat modeling powered by LLMs.
"""

import click

from cli.commands.config import config
from cli.commands.run import run
from cli.commands.version import version


@click.group()
@click.version_option(version="1.1.0", prog_name="paranoid")
def cli() -> None:
    """Paranoid - Open-source iterative threat modeling powered by LLMs.

    Run STRIDE and MAESTRO threat modeling on your system descriptions.
    Supports plain text and structured XML templates.

    \b
    Examples:
      paranoid run system.md                    # Basic usage
      paranoid run api-gateway.md --maestro     # Dual framework
      paranoid config init                      # Setup wizard (Phase 2)
      paranoid version                          # Show version info (Phase 5)

    \b
    Documentation:
      GitHub: https://github.com/theAstiv/paranoid
      Docs:   https://github.com/theAstiv/paranoid#readme
    """
    pass


# Register commands
cli.add_command(run)
cli.add_command(config)
cli.add_command(version)


def main() -> None:
    """Entry point for CLI (called by pyproject.toml script)."""
    cli()


if __name__ == "__main__":
    main()
