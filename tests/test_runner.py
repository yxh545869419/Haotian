from __future__ import annotations

import json

from haotian.runner import run_once
from haotian.services.classification_artifact_service import ClassificationArtifactService
from haotian.services.orchestration_service import OrchestrationService
from haotian.services.report_service import ReportService
from tests.test_orchestration_service import StubCollector, StubMetadataFetcher


def build_runner_service(tmp_path) -> OrchestrationService:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    return OrchestrationService(
        collector=StubCollector(),
        metadata_fetcher=StubMetadataFetcher(),
        artifact_service=ClassificationArtifactService(base_dir=tmp_path / "runs"),
        report_service=ReportService(database_url=database_url, report_dir=tmp_path / "reports"),
        database_url=database_url,
    )


def test_runner_stages_then_finalizes_reports(tmp_path) -> None:
    service = build_runner_service(tmp_path)

    first = run_once(report_date="2026-03-20", service=service)

    assert first["status"] == "awaiting_classification"
    assert first["classification_input"].endswith("classification-input.json")
    assert first["stage_errors"] == []

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
