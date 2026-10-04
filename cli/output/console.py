"""Real-time console event renderer for pipeline progress.

Formats PipelineEvent objects with status icons and colors for terminal output.
"""

import time

import click

from backend.pipeline.runner import PipelineEvent, PipelineStep
from backend.serialization import serialize_event_data


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

            data_to_show = serialize_event_data(event.data)

            try:
                data_str = json.dumps(data_to_show, indent=2)
                click.echo(f"    Data: {data_str}")
            except (TypeError, ValueError):
                click.echo(f"    Data: {data_to_show}")

    def render_final_summary(
        self,
        total_threats: int,
        iterations: int,
        duration: float,
        output_file: str | None = None,
        usage: dict | None = None,
    ) -> None:
        """Render final summary with separators.

        Args:
            total_threats: Total number of threats generated
            iterations: Number of iterations completed
            duration: Total duration in seconds
            output_file: Output file path (if JSON export enabled)
            usage: The COMPLETE event's ``data["usage"]`` (a serialized
                ``RunUsage``) — tokens by model and the fast-model share, if
                a distinct fast provider was used. None prints nothing extra.
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
        self._render_usage(usage)
        click.echo()

    def _render_usage(self, usage: dict | None) -> None:
        """Print the per-model token breakdown and fast-model share.

        No dollar figures here by design (decided 2026-10-01): tokens are
        reported by model, pricing is left to the user's own provider logs.
        """
        if not usage or not usage.get("by_model"):
            return
        click.echo(f"Total Tokens:       {usage.get('total_tokens', 0):,}")
        for model_usage in usage["by_model"]:
            tokens = model_usage.get("total_tokens", 0)
            calls = model_usage.get("calls", 0)
            click.echo(
                f"  {model_usage['model']:<30} {tokens:>10,} tokens  ({calls} call{'s' if calls != 1 else ''})"
            )
        if usage.get("fast_model_share") is not None:
            click.echo(
                f"Fast-model share:   {usage['fast_model_share']:.0%} of tokens served by {usage['fast_model']}"
            )
        if usage.get("fast_routing_disabled"):
            click.secho(
                "Warning: fast routing was disabled mid-run after a fast-model failure; "
                "later fast-routed steps ran on the main model.",
                fg="yellow",
            )
