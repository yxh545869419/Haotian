from __future__ import annotations

from datetime import date

from haotian.collectors.github_trending import TrendingRepo
from haotian.services.orchestration_service import OrchestrationService


class StubCollector:
    def fetch_trending(self, period: str) -> list[TrendingRepo]:
        assert period == "daily"
        return [
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
            ),
            TrendingRepo(
                snapshot_date="2026-03-20",
                period="daily",
                rank=2,
                repo_full_name="acme/extractor",
                repo_url="https://github.com/acme/extractor",
                description="Data extraction pipeline for unstructured documents.",
                language="Python",
                stars=80,
                forks=8,
            ),
        ]


def test_run_daily_pipeline_generates_health_summary(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    report_dir = tmp_path / "reports"
    service = OrchestrationService(
        collector=StubCollector(),
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
    content = result.report_path.read_text(encoding="utf-8")
    assert "Daily Capability Report - 2026-03-20" in content
    assert "browser_automation" in content or "data_extraction" in content
