from __future__ import annotations

import json
from datetime import date

from haotian.db.schema import get_connection, initialize_schema
from haotian.registry.capability_registry import (
    CapabilityApproval,
    CapabilityApprovalAction,
    CapabilityRegistryRecord,
    CapabilityRegistryRepository,
    CapabilityStatus,
)
from haotian.services.report_service import ReportService


def test_report_service_aggregates_capabilities_and_repo_snapshots(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    initialize_schema(database_url)
    repository = CapabilityRegistryRepository(database_url=database_url)
    repository.upsert_capability(
        CapabilityRegistryRecord(
            capability_id="browser_automation",
            canonical_name="Browser Automation",
            status=CapabilityStatus.POC,
            summary="Automates browser workflows.",
            first_seen_at="2026-03-20T00:00:00Z",
            last_seen_at="2026-03-20T00:00:00Z",
            last_score=0.91,
            mention_count=2,
            consecutive_appearances=2,
            source_repo_full_name="acme/browser-bot",
        )
    )
    repository.add_approval(
        CapabilityApproval(
            capability_id="browser_automation",
            action=CapabilityApprovalAction.POC,
            resulting_status=CapabilityStatus.POC,
            reviewer="auto-config",
            note="Automatically configured.",
            snapshot_date="2026-03-20",
        )
    )
    with get_connection(database_url) as connection:
        connection.executemany(
            """
            INSERT INTO repo_capabilities (
                snapshot_date,
                period,
                repo_full_name,
                capability_id,
                confidence,
                reason,
                summary,
                needs_review,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "2026-03-20",
                    "daily",
                    "acme/browser-bot",
                    "browser_automation",
                    0.91,
                    "Daily trend mentions browser automation.",
                    "Automates browser workflows.",
                    0,
                    "2026-03-20T00:00:00Z",
                ),
                (
                    "2026-03-20",
                    "weekly",
                    "acme/browser-bot",
                    "browser_automation",
                    0.88,
                    "Weekly trend confirms the same capability.",
                    "Automates browser workflows.",
                    0,
                    "2026-03-20T00:00:00Z",
                ),
            ],
        )
        connection.executemany(
            """
            INSERT INTO trending_repos (
                snapshot_date,
                period,
                rank,
                repo_full_name,
                repo_url,
                description,
                language,
                stars,
                forks
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("2026-03-19", "daily", 1, "acme/old-repo", "https://github.com/acme/old-repo", None, None, 10, 1),
                ("2026-03-20", "daily", 1, "acme/browser-bot", "https://github.com/acme/browser-bot", None, None, 10, 1),
                ("2026-03-20", "monthly", 2, "acme/extractor", "https://github.com/acme/extractor", None, None, 10, 1),
            ],
        )
        connection.commit()

    report_dir = tmp_path / "reports"
    path = ReportService(database_url=database_url, report_dir=report_dir).generate_daily_report(date(2026, 3, 20))
    content = path.read_text(encoding="utf-8")

    assert "Total capabilities: 1" in content
    assert "Today's repos (2): `acme/browser-bot`, `acme/extractor`" in content
    assert "New vs previous snapshot (2): `acme/browser-bot`, `acme/extractor`" in content
    assert "Dropped vs previous snapshot (1): `acme/old-repo`" in content
    assert "Source Repos (1): `acme/browser-bot`" in content
    assert "Periods: `daily, weekly`" in content
    assert "Manual Attention: NO" in content

    json_path = ReportService(database_url=database_url, report_dir=report_dir).generate_daily_report_json("2026-03-20")
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["report_date"] == "2026-03-20"
    assert payload["summary"]["total_capabilities"] == 1
    assert payload["repo_snapshot"]["new"] == ["acme/browser-bot", "acme/extractor"]
    assert payload["sections"]["covered"] == []
    assert payload["sections"]["enhancement_candidates"][0]["capability_id"] == "browser_automation"
