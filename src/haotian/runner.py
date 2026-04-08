"""Stable skill-facing runner for Haotian."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from haotian.config import get_settings
from haotian.services.classification_artifact_service import AUTO_SKILL_DECISION_POLICY_VERSION, ClassificationArtifactService
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
    decisions_path = orchestration_service.artifact_service.skill_merge_decisions_path(resolved_date.isoformat())
    legacy_output_path = orchestration_service.artifact_service.classification_output_path(resolved_date.isoformat())

    if decisions_path.exists() and orchestration_service.artifact_service.is_current_prepare_artifact(resolved_date.isoformat()):
        if (
            _has_empty_skill_decisions_with_candidates(orchestration_service.artifact_service, resolved_date, decisions_path)
            or _has_stale_auto_skill_decisions(decisions_path)
        ):
            decisions_path.unlink(missing_ok=True)
            legacy_output_path.unlink(missing_ok=True)
            result = orchestration_service.build_classification_input(resolved_date)
            summary = _build_prepare_summary(result, legacy_output_path)
        else:
            result = orchestration_service.ingest_skill_merge_decisions(resolved_date, decisions_path)
            summary = _build_finalize_summary(result, orchestration_service.artifact_service)
    else:
        decisions_path.unlink(missing_ok=True)
        legacy_output_path.unlink(missing_ok=True)
        result = orchestration_service.build_classification_input(resolved_date)
        summary = _build_prepare_summary(result, legacy_output_path)

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
        database_url = f"sqlite:///{(data_dir / 'haotian.db').resolve().as_posix()}"
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
    status = "awaiting_skill_decision" if result.classification_input_path is not None else "failed"
    skill_candidates_path = getattr(result, "skill_candidates_path", None)
    skill_merge_decisions_path = (
        skill_candidates_path.with_name("skill-merge-decisions.json")
        if skill_candidates_path is not None
        else None
    )
    if status != "awaiting_skill_decision":
        next_action = "Inspect stage_errors and repair the run."
    elif skill_merge_decisions_path is not None and skill_merge_decisions_path.exists():
        next_action = "Haotian auto-generated skill-merge-decisions.json; run the same command again to audit, install, and finalize reports."
    else:
        next_action = (
            "Read skill-candidates.json, write skill-merge-decisions.json beside the staged input, "
            "then run the same command again to finalize reports."
        )

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
        "skill_candidates": str(skill_candidates_path) if skill_candidates_path else None,
        "skill_merge_decisions": str(skill_merge_decisions_path) if skill_merge_decisions_path else None,
        "classification_output": str(output_path),
        "skill_sync_report": None,
        "skill_sync_summary": ClassificationArtifactService.empty_skill_sync_report_payload(result.report_date.isoformat())["summary"],
        "skill_sync_actions": [],
        "stage_errors": result.stage_errors,
        "next_action": next_action,
    }


def _has_empty_skill_decisions_with_candidates(
    artifact_service: ClassificationArtifactService,
    report_date: date,
    decisions_path: Path,
) -> bool:
    try:
        decisions = artifact_service.read_skill_merge_decisions(decisions_path)
        candidates = artifact_service.read_skill_candidates_items(report_date.isoformat())
    except Exception:  # noqa: BLE001
        return False
    return not decisions and bool(candidates)


def _has_stale_auto_skill_decisions(decisions_path: Path) -> bool:
    try:
        import json

        payload = json.loads(decisions_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False
    if payload.get("decision_mode") != "auto":
        return False
    return payload.get("auto_policy_version") != AUTO_SKILL_DECISION_POLICY_VERSION


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
        "skill_merge_decisions": str(result.skill_merge_decisions_path) if result.skill_merge_decisions_path else None,
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
