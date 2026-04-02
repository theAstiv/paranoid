"""Models command - list and inspect saved threat models from SQLite."""

import asyncio
import json

import click

from cli.errors import CLIError


def _short_id(model_id: str) -> str:
    """Return first 8 characters of a UUID for display."""
    return model_id[:8]


def _format_date(iso_str: str) -> str:
    """Format ISO timestamp to human-readable date."""
    if not iso_str:
        return "unknown"
    # ISO string: 2026-04-01T14:32:00.000000
    return iso_str[:16].replace("T", " ")


@click.group()
def models() -> None:
    """List and inspect saved threat models.

    Examples:

        \b
        # List recent threat models
        paranoid models list

        \b
        # Show threats for a model (partial ID works)
        paranoid models show a1b2c3d4
    """
    pass


@models.command(name="list")
@click.option(
    "--limit",
    "-n",
    type=click.IntRange(1, 200),
    default=20,
    help="Maximum number of models to show (default: 20)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON",
)
def list_models(limit: int, as_json: bool) -> None:
    """List saved threat models, most recent first.

    Examples:

        \b
        paranoid models list
        paranoid models list --limit 50
        paranoid models list --json
    """
    try:
        asyncio.run(_list_models_async(limit=limit, as_json=as_json))
    except CLIError as e:
        click.secho(f"\n✗ Error: {e.message}", fg="red", err=True)
        raise SystemExit(e.exit_code) from e
    except Exception as e:
        click.secho(f"\n✗ Unexpected error: {e}", fg="red", err=True)
        raise SystemExit(1) from e


async def _list_models_async(limit: int, as_json: bool) -> None:
    from backend.db import crud

    models = await crud.list_threat_models(limit=limit)

    if as_json:
        click.echo(json.dumps(models, indent=2))
        return

    if not models:
        click.echo()
        click.secho("No threat models found.", fg="yellow")
        click.echo("Run a threat model first:")
        click.echo("  paranoid run system.md")
        click.echo()
        return

    click.echo()
    # Header
    click.secho(
        f"  {'ID':<10}  {'Title':<20}  {'Framework':<9}  {'Threats':>7}  {'Status':<10}  Date",
        fg="cyan",
        bold=True,
    )
    click.secho("  " + "-" * 72, fg="white")

    for m in models:
        short = _short_id(m["id"])
        title = (m["title"] or "")[:20]
        framework = (m["framework"] or "")[:9]
        threat_count = m.get("threat_count") or 0
        status = m.get("status") or "unknown"
        date = _format_date(m.get("created_at", ""))

        status_color = "green" if status == "completed" else "yellow"
        click.echo(
            f"  {short:<10}  {title:<20}  {framework:<9}  {threat_count:>7}  "
            + click.style(f"{status:<10}", fg=status_color)
            + f"  {date}"
        )

    click.echo()
    click.secho(
        f"  {len(models)} model(s) shown. Use 'paranoid models show <id>' to inspect.", fg="white"
    )
    click.echo()


@models.command()
@click.argument("model_id")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output threats as JSON",
)
@click.option(
    "--mitigations/--no-mitigations",
    default=True,
    help="Show or hide mitigations (default: show)",
)
def show(model_id: str, as_json: bool, mitigations: bool) -> None:
    """Show threats for a saved model.

    MODEL_ID can be a full UUID or a unique prefix (e.g. 'a1b2c3d4').

    Examples:

        \b
        paranoid models show a1b2c3d4
        paranoid models show a1b2c3d4 --json
        paranoid models show a1b2c3d4 --no-mitigations
    """
    try:
        asyncio.run(
            _show_model_async(model_id=model_id, as_json=as_json, show_mitigations=mitigations)
        )
    except CLIError as e:
        click.secho(f"\n✗ Error: {e.message}", fg="red", err=True)
        raise SystemExit(e.exit_code) from e
    except Exception as e:
        click.secho(f"\n✗ Unexpected error: {e}", fg="red", err=True)
        raise SystemExit(1) from e


async def _show_model_async(model_id: str, as_json: bool, show_mitigations: bool) -> None:
    from backend.db import crud

    # Resolve full or prefix ID
    if len(model_id) == 36:
        # Looks like a full UUID — try exact match first
        model = await crud.get_threat_model(model_id)
    else:
        try:
            model = await crud.find_threat_model_by_prefix(model_id)
        except ValueError as e:
            raise CLIError(str(e)) from e

    if model is None:
        raise CLIError(
            f"No threat model found matching '{model_id}'.\n"
            "Run 'paranoid models list' to see available models."
        )

    threats = await crud.list_threats(model["id"])

    if as_json:
        click.echo(json.dumps({"model": model, "threats": threats}, indent=2))
        return

    click.echo()
    click.secho(f"  Threat Model: {model.get('title', 'untitled')}", fg="cyan", bold=True)
    click.secho("  " + "=" * 60, fg="white")
    click.echo(f"  ID:           {model['id']}")
    click.echo(f"  Framework:    {model.get('framework', 'unknown')}")
    click.echo(f"  Provider:     {model.get('provider', 'unknown')}")
    click.echo(f"  Status:       {model.get('status', 'unknown')}")
    click.echo(f"  Iterations:   {model.get('iteration_count', 0)}")
    click.echo(f"  Threats:      {len(threats)}")
    click.echo(f"  Created:      {_format_date(model.get('created_at', ''))}")
    click.echo()

    if not threats:
        click.secho("  No threats recorded.", fg="yellow")
        click.echo()
        return

    click.secho("  THREATS", fg="cyan", bold=True)
    click.secho("  " + "-" * 60, fg="white")

    for i, threat in enumerate(threats, 1):
        name = threat.get("name", "unnamed")
        category = threat.get("stride_category") or threat.get("maestro_category") or "—"
        target = threat.get("target") or "—"
        impact = threat.get("impact") or "—"
        likelihood = threat.get("likelihood") or "—"
        status = threat.get("status") or "pending"
        dread = threat.get("dread_score")

        status_color = (
            "green" if status == "accepted" else "red" if status == "rejected" else "white"
        )

        click.echo()
        click.echo(
            f"  [{i}] "
            + click.style(name, bold=True)
            + click.style(f"  ({category})", fg="cyan")
            + "  "
            + click.style(status, fg=status_color)
        )
        click.echo(
            f"      Target: {target}  |  Impact: {impact}  |  Likelihood: {likelihood}", nl=False
        )
        if dread is not None:
            click.echo(f"  |  DREAD: {dread:.1f}")
        else:
            click.echo()

        if show_mitigations and threat.get("mitigations"):
            mitig_list = threat["mitigations"]
            if isinstance(mitig_list, str):
                import json as _json

                try:
                    mitig_list = _json.loads(mitig_list)
                except Exception:
                    mitig_list = [mitig_list]
            for m in mitig_list:
                click.echo(f"      → {m}")

    click.echo()
    click.secho(f"  {len(threats)} threat(s) total.", fg="white")
    click.echo()
