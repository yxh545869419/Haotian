"""CLI command definitions."""

from __future__ import annotations

from pathlib import Path

import typer

from haotian.config import get_settings

app = typer.Typer(help="Haotian command line interface.")
run_app = typer.Typer(help="Workflow commands.")
app.add_typer(run_app, name="run")


@run_app.command("daily")
def run_daily(
    report_dir: Path | None = typer.Option(
        default=None,
        help="Optional override for report output directory.",
    ),
) -> None:
    """Placeholder for the daily processing workflow."""

    settings = get_settings()
    target_dir = report_dir or settings.report_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    typer.echo("Haotian daily workflow is not implemented yet.")
    typer.echo(f"Database: {settings.database_url}")
    typer.echo(f"LLM provider: {settings.llm_provider}")
    typer.echo(f"Report directory: {target_dir}")
