"""Stable skill-facing runner for Haotian."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from haotian.config import get_settings
from haotian.services.classification_artifact_service import ClassificationArtifactService
from haotian.services.orchestration_service import ClassificationInputBuildResult, DailyPipelineResult, OrchestrationService
from haotian.services.report_service import ReportService


def run_once(
    *,
    report_date: str | None = None,
    workspace: Path | str | None = None,
    service: OrchestrationService | None = None,
) -> dict[str, object]:
    """Run the next Haotian skill stage for a report date."""

    resolved_date = _normalize_report_date(report_date)
    orchestration_service = service or _build_service(workspace)
    output_path = orchestration_service.artifact_service.classification_output_path(resolved_date.isoformat())

    if output_path.exists() and orchestration_service.artifact_service.is_current_prepare_artifact(resolved_date.isoformat()):
        result = orchestration_service.ingest_classification_output(resolved_date, output_path)
        summary = _build_finalize_summary(result, orchestration_service.artifact_service)
    else:
        output_path.unlink(missing_ok=True)
        result = orchestration_service.build_classification_input(resolved_date)
        summary = _build_prepare_summary(result, output_path)

    run_summary_path = orchestration_service.artifact_service.run_summary_path(resolved_date.isoformat())
    summary["run_summary"] = str(run_summary_path)
    orchestration_service.artifact_service.write_run_summary(
        report_date=resolved_date.isoformat(),
        summary=summary,
    )
    return summary


def _build_service(workspace: Path | str | None) -> OrchestrationService:
    settings = get_settings()
    repository_tmp_dir = None
    if workspace is None:
        database_url = settings.database_url
        report_dir = settings.report_dir
        run_dir = settings.run_dir
    else:
        base_dir = Path(workspace)
        data_dir = base_dir / "data"
        database_url = f"sqlite:///{(data_dir / 'app.db').resolve().as_posix()}"
        report_dir = data_dir / "reports"
        run_dir = data_dir / "runs"
        repository_tmp_dir = data_dir / "tmp" / "repos"

    return OrchestrationService(
        database_url=database_url,
        report_service=ReportService(database_url=database_url, report_dir=report_dir, run_dir=run_dir),
        artifact_service=ClassificationArtifactService(base_dir=run_dir),
        repository_tmp_dir=repository_tmp_dir,
    )


def _build_prepare_summary(result: ClassificationInputBuildResult, output_path: Path) -> dict[str, object]:
    status = "awaiting_classification" if result.classification_input_path is not None else "failed"
    return {
        "status": status,
        "report_date": result.report_date.isoformat(),
        "repos_ingested": result.repos_ingested,
        "repository_items": result.repository_items,
        "deep_analyzed_repos": result.deep_analyzed_repos,
        "cached_reused_repos": result.cached_reused_repos,
        "fallback_repos": result.fallback_repos,
        "skipped_due_to_budget": result.skipped_due_to_budget,
        "cleanup_warnings": result.cleanup_warnings,
        "classification_input": str(result.classification_input_path) if result.classification_input_path else None,
        "classification_output": str(output_path),
        "skill_sync_report": None,
        "skill_sync_summary": ClassificationArtifactService.empty_skill_sync_report_payload(result.report_date.isoformat())["summary"],
        "skill_sync_actions": [],
        "stage_errors": result.stage_errors,
        "next_action": (
            "Read docs/capability-taxonomy.md, write classification-output.json beside the staged input, "
            "then run the same command again to finalize reports."
            if status == "awaiting_classification"
            else "Inspect stage_errors and repair the run."
        ),
    }


def _build_finalize_summary(
    result: DailyPipelineResult,
    artifact_service: ClassificationArtifactService,
) -> dict[str, object]:
    completed = (
        result.succeeded
        and result.markdown_report_path is not None
        and result.json_report_path is not None
    )
    return {
        "status": "completed" if completed else "failed",
        "report_date": result.report_date.isoformat(),
        "repos_ingested": result.repos_ingested,
        "capabilities_identified": result.capabilities_identified,
        "alerts_generated": result.alerts_generated,
        "deep_analyzed_repos": result.deep_analyzed_repos,
        "cached_reused_repos": result.cached_reused_repos,
        "fallback_repos": result.fallback_repos,
        "skipped_due_to_budget": result.skipped_due_to_budget,
        "cleanup_warnings": result.cleanup_warnings,
        "classification_output": str(result.classification_output_path) if result.classification_output_path else None,
        "markdown_report": str(result.markdown_report_path) if result.markdown_report_path else None,
        "json_report": str(result.json_report_path) if result.json_report_path else None,
        "capability_audit": str(result.capability_audit_path) if result.capability_audit_path else None,
        "taxonomy_gap_candidates_report": (
            str(result.taxonomy_gap_candidates_path) if result.taxonomy_gap_candidates_path else None
        ),
        "skill_sync_report": str(result.skill_sync_report_path) if result.skill_sync_report_path else None,
        "skill_sync_summary": result.skill_sync_summary or ClassificationArtifactService.default_skill_sync_summary(),
        "skill_sync_actions": result.skill_sync_actions,
        "auto_promoted_capabilities": result.auto_promoted_capabilities,
        "risky_enhancement_candidates": result.risky_enhancement_candidates,
        "manual_attention_items": result.manual_attention_items,
        "taxonomy_gap_candidates": result.taxonomy_gap_candidates,
        "stage_errors": result.stage_errors,
        "next_action": "Review the generated Markdown/JSON report artifacts." if completed else "Inspect stage_errors and repair the run.",
    }


def _normalize_report_date(value: str | None) -> date:
    return date.fromisoformat(value) if value else date.today()
