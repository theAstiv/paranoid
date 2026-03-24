"""Real-time console event renderer for pipeline progress.

Formats PipelineEvent objects with status icons and colors for terminal output.
"""

import time

import click

from backend.pipeline.runner import PipelineEvent, PipelineStep


class ConsoleRenderer:
    """Real-time console event renderer with colored output."""

    # Status icons (Unicode with ASCII fallbacks for Windows)
    try:
        # Try Unicode icons
        ICONS = {
            "started": "▶",
            "completed": "✓",
            "failed": "✗",
            "info": "ℹ",
        }
        # Test if console supports Unicode
        import sys

        "▶".encode(sys.stdout.encoding or "utf-8")
    except (UnicodeEncodeError, AttributeError):
        # Fallback to ASCII
        ICONS = {
            "started": ">",
            "completed": "[OK]",
            "failed": "[FAIL]",
            "info": "[i]",
        }

    # Color mapping for status
    COLORS = {
        "started": "cyan",
        "completed": "green",
        "failed": "red",
        "info": "yellow",
    }

    def __init__(self, verbose: bool = False):
        """Initialize console renderer.

        Args:
            verbose: Show detailed event data (assets, flows, etc.)
        """
        self.verbose = verbose
        self.start_time = time.time()

    def render_event(self, event: PipelineEvent) -> None:
        """Render single event to console with status icon and color.

        Args:
            event: Pipeline event to render
        """
        icon = self.ICONS.get(event.status, "•")
        color = self.COLORS.get(event.status, "white")

        # Build iteration tag if present
        iteration_tag = f" [iter {event.iteration}]" if event.iteration else ""

        # Format step name
        step_name = event.step.value if isinstance(event.step, PipelineStep) else event.step

        # Main message
        click.secho(f"[{icon}] {step_name}{iteration_tag}: {event.message}", fg=color)

        # Verbose mode: show event data
        if self.verbose and event.data:
            import json

            data_str = json.dumps(event.data, indent=2)
            click.echo(f"    Data: {data_str}")

    def render_final_summary(
        self,
        total_threats: int,
        iterations: int,
        duration: float,
        output_file: str | None = None,
    ) -> None:
        """Render final summary with separators.

        Args:
            total_threats: Total number of threats generated
            iterations: Number of iterations completed
            duration: Total duration in seconds
            output_file: Output file path (if JSON export enabled)
        """
        click.echo()
        click.secho("=" * 80, fg="white")
        click.secho("THREAT MODEL COMPLETE", fg="green", bold=True)
        click.secho("=" * 80, fg="white")
        click.echo(f"Total Threats:      {total_threats}")
        click.echo(f"Iterations:         {iterations}")
        click.echo(f"Duration:           {duration:.1f} seconds")
        if output_file:
            click.echo(f"Output:             {output_file}")
        click.echo()
