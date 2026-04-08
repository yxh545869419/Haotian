from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from haotian.db.schema import get_connection, initialize_schema
from haotian.registry.capability_registry import (
    CapabilityApproval,
    CapabilityApprovalAction,
    CapabilityRegistryRecord,
    CapabilityRegistryRepository,
    CapabilityStatus,
)
from haotian.services.codex_skill_inventory_service import InstalledSkillRecord
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


def _write_taxonomy_gap_candidates(
    run_dir,
    *,
    report_date: str,
) -> None:
    run_path = run_dir / report_date
    run_path.mkdir(parents=True, exist_ok=True)
    run_path.joinpath("taxonomy-gap-candidates.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "report_date": report_date,
                "candidates": [
                    {
                        "candidate_id": "content_generation",
                        "display_name": "Content Generation / Marketing Automation",
                        "reason": "仓库更像内容生产或营销自动化工具，当前 taxonomy 没有覆盖这一能力。",
                        "repo_full_names": ["acme/money-printer"],
                        "repo_count": 1,
                    },
                    {
                        "candidate_id": "security_analysis",
                        "display_name": "安全分析",
                        "reason": "仓库主要面向漏洞、配置错误、密钥或 SBOM 扫描，当前 taxonomy 没有对应能力。",
                        "repo_full_names": ["acme/security-scanner"],
                        "repo_count": 1,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

def _write_taxonomy_gap_candidates_payload(run_dir, *, report_date: str, payload) -> None:
    run_path = run_dir / report_date
    run_path.mkdir(parents=True, exist_ok=True)
    run_path.joinpath("taxonomy-gap-candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_skill_candidates(run_dir, *, report_date: str, payload: dict[str, object]) -> None:
    run_path = run_dir / report_date
    run_path.mkdir(parents=True, exist_ok=True)
    run_path.joinpath("skill-candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_skill_merge_decisions(run_dir, *, report_date: str, payload: dict[str, object]) -> None:
    run_path = run_dir / report_date
    run_path.mkdir(parents=True, exist_ok=True)
    run_path.joinpath("skill-merge-decisions.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class FakeInventoryService:
    def __init__(self, records: dict[str, InstalledSkillRecord]) -> None:
        self.records = records

    def scan(self) -> dict[str, InstalledSkillRecord]:
        return dict(self.records)


def _installed_skill_record(root: Path, slug: str, *, display_name: str, description: str = "") -> InstalledSkillRecord:
    skill_dir = root / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(f"# {display_name}\n\n{description}\n", encoding="utf-8")
    skill_dir.joinpath("README.md").write_text("# Readme\n", encoding="utf-8")
    return InstalledSkillRecord(
        slug=slug,
        source_root=root.resolve(),
        skill_dir=skill_dir.resolve(),
        canonical_path=skill_dir.resolve(),
        display_name=display_name,
        description=description,
        relative_path=slug,
        root_index=0,
        managed=False,
    )


def _wrapper_only_skill_record(root: Path, slug: str, *, display_name: str) -> InstalledSkillRecord:
    skill_dir = root / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(f"# {display_name}\n\nManaged wrapper generated by Haotian.\n", encoding="utf-8")
    skill_dir.joinpath("haotian-wrapper.json").write_text(
        json.dumps({"slug": slug, "source_repo_full_name": "acme/wrapper-only"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return InstalledSkillRecord(
        slug=slug,
        source_root=root.resolve(),
        skill_dir=skill_dir.resolve(),
        canonical_path=skill_dir.resolve(),
        display_name=display_name,
        description="Managed wrapper generated by Haotian.",
        relative_path=slug,
        root_index=0,
        managed=False,
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
    assert "一句话结论：今日识别 1 个能力，暂无人工关注项，重点跟进 1 个增强候选，taxonomy gap 0 类。" in content
    assert "统计：能力 1｜人工关注 0｜新增 0｜增强候选 1｜已覆盖 0｜风险 0" in content
    assert "仓库变化：今日 2 个｜新增 2 个｜移除 1 个" in content
    assert "## 今日重点" in content
    assert "`浏览器自动化`：需确认，优先级中，代表仓库 `acme/browser-bot`。" in content
    assert "## 能力摘要" in content
    assert "### 浏览器自动化 (`browser_automation`)" in content
    assert "状态：需确认" in content
    assert "优先级：中" in content
    assert "代表仓库：`acme/browser-bot`" in content
    assert "用途：Automates browser workflows." in content
    assert "分析备注：" not in content
    assert "建议：已自动归类为 POC 跟踪项；若需要推进落地再人工复核。" in content
    assert "## 产物路径" in content

    json_path = ReportService(database_url=database_url, report_dir=report_dir).generate_daily_report_json("2026-03-20")
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["report_format"] == "management-summary-v1"
    assert payload["report_date"] == "2026-03-20"
    assert payload["summary"]["total_capabilities"] == 1
    assert payload["executive_summary"]["headline"] == "今日识别 1 个能力，暂无人工关注项，重点跟进 1 个增强候选，taxonomy gap 0 类。"
    assert payload["highlights"][0]["status_label"] == "需确认"
    assert payload["highlights"][0]["priority"] == "medium"
    assert payload["capability_cards"][0]["capability_id"] == "browser_automation"
    assert payload["capability_cards"][0]["status_label"] == "需确认"
    assert payload["capability_cards"][0]["priority"] == "medium"
    assert payload["capability_cards"][0]["purpose"] == "Automates browser workflows."
    assert "note" not in payload["capability_cards"][0]["analysis"]
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


def test_report_service_switches_to_skill_summary_when_skill_artifacts_exist(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    initialize_schema(database_url)
    report_dir = tmp_path / "reports"
    run_dir = tmp_path / "runs"
    skills_root = tmp_path / "skills"
    inventory_service = FakeInventoryService(
        {
            "browser-bot": _installed_skill_record(
                skills_root,
                "browser-bot",
                display_name="Browser Bot",
                description="用于执行浏览器自动化流程。",
            ),
            "code-reviewer": _installed_skill_record(
                skills_root,
                "code-reviewer",
                display_name="Code Reviewer",
                description="用于审查代码改动。",
            ),
        }
    )
    with get_connection(database_url) as connection:
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
                ("2026-03-25", "daily", 1, "acme/browser-bot", "https://github.com/acme/browser-bot", None, None, 10, 1),
                ("2026-03-25", "daily", 2, "contoso/browser-bot", "https://github.com/contoso/browser-bot", None, None, 10, 1),
                ("2026-03-25", "daily", 3, "acme/security-audit", "https://github.com/acme/security-audit", None, None, 10, 1),
            ],
        )
        connection.commit()

    _write_skill_candidates(
        run_dir,
        report_date="2026-03-25",
        payload={
            "schema_version": 1,
            "analysis_format": "skill-discovery-v1",
            "report_date": "2026-03-25",
            "expected_output_filename": "skill-merge-decisions.json",
            "candidates": [
                {
                    "candidate_id": "cand-browser-1",
                    "slug": "browser-bot",
                    "display_name": "Browser Bot",
                    "repo_full_name": "acme/browser-bot",
                    "repo_url": "https://github.com/acme/browser-bot",
                    "relative_root": "skills/browser-bot",
                    "files": ["SKILL.md", "README.md", "settings.json"],
                    "description": "用于执行浏览器自动化流程。",
                    "matched_keywords": ["SKILL.md", "README.md"],
                    "architecture_signals": ["codex-skill-package"],
                },
                {
                    "candidate_id": "cand-browser-2",
                    "slug": "browser-bot",
                    "display_name": "Browser Bot",
                    "repo_full_name": "contoso/browser-bot",
                    "repo_url": "https://github.com/contoso/browser-bot",
                    "relative_root": "skills/browser-bot",
                    "files": ["SKILL.md", "README.md"],
                    "description": "用于执行浏览器自动化流程。",
                    "matched_keywords": ["SKILL.md", "README.md"],
                    "architecture_signals": ["codex-skill-package"],
                },
                {
                    "candidate_id": "cand-security-1",
                    "slug": "security-analysis",
                    "display_name": "Security Analysis",
                    "repo_full_name": "acme/security-audit",
                    "repo_url": "https://github.com/acme/security-audit",
                    "relative_root": "skills/security-analysis",
                    "files": ["SKILL.md", "README.md"],
                    "description": "用于执行漏洞与配置检查。",
                    "matched_keywords": ["SKILL.md"],
                    "architecture_signals": ["codex-skill-package"],
                },
            ],
        },
    )
    _write_skill_merge_decisions(
        run_dir,
        report_date="2026-03-25",
        payload={
            "schema_version": 1,
            "report_date": "2026-03-25",
            "decisions": [
                {
                    "candidate_id": "cand-browser-1",
                    "decision": "accept",
                    "canonical_name": "Browser Bot",
                    "merge_target": "browser-bot",
                    "accepted": True,
                    "reason": "与已安装 skill 对齐。",
                },
                {
                    "candidate_id": "cand-browser-2",
                    "decision": "accept",
                    "canonical_name": "Browser Bot",
                    "merge_target": "browser-bot",
                    "accepted": True,
                    "reason": "与同名 skill 合并。",
                },
                {
                    "candidate_id": "cand-security-1",
                    "decision": "review",
                    "canonical_name": "Security Analysis",
                    "merge_target": "security-analysis",
                    "accepted": False,
                    "reason": "还需要 Codex 复核。",
                },
            ],
        },
    )
    run_path = run_dir / "2026-03-25"
    run_path.joinpath("skill-sync-report.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "report_date": "2026-03-25",
                "summary": {
                    "config_ready": True,
                    "candidate_count": 2,
                    "action_count": 1,
                    "aligned_existing": 1,
                    "installed_new": 0,
                    "discarded_non_integrable": 0,
                    "blocked_audit_failure": 0,
                    "blocked_ambiguous_match": 0,
                    "rolled_back_install_failure": 0,
                },
                "actions": [
                    {
                        "action": "aligned_existing",
                        "slug": "browser-bot",
                        "display_name": "Browser Bot",
                        "source_repo_full_name": "acme/browser-bot",
                        "repo_url": "https://github.com/acme/browser-bot",
                        "relative_root": "skills/browser-bot",
                        "files": ["SKILL.md", "README.md"],
                        "matched_installed_slug": "browser-bot",
                        "matched_installed_path": str((skills_root / "browser-bot").resolve()),
                        "reason": "已对齐现有 skill。",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    service = ReportService(
        database_url=database_url,
        report_dir=report_dir,
        run_dir=run_dir,
        inventory_service=inventory_service,
    )

    markdown = service.generate_daily_report("2026-03-25").read_text(encoding="utf-8")
    payload = json.loads(service.generate_daily_report_json("2026-03-25").read_text(encoding="utf-8"))

    assert payload["report_format"] == "skill-summary-v1"
    assert payload["daily_skill_summary"]["merged_skills"] == 2
    assert payload["daily_skill_summary"]["integrated_skills"] == 1
    assert payload["daily_skill_summary"]["pending_skills"] == 1
    assert payload["daily_skill_summary"]["installed_inventory"] == 2
    merged_by_id = {item["skill_id"]: item for item in payload["merged_skill_cards"]}
    discovered_by_id = {item["skill_id"]: item for item in payload["discovered_skill_cards"]}
    assert merged_by_id["browser-bot"]["status_label"] == "已集成"
    assert merged_by_id["browser-bot"]["source_repositories"] == ["acme/browser-bot", "contoso/browser-bot"]
    assert discovered_by_id["security-analysis"]["status_label"] == "需确认"
    assert payload["installed_skill_cards"][0]["installed_paths"]
    assert "## Skill 摘要" in markdown
    assert "### Browser Bot (`browser-bot`)" in markdown
    assert "来源仓库：`acme/browser-bot`、`contoso/browser-bot`" in markdown
    assert "## 当前已集成 Skills" in markdown


def test_skill_summary_ignores_stale_wrapper_only_inventory(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    initialize_schema(database_url)
    report_dir = tmp_path / "reports"
    run_dir = tmp_path / "runs"
    stale_root = tmp_path / "old-agents" / "skills" / "haotian-managed"
    stale_record = _wrapper_only_skill_record(stale_root, "clip", display_name="clip")
    inventory_service = FakeInventoryService({"clip": stale_record})

    _write_skill_candidates(
        run_dir,
        report_date="2026-03-25",
        payload={
            "schema_version": 1,
            "analysis_format": "skill-discovery-v1",
            "report_date": "2026-03-25",
            "expected_output_filename": "skill-merge-decisions.json",
            "candidates": [
                {
                    "candidate_id": "cand-clip",
                    "slug": "clip",
                    "display_name": "clip",
                    "repo_full_name": "nousresearch/hermes-agent",
                    "repo_url": "https://github.com/nousresearch/hermes-agent",
                    "relative_root": "skills/clip",
                    "files": ["SKILL.md"],
                    "description": "用于处理 CLIP 相关工作流。",
                    "matched_keywords": ["SKILL.md"],
                    "architecture_signals": ["codex-skill-package"],
                }
            ],
        },
    )
    _write_skill_merge_decisions(
        run_dir,
        report_date="2026-03-25",
        payload={
            "schema_version": 1,
            "report_date": "2026-03-25",
            "decisions": [
                {
                    "candidate_id": "cand-clip",
                    "decision": "accept",
                    "canonical_name": "clip",
                    "merge_target": "clip",
                    "accepted": True,
                    "reason": "可落地为 Codex skill。",
                }
            ],
        },
    )
    run_path = run_dir / "2026-03-25"
    run_path.joinpath("skill-sync-report.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "report_date": "2026-03-25",
                "summary": {"config_ready": True},
                "actions": [
                    {
                        "action": "aligned_existing",
                        "slug": "clip",
                        "display_name": "clip",
                        "source_repo_full_name": "nousresearch/hermes-agent",
                        "matched_installed_slug": "clip",
                        "matched_installed_path": str(stale_record.skill_dir),
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    service = ReportService(
        database_url=database_url,
        report_dir=report_dir,
        run_dir=run_dir,
        inventory_service=inventory_service,
    )

    markdown = service.generate_daily_report("2026-03-25").read_text(encoding="utf-8")
    payload = json.loads(service.generate_daily_report_json("2026-03-25").read_text(encoding="utf-8"))

    stale_path = str(stale_record.skill_dir)
    merged_by_id = {item["skill_id"]: item for item in payload["merged_skill_cards"]}
    assert payload["daily_skill_summary"]["installed_inventory"] == 0
    assert merged_by_id["clip"]["status_label"] == "需确认"
    assert stale_path not in merged_by_id["clip"]["installed_paths"]
    assert stale_path not in markdown


def test_report_payload_includes_taxonomy_gap_summary(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    initialize_schema(database_url)
    report_dir = tmp_path / "reports"
    run_dir = tmp_path / "runs"
    service = ReportService(database_url=database_url, report_dir=report_dir, run_dir=run_dir)

    sections = {
        "summary": [],
        "manual_attention": [],
        "new_capabilities": [],
        "enhancement_candidates": [],
        "covered": [],
        "risks": [],
    }
    repo_snapshot = {
        "today": ("acme/money-printer", "acme/security-scanner"),
        "previous": (),
        "new": ("acme/money-printer", "acme/security-scanner"),
        "dropped": (),
    }
    _write_taxonomy_gap_candidates(run_dir, report_date="2026-03-25")

    payload = service._build_report_payload(date(2026, 3, 25), sections, repo_snapshot)

    assert payload["taxonomy_gap_summary"]["candidate_count"] == 2
    assert payload["taxonomy_gap_candidates"][0]["display_name"] == "Content Generation / Marketing Automation"
    assert payload["executive_summary"]["taxonomy_gap_count"] == 2
    assert payload["capability_cards"][0]["capability_id"] == "content_generation"
    assert payload["capability_cards"][0]["status_label"] == "需确认"
    assert payload["capability_cards"][0]["purpose"] == "仓库更像内容生产或营销自动化工具，当前 taxonomy 没有覆盖这一能力。"

def test_report_payload_includes_skill_sync_summary_and_actions(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    initialize_schema(database_url)
    report_dir = tmp_path / "reports"
    run_dir = tmp_path / "runs"
    service = ReportService(database_url=database_url, report_dir=report_dir, run_dir=run_dir)

    run_path = run_dir / "2026-03-25"
    run_path.mkdir(parents=True, exist_ok=True)
    run_path.joinpath("skill-sync-report.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "report_date": "2026-03-25",
                "summary": {
                    "config_ready": True,
                    "candidate_count": 1,
                    "action_count": 1,
                    "aligned_existing": 1,
                    "installed_new": 0,
                    "discarded_non_integrable": 0,
                    "blocked_audit_failure": 0,
                    "blocked_ambiguous_match": 0,
                    "rolled_back_install_failure": 0,
                },
                "actions": [
                    {
                        "action": "aligned_existing",
                        "slug": "browser-bot",
                        "display_name": "browser-bot",
                        "source_repo_full_name": "acme/browser-bot",
                        "repo_url": "https://github.com/acme/browser-bot",
                        "relative_root": ".",
                        "files": ["SKILL.md"],
                        "matched_installed_slug": "browser-bot",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = service._build_report_payload(
        date(2026, 3, 25),
        {
            "summary": [],
            "manual_attention": [],
            "new_capabilities": [],
            "enhancement_candidates": [],
            "covered": [],
            "risks": [],
        },
        {
            "today": (),
            "previous": (),
            "new": (),
            "dropped": (),
        },
    )

    assert payload["skill_sync_summary"]["aligned_existing"] == 1
    assert payload["skill_sync_actions"][0]["action"] == "aligned_existing"
    assert payload["artifact_links"]["skill_sync_report"].endswith("skill-sync-report.json")


def test_report_service_marks_capability_as_integrated_when_skill_sync_aligned(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    initialize_schema(database_url)
    report_dir = tmp_path / "reports"
    run_dir = tmp_path / "runs"
    repository = CapabilityRegistryRepository(database_url=database_url)
    repository.upsert_capability(
        CapabilityRegistryRecord(
            capability_id="browser_automation",
            canonical_name="Browser Automation",
            status=CapabilityStatus.ACTIVE,
            summary="Automates browser workflows.",
            first_seen_at="2026-03-20T00:00:00Z",
            last_seen_at="2026-03-20T00:00:00Z",
            last_score=0.95,
            mention_count=3,
            consecutive_appearances=3,
            source_repo_full_name="acme/browser-bot",
        )
    )
    with get_connection(database_url) as connection:
        _insert_repo_capability(
            connection,
            snapshot_date="2026-03-20",
            period="daily",
            repo_full_name="acme/browser-bot",
            capability_id="browser_automation",
            confidence=0.95,
            reason="Daily trend mentions browser automation.",
            summary="Automates browser workflows.",
        )
        _insert_repo_analysis_snapshot(
            connection,
            snapshot_date="2026-03-20",
            repo_full_name="acme/browser-bot",
        )
        connection.execute(
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
            ("2026-03-20", "daily", 1, "acme/browser-bot", "https://github.com/acme/browser-bot", None, None, 10, 1),
        )
        connection.commit()

    run_path = run_dir / "2026-03-20"
    run_path.mkdir(parents=True, exist_ok=True)
    run_path.joinpath("skill-sync-report.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "report_date": "2026-03-20",
                "summary": {
                    "config_ready": True,
                    "candidate_count": 1,
                    "action_count": 1,
                    "aligned_existing": 1,
                    "installed_new": 0,
                    "discarded_non_integrable": 0,
                    "blocked_audit_failure": 0,
                    "blocked_ambiguous_match": 0,
                    "rolled_back_install_failure": 0,
                },
                "actions": [
                    {
                        "action": "aligned_existing",
                        "slug": "browser-bot",
                        "display_name": "browser-bot",
                        "source_repo_full_name": "acme/browser-bot",
                        "repo_url": "https://github.com/acme/browser-bot",
                        "relative_root": ".",
                        "files": ["SKILL.md"],
                        "matched_installed_slug": "browser-bot",
                        "capability_ids": ["browser_automation"],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = ReportService(database_url=database_url, report_dir=report_dir, run_dir=run_dir).generate_daily_report_json("2026-03-20")
    report = json.loads(payload.read_text(encoding="utf-8"))

    assert report["capability_cards"][0]["status_label"] == "已集成"
    assert report["highlights"][0]["status_label"] == "已集成"


@pytest.mark.parametrize(
    ("payload", "description"),
    [
        ("not-json", "malformed json"),
        (["unexpected-root"], "wrong root type"),
    ],
)
def test_report_payload_treats_invalid_taxonomy_gap_file_as_empty(tmp_path, payload, description) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    initialize_schema(database_url)
    report_dir = tmp_path / "reports"
    run_dir = tmp_path / "runs"
    service = ReportService(database_url=database_url, report_dir=report_dir, run_dir=run_dir)

    if isinstance(payload, str):
        run_path = run_dir / "2026-03-25"
        run_path.mkdir(parents=True, exist_ok=True)
        run_path.joinpath("taxonomy-gap-candidates.json").write_text(payload, encoding="utf-8")
    else:
        _write_taxonomy_gap_candidates_payload(run_dir, report_date="2026-03-25", payload=payload)

    sections = {
        "summary": [],
        "manual_attention": [],
        "new_capabilities": [],
        "enhancement_candidates": [],
        "covered": [],
        "risks": [],
    }
    repo_snapshot = {
        "today": (),
        "previous": (),
        "new": (),
        "dropped": (),
    }

    payload = service._build_report_payload(date(2026, 3, 25), sections, repo_snapshot)

    assert payload["taxonomy_gap_candidates"] == []
    assert payload["taxonomy_gap_summary"]["candidate_count"] == 0
    assert payload["executive_summary"]["taxonomy_gap_count"] == 0


def test_report_payload_normalizes_taxonomy_gap_repo_count_from_repo_names(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    initialize_schema(database_url)
    report_dir = tmp_path / "reports"
    run_dir = tmp_path / "runs"
    service = ReportService(database_url=database_url, report_dir=report_dir, run_dir=run_dir)

    _write_taxonomy_gap_candidates_payload(
        run_dir,
        report_date="2026-03-25",
        payload={
            "schema_version": 1,
            "report_date": "2026-03-25",
            "candidates": [
                {
                    "candidate_id": "content_generation",
                    "display_name": "Content Generation / Marketing Automation",
                    "reason": "仓库更像内容生产或营销自动化工具，当前 taxonomy 没有覆盖这一能力。",
                    "repo_full_names": ["acme/money-printer", "acme/newsletter-bot"],
                    "repo_count": 999,
                }
            ],
        },
    )

    sections = {
        "summary": [],
        "manual_attention": [],
        "new_capabilities": [],
        "enhancement_candidates": [],
        "covered": [],
        "risks": [],
    }
    repo_snapshot = {
        "today": (),
        "previous": (),
        "new": (),
        "dropped": (),
    }

    payload = service._build_report_payload(date(2026, 3, 25), sections, repo_snapshot)

    assert payload["taxonomy_gap_candidates"][0]["repo_count"] == 2
    assert payload["taxonomy_gap_summary"]["repo_count"] == 2


def test_report_payload_skips_bad_taxonomy_gap_candidate_entries(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    initialize_schema(database_url)
    report_dir = tmp_path / "reports"
    run_dir = tmp_path / "runs"
    service = ReportService(database_url=database_url, report_dir=report_dir, run_dir=run_dir)

    _write_taxonomy_gap_candidates_payload(
        run_dir,
        report_date="2026-03-25",
        payload={
            "schema_version": 1,
            "report_date": "2026-03-25",
            "candidates": [
                "not-a-dict",
                {
                    "candidate_id": "broken_entry",
                    "display_name": "坏条目",
                    "reason": "This entry is malformed.",
                    "repo_full_names": None,
                    "repo_count": "invalid",
                },
            ],
        },
    )

    sections = {
        "summary": [],
        "manual_attention": [],
        "new_capabilities": [],
        "enhancement_candidates": [],
        "covered": [],
        "risks": [],
    }
    repo_snapshot = {
        "today": (),
        "previous": (),
        "new": (),
        "dropped": (),
    }

    payload = service._build_report_payload(date(2026, 3, 25), sections, repo_snapshot)

    assert payload["taxonomy_gap_candidates"] == []
    assert payload["taxonomy_gap_summary"]["candidate_count"] == 0


def test_markdown_renders_taxonomy_gap_section(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    initialize_schema(database_url)
    report_dir = tmp_path / "reports"
    run_dir = tmp_path / "runs"
    service = ReportService(database_url=database_url, report_dir=report_dir, run_dir=run_dir)

    sections = {
        "summary": [],
        "manual_attention": [],
        "new_capabilities": [],
        "enhancement_candidates": [],
        "covered": [],
        "risks": [],
    }
    repo_snapshot = {
        "today": ("acme/money-printer", "acme/security-scanner"),
        "previous": (),
        "new": ("acme/money-printer", "acme/security-scanner"),
        "dropped": (),
    }
    _write_taxonomy_gap_candidates(run_dir, report_date="2026-03-25")
    payload = service._build_report_payload(date(2026, 3, 25), sections, repo_snapshot)

    markdown = service._render_markdown(date(2026, 3, 25), payload)
    assert "## Taxonomy Gap 候选" in markdown
    assert "Content Generation / Marketing Automation" in markdown
    assert "taxonomy gap 2 类" in markdown
    assert "## 能力摘要" in markdown
    assert "### Content Generation / Marketing Automation (`content_generation`)" in markdown
    assert "用途：仓库更像内容生产或营销自动化工具，当前 taxonomy 没有覆盖这一能力。" in markdown


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

    assert "状态：需确认" in content
    assert "优先级：高" in content
    assert "分析备注：" not in content


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

    assert "状态：需确认" in content
    assert "优先级：中" in content
    assert "分析备注：" not in content
    assert payload["sections"]["new_capabilities"][0]["fallback_used"] is True
    assert payload["sections"]["new_capabilities"][0]["cleanup_completed"] is True
    assert payload["sections"]["new_capabilities"][0]["matched_files"] == []
    assert payload["sections"]["new_capabilities"][0]["evidence_snippets"] == []
    assert payload["capability_cards"][0]["analysis"]["depth_label"] == "_未提供_"
    assert payload["capability_cards"][0]["evidence_preview"]["matched_files_total"] == 0
