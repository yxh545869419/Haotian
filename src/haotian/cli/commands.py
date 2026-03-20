"""CLI command definitions."""

from __future__ import annotations

from datetime import date
import logging
from pathlib import Path

import typer

from haotian.config import get_settings
from haotian.registry.capability_registry import CapabilityApprovalAction
from haotian.services.approval_service import ApprovalService
from haotian.services.orchestration_service import OrchestrationService
from haotian.services.report_service import ReportService

app = typer.Typer(help="Haotian command line interface.")
run_app = typer.Typer(help="Workflow commands.")
approval_app = typer.Typer(help="Capability approval commands.")
app.add_typer(run_app, name="run")
app.add_typer(approval_app, name="approval")


@run_app.command("daily")
def run_daily(
    report_date: str = typer.Option(
        date.today().isoformat(),
        "--date",
        help="Date to generate the daily report for (YYYY-MM-DD).",
    ),
    report_dir: Path | None = typer.Option(
        default=None,
        help="Optional override for report output directory.",
    ),
) -> None:
    """Run the daily MVP pipeline end to end."""

    _configure_logging()
    settings = get_settings()
    target_dir = report_dir or settings.report_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    parsed_date = date.fromisoformat(report_date)
    service = OrchestrationService(
        report_service=ReportService(
            database_url=settings.database_url,
            report_dir=target_dir,
        ),
        database_url=settings.database_url,
    )
    result = service.run_daily_pipeline(parsed_date)
    typer.echo(f"Repos fetched: {result.repos_ingested}")
    typer.echo(f"Capabilities identified: {result.capabilities_identified}")
    typer.echo(f"Alert-worthy updates: {result.alerts_generated}")
    typer.echo(f"Report path: {result.report_path}")
    if result.stage_errors:
        typer.echo("Errors:")
        for error in result.stage_errors:
            typer.echo(f"- {error}")
        raise typer.Exit(code=1)


@approval_app.command("apply")
def approval_apply(
    capability: str = typer.Option(..., "--capability", help="Capability identifier to update."),
    action: CapabilityApprovalAction = typer.Option(..., "--action", help="Approval action to apply."),
    reviewer: str | None = typer.Option(None, "--reviewer", help="Reviewer name or handle."),
    note: str | None = typer.Option(None, "--note", help="Optional approval note."),
    snapshot_date: str | None = typer.Option(None, "--snapshot-date", help="Optional snapshot date (YYYY-MM-DD)."),
) -> None:
    """Apply an approval action to a capability."""

    service = ApprovalService()
    updated = service.apply_approval(
        capability_id=capability,
        action=action,
        reviewer=reviewer,
        note=note,
        snapshot_date=snapshot_date,
    )
    typer.echo(
        f"Applied {action.value} to {updated.capability_id}; registry status is now {updated.status.value}."
    )


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
