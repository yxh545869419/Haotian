from __future__ import annotations

import json
from datetime import date

from haotian.collectors.github_trending import TrendingRepo
from haotian.registry.capability_registry import CapabilityRegistryRecord
from haotian.registry.capability_registry import CapabilityRegistryRepository, CapabilityStatus
from haotian.services.classification_artifact_service import ClassificationArtifactService
from haotian.services.orchestration_service import OrchestrationService
from haotian.services.report_service import ReportService


class StubCollector:
    def fetch_trending(self, period: str) -> list[TrendingRepo]:
        fixtures = {
            "daily": [
                TrendingRepo(
                    snapshot_date="2026-03-20",
                    period="daily",
                    rank=1,
                    repo_full_name="acme/browser-bot",
                    repo_url="https://github.com/acme/browser-bot",
                    description="Browser automation agent for websites.",
                    language="Python",
                    stars=100,
                    forks=10,
                )
            ],
            "weekly": [
                TrendingRepo(
                    snapshot_date="2026-03-20",
                    period="weekly",
                    rank=1,
                    repo_full_name="acme/browser-bot",
                    repo_url="https://github.com/acme/browser-bot",
                    description="Browser automation agent for websites.",
                    language="Python",
                    stars=120,
                    forks=12,
                )
            ],
            "monthly": [
                TrendingRepo(
                    snapshot_date="2026-03-20",
                    period="monthly",
                    rank=1,
                    repo_full_name="acme/extractor",
                    repo_url="https://github.com/acme/extractor",
                    description="Data extraction pipeline for unstructured documents.",
                    language="Python",
                    stars=80,
                    forks=8,
                )
            ],
        }
        return fixtures[period]


class StubMetadataFetcher:
    def fetch(self, repo_full_name: str):
        from haotian.collectors.github_repository_metadata import RepositoryMetadataPayload

        payloads = {
            "acme/browser-bot": RepositoryMetadataPayload(
                readme="Browser automation workflows for websites.",
                topics=("browser-agent",),
            ),
            "acme/extractor": RepositoryMetadataPayload(
                readme="Data extraction pipeline. Workflow orchestration across OCR and parsing jobs.",
                topics=("ocr", "automation"),
            ),
        }
        return payloads[repo_full_name]


def build_service(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    report_dir = tmp_path / "reports"
    run_dir = tmp_path / "runs"
    return OrchestrationService(
        collector=StubCollector(),
        metadata_fetcher=StubMetadataFetcher(),
        artifact_service=ClassificationArtifactService(base_dir=run_dir),
        report_service=ReportService(database_url=database_url, report_dir=report_dir),
        database_url=database_url,
    )


def test_build_classification_input_writes_repo_metadata(tmp_path) -> None:
    service = build_service(tmp_path)

    result = service.build_classification_input(date(2026, 3, 20))

    payload = json.loads(result.classification_input_path.read_text(encoding="utf-8"))
    assert result.repos_ingested == 2
    assert result.repository_items == 2
    assert result.stage_errors == []
    assert payload["report_date"] == "2026-03-20"
    assert payload["items"][0]["repo_full_name"] == "acme/browser-bot"
    assert payload["items"][0]["periods"] == ["daily", "weekly"]
    assert "Browser automation workflows for websites." in payload["items"][0]["candidate_texts"]


def test_ingest_classification_output_auto_configures_registry_and_generates_reports(tmp_path) -> None:
    service = build_service(tmp_path)
    staged = service.build_classification_input(date(2026, 3, 20))
    output_path = staged.classification_input_path.with_name("classification-output.json")
    output_path.write_text(
        json.dumps(
            [
                {
                    "repo_full_name": "acme/browser-bot",
                    "capabilities": [
                        {
                            "capability_id": "browser_automation",
                            "confidence": 0.93,
                            "reason": "The repo description and README both focus on browser workflows.",
                            "summary": "Automates browser workflows for websites.",
                            "needs_review": False,
                            "source_label": "codex",
                        }
                    ],
                },
                {
                    "repo_full_name": "acme/extractor",
                    "capabilities": [
                        {
                            "capability_id": "data_extraction",
                            "confidence": 0.9,
                            "reason": "The repo description focuses on extracting structured data from documents.",
                            "summary": "Extracts structured information from unstructured inputs.",
                            "needs_review": False,
                            "source_label": "codex",
                        },
                        {
                            "capability_id": "workflow_orchestration",
                            "confidence": 0.82,
                            "reason": "The README describes a multi-step OCR and parsing workflow.",
                            "summary": "Coordinates OCR and parsing steps into a repeatable workflow.",
                            "needs_review": False,
                            "source_label": "codex",
                        },
                    ],
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = service.ingest_classification_output(date(2026, 3, 20), output_path)

    assert result.repos_ingested == 2
    assert result.capabilities_identified == 3
    assert result.alerts_generated >= 2
    assert result.markdown_report_path == tmp_path / "reports" / "2026-03-20.md"
    assert result.json_report_path == tmp_path / "reports" / "2026-03-20.json"
    assert result.markdown_report_path.exists()
    assert result.json_report_path.exists()
    assert result.stage_errors == []

    repository = CapabilityRegistryRepository(database_url=f"sqlite:///{tmp_path / 'app.db'}")
    capabilities = {item.capability_id: item for item in repository.list_capabilities()}
    assert capabilities["browser_automation"].status in {
        CapabilityStatus.WATCHLIST,
        CapabilityStatus.POC,
        CapabilityStatus.ACTIVE,
    }
    assert capabilities["data_extraction"].status in {CapabilityStatus.WATCHLIST, CapabilityStatus.POC, CapabilityStatus.ACTIVE}
    assert "workflow_orchestration" in capabilities

    content = result.markdown_report_path.read_text(encoding="utf-8")
    assert "## Repo Snapshot" in content
    assert "Today's repos (2): `acme/browser-bot`, `acme/extractor`" in content
    assert "Manual Attention" in content
    assert "Periods: `daily, weekly`" in content or "Periods: `monthly`" in content
