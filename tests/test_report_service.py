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


def _insert_repo_capability(
    connection,
    *,
    snapshot_date: str,
    period: str,
    repo_full_name: str,
    capability_id: str,
    confidence: float,
    reason: str,
    summary: str,
    needs_review: int = 0,
) -> None:
    connection.execute(
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
        (
            snapshot_date,
            period,
            repo_full_name,
            capability_id,
            confidence,
            reason,
            summary,
            needs_review,
            f"{snapshot_date}T00:00:00Z",
        ),
    )


def _insert_repo_analysis_snapshot(
    connection,
    *,
    snapshot_date: str,
    repo_full_name: str,
    repo_url: str = "https://github.com/acme/browser-bot",
    analysis_depth: str = "layered",
    clone_strategy: str = "shallow-clone",
    clone_started: int = 1,
    analysis_completed: int = 1,
    cleanup_attempted: int = 1,
    cleanup_required: int = 1,
    cleanup_completed: int = 1,
    fallback_used: int = 0,
    root_files: str = '["README.md", "workflow.py"]',
    matched_files: str = '["README.md", "workflow.py"]',
    matched_keywords: str = '["README*", "workflow*"]',
    architecture_signals: str = '["browser-automation"]',
    probe_summary: str = "Layered probe selected 2 files across browser-automation.",
    evidence_snippets: str = (
        '[{"path":"README.md","excerpt":"Browser automation workflows","why_it_matters":"Usually the clearest project overview for the repository."}]'
    ),
    analysis_limits: str = "[]",
) -> None:
    connection.execute(
        """
        INSERT INTO repo_analysis_snapshots (
            snapshot_date,
            repo_full_name,
            repo_url,
            analysis_depth,
            clone_strategy,
            clone_started,
            analysis_completed,
            cleanup_attempted,
            cleanup_required,
            cleanup_completed,
            fallback_used,
            root_files,
            matched_files,
            matched_keywords,
            architecture_signals,
            probe_summary,
            evidence_snippets,
            analysis_limits
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_date,
            repo_full_name,
            repo_url,
            analysis_depth,
            clone_strategy,
            clone_started,
            analysis_completed,
            cleanup_attempted,
            cleanup_required,
            cleanup_completed,
            fallback_used,
            root_files,
            matched_files,
            matched_keywords,
            architecture_signals,
            probe_summary,
            evidence_snippets,
            analysis_limits,
        ),
    )


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
        _insert_repo_capability(
            connection,
            snapshot_date="2026-03-20",
            period="daily",
            repo_full_name="acme/browser-bot",
            capability_id="browser_automation",
            confidence=0.91,
            reason="Daily trend mentions browser automation.",
            summary="Automates browser workflows.",
        )
        _insert_repo_capability(
            connection,
            snapshot_date="2026-03-20",
            period="weekly",
            repo_full_name="acme/browser-bot",
            capability_id="browser_automation",
            confidence=0.88,
            reason="Weekly trend confirms the same capability.",
            summary="Automates browser workflows.",
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
        _insert_repo_analysis_snapshot(
            connection,
            snapshot_date="2026-03-20",
            repo_full_name="acme/browser-bot",
        )
        connection.commit()

    report_dir = tmp_path / "reports"
    path = ReportService(database_url=database_url, report_dir=report_dir).generate_daily_report(date(2026, 3, 20))
    content = path.read_text(encoding="utf-8")

    assert "# 每日能力管理摘要 - 2026-03-20" in content
    assert "## 总览" in content
    assert "一句话结论：今日识别 1 个能力，暂无人工关注项，重点跟进 1 个增强候选。" in content
    assert "统计：能力 1｜人工关注 0｜新增 0｜增强候选 1｜已覆盖 0｜风险 0" in content
    assert "仓库变化：今日 2 个｜新增 2 个｜移除 1 个" in content
    assert "## 今日重点" in content
    assert "`浏览器自动化`：增强候选，优先级中，代表仓库 `acme/browser-bot`。" in content
    assert "## 能力摘要" in content
    assert "### 浏览器自动化 (`browser_automation`)" in content
    assert "状态：增强候选" in content
    assert "优先级：中" in content
    assert "代表仓库：`acme/browser-bot`" in content
    assert "判断：Automates browser workflows." in content
    assert "分析备注：分层分析；无回退；清理完成；命中文件 2 个" in content
    assert "建议：已自动归类为 POC 跟踪项；若需要推进落地再人工复核。" in content
    assert "## 产物路径" in content

    json_path = ReportService(database_url=database_url, report_dir=report_dir).generate_daily_report_json("2026-03-20")
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["report_format"] == "management-summary-v1"
    assert payload["report_date"] == "2026-03-20"
    assert payload["summary"]["total_capabilities"] == 1
    assert payload["executive_summary"]["headline"] == "今日识别 1 个能力，暂无人工关注项，重点跟进 1 个增强候选。"
    assert payload["highlights"][0]["status_label"] == "增强候选"
    assert payload["highlights"][0]["priority"] == "medium"
    assert payload["capability_cards"][0]["capability_id"] == "browser_automation"
    assert payload["capability_cards"][0]["status_label"] == "增强候选"
    assert payload["capability_cards"][0]["priority"] == "medium"
    assert payload["capability_cards"][0]["analysis"]["depth_label"] == "分层"
    assert payload["capability_cards"][0]["evidence_preview"]["matched_files_total"] == 2
    assert payload["artifact_links"]["classification_output"].endswith("classification-output.json")
    assert payload["artifact_links"]["capability_audit"].endswith("capability-audit.json")
    assert payload["artifact_links"]["taxonomy_gap_candidates"].endswith("taxonomy-gap-candidates.json")
    assert payload["repo_snapshot"]["new"] == ["acme/browser-bot", "acme/extractor"]
    assert payload["sections"]["covered"] == []
    item = payload["sections"]["enhancement_candidates"][0]
    assert item["capability_id"] == "browser_automation"
    assert item["analysis_depth"] == "layered"
    assert item["matched_files"] == ["README.md", "workflow.py"]
    assert item["fallback_used"] is False
    assert item["cleanup_completed"] is True
    assert item["evidence_snippets"][0]["path"] == "README.md"


def test_report_service_marks_fallback_analysis_in_markdown(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    initialize_schema(database_url)
    with get_connection(database_url) as connection:
        _insert_repo_capability(
            connection,
            snapshot_date="2026-03-20",
            period="daily",
            repo_full_name="acme/browser-bot",
            capability_id="browser_automation",
            confidence=0.48,
            reason="Daily trend mentions browser automation.",
            summary="Automates browser workflows.",
            needs_review=1,
        )
        _insert_repo_analysis_snapshot(
            connection,
            snapshot_date="2026-03-20",
            repo_full_name="acme/browser-bot",
            analysis_depth="fallback",
            clone_strategy="skipped-by-budget",
            cleanup_completed=0,
            fallback_used=1,
            root_files="[]",
            matched_files="[]",
            matched_keywords="[]",
            architecture_signals="[]",
            probe_summary="Deep analysis skipped because the repository budget was exhausted.",
            evidence_snippets="[]",
            analysis_limits='["skipped due to deep-analysis budget"]',
        )
        connection.commit()

    report_dir = tmp_path / "reports"
    content = ReportService(database_url=database_url, report_dir=report_dir).generate_daily_report("2026-03-20").read_text(encoding="utf-8")

    assert "状态：新能力" in content
    assert "优先级：高" in content
    assert "分析备注：回退分析；存在回退；清理未完成；命中文件 0 个" in content


def test_report_service_preserves_fallback_and_cleanup_from_sparse_joined_rows(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    initialize_schema(database_url)
    service = ReportService(database_url=database_url, report_dir=tmp_path / "reports")

    rows = [
        {
            "snapshot_date": "2026-03-20",
            "period": "daily",
            "repo_full_name": "acme/browser-bot",
            "capability_id": "browser_automation",
            "reason": "Sparse repo analysis snapshot.",
            "summary": "Automates browser workflows.",
            "base_score": 0.91,
            "needs_review": 0,
            "canonical_name": "Browser Automation",
            "registry_status": "poc",
            "first_seen_at": "2026-03-20T00:00:00Z",
            "mention_count": 1,
            "consecutive_appearances": 1,
            "analysis_depth": None,
            "fallback_used": 1,
            "cleanup_completed": 1,
            "matched_files": None,
            "evidence_snippets": None,
        }
    ]

    item = service._aggregate_rows(rows, date(2026, 3, 20))[0]

    assert item.analysis_depth == ""
    assert item.fallback_used is True
    assert item.cleanup_completed is True
    assert item.matched_files == ()
    assert item.evidence_snippets == ()


def test_report_service_handles_sparse_repo_analysis_snapshot_rows(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    initialize_schema(database_url)
    with get_connection(database_url) as connection:
        _insert_repo_capability(
            connection,
            snapshot_date="2026-03-20",
            period="daily",
            repo_full_name="acme/browser-bot",
            capability_id="browser_automation",
            confidence=0.91,
            reason="Daily trend mentions browser automation.",
            summary="Automates browser workflows.",
        )
        _insert_repo_analysis_snapshot(
            connection,
            snapshot_date="2026-03-20",
            repo_full_name="acme/browser-bot",
            analysis_depth="",
            clone_strategy="skipped-by-budget",
            cleanup_completed=1,
            cleanup_attempted=1,
            cleanup_required=1,
            fallback_used=1,
            root_files="[]",
            matched_files="[]",
            matched_keywords="[]",
            architecture_signals="[]",
            probe_summary="Sparse analysis snapshot with only fallback and cleanup state.",
            evidence_snippets="[]",
            analysis_limits="[]",
        )
        connection.commit()

    report_dir = tmp_path / "reports"
    service = ReportService(database_url=database_url, report_dir=report_dir)
    content = service.generate_daily_report("2026-03-20").read_text(encoding="utf-8")
    payload = json.loads(service.generate_daily_report_json("2026-03-20").read_text(encoding="utf-8"))

    assert "状态：新能力" in content
    assert "优先级：中" in content
    assert "分析备注：未提供分析深度；存在回退；清理完成；命中文件 0 个" in content
    assert payload["sections"]["new_capabilities"][0]["fallback_used"] is True
    assert payload["sections"]["new_capabilities"][0]["cleanup_completed"] is True
    assert payload["sections"]["new_capabilities"][0]["matched_files"] == []
    assert payload["sections"]["new_capabilities"][0]["evidence_snippets"] == []
    assert payload["capability_cards"][0]["analysis"]["depth_label"] == "_未提供_"
    assert payload["capability_cards"][0]["evidence_preview"]["matched_files_total"] == 0
