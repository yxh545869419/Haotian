from __future__ import annotations

from datetime import date

from haotian.collectors.github_trending import TrendingRepo
from haotian.registry.capability_registry import CapabilityRegistryRepository, CapabilityStatus
from haotian.services.orchestration_service import OrchestrationService


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


def test_run_daily_pipeline_auto_configures_registry_and_generates_report(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    report_dir = tmp_path / "reports"
    service = OrchestrationService(
        collector=StubCollector(),
        metadata_fetcher=StubMetadataFetcher(),
        database_url=database_url,
    )
    service.report_service.report_dir = report_dir

    result = service.run_daily_pipeline(date(2026, 3, 20))

    assert result.repos_ingested == 2
    assert result.capabilities_identified >= 2
    assert result.alerts_generated >= 2
    assert result.report_path == report_dir / "2026-03-20.md"
    assert result.report_path.exists()
    assert result.stage_errors == []

    repository = CapabilityRegistryRepository(database_url=database_url)
    capabilities = {item.capability_id: item for item in repository.list_capabilities()}
    assert capabilities["browser_automation"].status in {
        CapabilityStatus.WATCHLIST,
        CapabilityStatus.POC,
        CapabilityStatus.ACTIVE,
    }
    assert capabilities["data_extraction"].status in {CapabilityStatus.WATCHLIST, CapabilityStatus.POC, CapabilityStatus.ACTIVE}
    assert "workflow_orchestration" in capabilities

    content = result.report_path.read_text(encoding="utf-8")
    assert "## Repo Snapshot" in content
    assert "Today's repos (2): `acme/browser-bot`, `acme/extractor`" in content
    assert "Manual Attention" in content
    assert "Periods: `daily, weekly`" in content or "Periods: `monthly`" in content
