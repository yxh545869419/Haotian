from __future__ import annotations

import json
from types import SimpleNamespace

from haotian.runner import run_once
from haotian.services.classification_artifact_service import ClassificationArtifactService
from haotian.services.orchestration_service import OrchestrationService
from haotian.services.report_service import ReportService
from tests.test_orchestration_service import BudgetCollector
from tests.test_orchestration_service import StubCollector
from tests.test_orchestration_service import StubMetadataFetcher
from tests.test_orchestration_service import StubRepositoryAnalysisService
from tests.test_orchestration_service import make_layered_result


def build_runner_service(
    tmp_path,
    *,
    collector: StubCollector | BudgetCollector | None = None,
    repository_analysis_service: StubRepositoryAnalysisService | None = None,
    max_deep_analysis_repos: int | None = None,
) -> OrchestrationService:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    return OrchestrationService(
        collector=collector or StubCollector(),
        metadata_fetcher=StubMetadataFetcher(),
        artifact_service=ClassificationArtifactService(base_dir=tmp_path / "runs"),
        report_service=ReportService(database_url=database_url, report_dir=tmp_path / "reports"),
        repository_analysis_service=repository_analysis_service,
        max_deep_analysis_repos=max_deep_analysis_repos,
        database_url=database_url,
    )


def test_runner_stages_then_finalizes_reports(tmp_path) -> None:
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/browser-bot": make_layered_result("acme/browser-bot", repo_url="https://github.com/acme/browser-bot"),
            "acme/extractor": make_layered_result("acme/extractor", repo_url="https://github.com/acme/extractor"),
        }
    )
    service = build_runner_service(tmp_path, repository_analysis_service=analysis_service)

    first = run_once(report_date="2026-03-20", service=service)

    assert first["status"] == "awaiting_classification"
    assert first["classification_input"].endswith("classification-input.json")
    assert first["stage_errors"] == []
    assert first["deep_analyzed_repos"] == 2
    assert first["fallback_repos"] == 0
    assert first["skipped_due_to_budget"] == 0
    assert first["cleanup_warnings"] == 0

    output_path = service.artifact_service.classification_output_path("2026-03-20")
    output_path.write_text(
        json.dumps(
            [
                {
                    "repo_full_name": "acme/browser-bot",
                    "capabilities": [
                        {
                            "capability_id": "browser_automation",
                            "confidence": 0.93,
                            "reason": "The repo centers on browser workflow automation.",
                            "summary": "Automates browser workflows for websites.",
                            "needs_review": False,
                            "source_label": "codex",
                        }
                    ],
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    second = run_once(report_date="2026-03-20", service=service)

    assert second["status"] == "completed"
    assert second["markdown_report"].endswith("2026-03-20.md")
    assert second["json_report"].endswith("2026-03-20.json")
    assert second["run_summary"].endswith("run-summary.json")
    assert second["stage_errors"] == []
    assert second["deep_analyzed_repos"] == 2
    assert second["fallback_repos"] == 0
    assert second["skipped_due_to_budget"] == 0
    assert second["cleanup_warnings"] == 0


def test_runner_summary_includes_budget_counts(tmp_path) -> None:
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/alpha": make_layered_result("acme/alpha", repo_url="https://github.com/acme/alpha"),
            "acme/bravo": make_layered_result("acme/bravo", repo_url="https://github.com/acme/bravo"),
            "acme/charlie": make_layered_result("acme/charlie", repo_url="https://github.com/acme/charlie"),
        }
    )
    service = build_runner_service(
        tmp_path,
        collector=BudgetCollector(),
        repository_analysis_service=analysis_service,
        max_deep_analysis_repos=1,
    )

    first = run_once(report_date="2026-03-20", service=service)

    assert first["deep_analyzed_repos"] == 1
    assert first["fallback_repos"] == 2
    assert first["skipped_due_to_budget"] == 2
    assert first["cleanup_warnings"] == 0


def test_runner_reports_failed_prepare_when_ingest_fails(tmp_path, monkeypatch) -> None:
    service = build_runner_service(tmp_path)

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002, ARG001
        raise RuntimeError("ingest failed")

    monkeypatch.setattr(service.ingest_service, "ingest_trending_repos", boom)

    summary = run_once(report_date="2026-03-20", service=service)

    assert summary["status"] == "failed"
    assert summary["classification_input"] is None
    assert summary["next_action"] == "Inspect stage_errors and repair the run."
    assert "classification-output.json" not in summary["next_action"]


def test_runner_workspace_scopes_repository_analysis_temp_root(tmp_path, monkeypatch) -> None:
    captured = {}

    class FakeOrchestrationService:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs
            self.artifact_service = kwargs["artifact_service"]

        def build_classification_input(self, report_date):  # noqa: ANN001
            return SimpleNamespace(
                report_date=report_date,
                repos_ingested=0,
                repository_items=0,
                deep_analyzed_repos=0,
                fallback_repos=0,
                skipped_due_to_budget=0,
                cleanup_warnings=0,
                classification_input_path=self.artifact_service.classification_input_path(report_date.isoformat()),
                stage_errors=[],
            )

        def ingest_classification_output(self, report_date, path):  # noqa: ANN001
            raise AssertionError("unexpected finalize path")

    monkeypatch.setattr("haotian.runner.OrchestrationService", FakeOrchestrationService)

    workspace = tmp_path / "workspace"
    run_once(report_date="2026-03-20", workspace=workspace)

    assert captured["kwargs"]["repository_tmp_dir"] == workspace / "data" / "tmp" / "repos"
