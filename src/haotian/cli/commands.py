"""CLI command definitions."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from haotian.config import get_settings
from haotian.registry.capability_registry import CapabilityApprovalAction
from haotian.services.approval_service import ApprovalService
from haotian.services.report_service import ReportService, generate_daily_report

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
    """Generate the daily markdown report."""

    settings = get_settings()
    target_dir = report_dir or settings.report_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    parsed_date = date.fromisoformat(report_date)
    path = generate_daily_report(parsed_date) if report_dir is None else ReportService(report_dir=target_dir).generate_daily_report(parsed_date)
    typer.echo(f"Generated report: {path}")


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
