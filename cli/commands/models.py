"""Models command - list and inspect saved threat models from SQLite."""

import asyncio
import json
from pathlib import Path

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


def _category_from_row(row: dict) -> str:  # type: ignore[type-arg]
    """Return stride_category or maestro_category from a DB threat row."""
    return row.get("stride_category") or row.get("maestro_category") or "Unknown"


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

        \b
        # Export a saved model to Markdown
        paranoid models export a1b2c3d4 --format markdown -o report.md
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


# ---------------------------------------------------------------------------
# export command
# ---------------------------------------------------------------------------

_FORMAT_EXTENSIONS = {
    "simple": ".json",
    "full": ".json",
    "sarif": ".sarif",
    "markdown": ".md",
}


@models.command(name="export")
@click.argument("model_id")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["simple", "full", "sarif", "markdown"], case_sensitive=False),
    required=True,
    help="Export format: simple/full (JSON), sarif (GitHub Security), or markdown",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output file path (default: {id_prefix}_{format}{ext} in current directory)",
)
def export_model(model_id: str, output_format: str, output: Path | None) -> None:
    """Export a saved threat model to a file.

    MODEL_ID can be a full UUID or a unique prefix (e.g. 'a1b2c3d4').

    Examples:

        \b
        paranoid models export a1b2c3d4 --format markdown -o report.md
        paranoid models export a1b2c3d4 --format sarif -o findings.sarif
        paranoid models export a1b2c3d4 --format simple -o threats.json
        paranoid models export a1b2c3d4 --format full
    """
    try:
        asyncio.run(
            _export_model_async(model_id=model_id, output_format=output_format, output=output)
        )
    except CLIError as e:
        click.secho(f"\n✗ Error: {e.message}", fg="red", err=True)
        raise SystemExit(e.exit_code) from e
    except Exception as e:
        click.secho(f"\n✗ Unexpected error: {e}", fg="red", err=True)
        raise SystemExit(1) from e


async def _export_model_async(
    model_id: str,
    output_format: str,
    output: Path | None,
) -> None:
    from backend.db import crud

    # Resolve full UUID or prefix
    if len(model_id) == 36:
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

    # Determine output path
    ext = _FORMAT_EXTENSIONS[output_format]
    if output is None:
        output_path = Path(f"{model['id'][:8]}_{output_format}{ext}")
    elif not output.suffix:
        output_path = output.with_suffix(ext)
    else:
        output_path = output

    # Dispatch to export function
    if output_format == "markdown":
        from backend.export.markdown import export_markdown

        md = export_markdown(
            threats=threats,
            model_id=model["id"],
            framework=model.get("framework", "STRIDE"),
            title=model.get("title"),
        )
        output_path.write_text(md, encoding="utf-8")

    elif output_format == "sarif":
        from backend.export.sarif import export_sarif
        from backend.models.state import Threat, ThreatsList

        stride_rows = [r for r in threats if r.get("stride_category")]
        skipped = len(threats) - len(stride_rows)
        if skipped:
            click.secho(
                f"  ⚠ Skipping {skipped} MAESTRO threat(s) — SARIF export is STRIDE-only",
                fg="yellow",
            )

        built = []
        for r in stride_rows:
            try:
                # model_construct skips Pydantic validation — persisted descriptions may
                # not meet the 35-50 word constraint enforced at generation time
                built.append(Threat.model_construct(**r))
            except Exception as exc:
                click.secho(f"  ⚠ Skipping threat '{r.get('name', '?')}': {exc}", fg="yellow")

        threats_list = ThreatsList.model_construct(threats=built)
        sarif_data = export_sarif(
            threats=threats_list,
            model_id=model["id"],
            framework=model.get("framework", "STRIDE"),
        )
        output_path.write_text(json.dumps(sarif_data, indent=2), encoding="utf-8")

    elif output_format == "simple":
        simple = {
            "model_id": model["id"],
            "title": model.get("title"),
            "framework": model.get("framework"),
            "created_at": model.get("created_at"),
            "threats": [
                {
                    "name": t.get("name"),
                    "category": _category_from_row(t),
                    "target": t.get("target"),
                    "impact": t.get("impact"),
                    "likelihood": t.get("likelihood"),
                    "dread_score": t.get("dread_score"),
                    "mitigation_count": len(t.get("mitigations") or []),
                }
                for t in threats
            ],
        }
        output_path.write_text(json.dumps(simple, indent=2), encoding="utf-8")

    else:  # full
        output_path.write_text(
            json.dumps({"model": model, "threats": threats}, indent=2, default=str),
            encoding="utf-8",
        )

    click.echo()
    click.secho(
        f"  ✓ Exported {len(threats)} threat(s) → {output_path}",
        fg="green",
    )
    click.echo()
