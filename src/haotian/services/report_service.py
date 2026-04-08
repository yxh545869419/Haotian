"""Daily capability reporting helpers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import json
import sqlite3
from pathlib import Path
import re

from haotian.config import get_settings
from haotian.db.schema import get_connection, initialize_schema
from haotian.registry.capability_registry import CapabilityStatus
from haotian.services.classification_artifact_service import ClassificationArtifactService
from haotian.services.codex_skill_inventory_service import CodexSkillInventoryService, InstalledSkillRecord


@dataclass(frozen=True, slots=True)
class ReportEvidenceSnippet:
    path: str
    excerpt: str
    why_it_matters: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "excerpt": self.excerpt,
            "why_it_matters": self.why_it_matters,
        }


@dataclass(frozen=True, slots=True)
class ReportItem:
    capability_id: str
    canonical_name: str
    display_name: str
    analysis_depth: str
    matched_files: tuple[str, ...]
    evidence_snippets: tuple[ReportEvidenceSnippet, ...]
    fallback_used: bool
    cleanup_completed: bool
    source_repos: tuple[str, ...]
    periods: tuple[str, ...]
    reason: str
    suggestion: str
    base_score: float
    summary: str
    status: str
    repo_count: int
    needs_manual_attention: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "canonical_name": self.canonical_name,
            "display_name": self.display_name,
            "analysis_depth": self.analysis_depth,
            "matched_files": list(self.matched_files),
            "evidence_snippets": [snippet.to_dict() for snippet in self.evidence_snippets],
            "fallback_used": self.fallback_used,
            "cleanup_completed": self.cleanup_completed,
            "source_repos": list(self.source_repos),
            "periods": list(self.periods),
            "reason": self.reason,
            "suggestion": self.suggestion,
            "base_score": self.base_score,
            "summary": self.summary,
            "status": self.status,
            "repo_count": self.repo_count,
            "needs_manual_attention": self.needs_manual_attention,
        }


class ReportService:
    """Generate daily markdown reports from collected capability data."""

    def __init__(
        self,
        database_url: str | None = None,
        report_dir: Path | None = None,
        run_dir: Path | None = None,
        inventory_service: CodexSkillInventoryService | None = None,
    ) -> None:
        settings = get_settings()
        self.database_url = database_url
        self.report_dir = report_dir or settings.report_dir
        if run_dir is not None:
            self.run_dir = run_dir
        elif report_dir is not None:
            self.run_dir = report_dir.parent / "runs"
        else:
            self.run_dir = settings.run_dir
        self.inventory_service = inventory_service or CodexSkillInventoryService()

    def generate_daily_report(self, report_date: date | str) -> Path:
        target_date = self._normalize_date(report_date)
        initialize_schema(self.database_url)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        sections = self._load_sections(target_date)
        repo_snapshot = self._load_repo_snapshot(target_date)
        payload = self._build_report_payload(target_date, sections, repo_snapshot)
        report_path = self.report_dir / f"{target_date.isoformat()}.md"
        report_path.write_text(self._render_markdown(target_date, payload), encoding="utf-8")
        return report_path

    def generate_daily_report_json(self, report_date: date | str) -> Path:
        target_date = self._normalize_date(report_date)
        initialize_schema(self.database_url)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        sections = self._load_sections(target_date)
        repo_snapshot = self._load_repo_snapshot(target_date)
        payload = self._build_report_payload(target_date, sections, repo_snapshot)
        report_path = self.report_dir / f"{target_date.isoformat()}.json"
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return report_path

    def _load_sections(self, target_date: date) -> dict[str, list[ReportItem]]:
        with get_connection(self.database_url) as connection:
            rows = connection.execute(
                """
                SELECT
                    rc.snapshot_date AS snapshot_date,
                    rc.period AS period,
                    rc.repo_full_name AS repo_full_name,
                    rc.capability_id AS capability_id,
                    rc.reason AS reason,
                    rc.summary AS summary,
                    rc.confidence AS base_score,
                    rc.needs_review AS needs_review,
                    COALESCE(cr.canonical_name, rc.capability_id) AS canonical_name,
                    COALESCE(cr.status, 'pending_review') AS registry_status,
                    COALESCE(cr.first_seen_at, rc.created_at) AS first_seen_at,
                    COALESCE(cr.mention_count, 1) AS mention_count,
                    COALESCE(cr.consecutive_appearances, 1) AS consecutive_appearances,
                    ra.analysis_depth AS analysis_depth,
                    ra.fallback_used AS fallback_used,
                    ra.cleanup_completed AS cleanup_completed,
                    ra.matched_files AS matched_files,
                    ra.evidence_snippets AS evidence_snippets
                FROM repo_capabilities rc
                LEFT JOIN capability_registry cr ON cr.capability_id = rc.capability_id
                LEFT JOIN repo_analysis_snapshots ra
                    ON ra.snapshot_date = rc.snapshot_date
                   AND ra.repo_full_name = rc.repo_full_name
                WHERE rc.snapshot_date = ?
                ORDER BY rc.confidence DESC, rc.capability_id ASC, rc.repo_full_name ASC
                """,
                (target_date.isoformat(),),
            ).fetchall()
        items = self._aggregate_rows(rows, target_date)
        manual_attention = [item for item in items if item.needs_manual_attention]
        return {
            "summary": items,
            "manual_attention": manual_attention,
            "new_capabilities": [item for item in items if item.status == "new_capabilities"],
            "enhancement_candidates": [item for item in items if item.status == "enhancement_candidates"],
            "covered": [item for item in items if item.status == "covered"],
            "risks": [item for item in items if item.status == "risks"],
        }

    def _load_repo_snapshot(self, target_date: date) -> dict[str, tuple[str, ...]]:
        with get_connection(self.database_url) as connection:
            today_rows = connection.execute(
                "SELECT DISTINCT repo_full_name FROM trending_repos WHERE snapshot_date = ? ORDER BY repo_full_name ASC",
                (target_date.isoformat(),),
            ).fetchall()
            previous_date = connection.execute(
                "SELECT MAX(snapshot_date) AS snapshot_date FROM trending_repos WHERE snapshot_date < ?",
                (target_date.isoformat(),),
            ).fetchone()["snapshot_date"]
            previous_rows = []
            if previous_date:
                previous_rows = connection.execute(
                    "SELECT DISTINCT repo_full_name FROM trending_repos WHERE snapshot_date = ? ORDER BY repo_full_name ASC",
                    (previous_date,),
                ).fetchall()
        today = tuple(row["repo_full_name"] for row in today_rows)
        previous = tuple(row["repo_full_name"] for row in previous_rows)
        today_set = set(today)
        previous_set = set(previous)
        return {
            "today": today,
            "previous": previous,
            "new": tuple(sorted(today_set - previous_set)),
            "dropped": tuple(sorted(previous_set - today_set)),
        }

    def _aggregate_rows(self, rows: list[sqlite3.Row], target_date: date) -> list[ReportItem]:
        grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            grouped[str(row["capability_id"])].append(row)

        items: list[ReportItem] = []
        for capability_id, group_rows in grouped.items():
            primary = max(group_rows, key=lambda row: float(row["base_score"]))
            registry_status = str(primary["registry_status"])
            first_seen = str(primary["first_seen_at"])[:10]
            mention_count = int(primary["mention_count"])
            consecutive = int(primary["consecutive_appearances"])
            needs_review = any(bool(row["needs_review"]) for row in group_rows)
            repo_names = tuple(sorted({str(row["repo_full_name"]) for row in group_rows}))
            periods = tuple(sorted({str(row["period"]) for row in group_rows}))
            max_score = max(float(row["base_score"]) for row in group_rows)
            snapshot_rows = [
                row
                for row in group_rows
                if row["analysis_depth"] is not None
                or row["matched_files"] is not None
                or row["evidence_snippets"] is not None
                or row["fallback_used"] is not None
                or row["cleanup_completed"] is not None
            ]
            analysis_depth = self._collect_analysis_depth(group_rows)
            matched_files = self._collect_matched_files(group_rows)
            evidence_snippets = self._collect_evidence_snippets(group_rows)
            fallback_used = any(bool(row["fallback_used"]) for row in snapshot_rows)
            cleanup_completed = all(bool(row["cleanup_completed"]) for row in snapshot_rows) if snapshot_rows else False
            reason = " | ".join(dict.fromkeys(str(row["reason"]) for row in group_rows))
            summary = " ".join(dict.fromkeys(str(row["summary"]) for row in group_rows))
            bucket, suggestion, needs_manual_attention = self._choose_bucket(
                registry_status=registry_status,
                first_seen=first_seen,
                target_date=target_date,
                mention_count=mention_count,
                consecutive=consecutive,
                needs_review=needs_review,
                base_score=max_score,
            )
            items.append(
                ReportItem(
                    capability_id=capability_id,
                    canonical_name=str(primary["canonical_name"]),
                    display_name=self._localize_capability_name(capability_id, str(primary["canonical_name"])),
                    analysis_depth=analysis_depth,
                    matched_files=matched_files,
                    evidence_snippets=evidence_snippets,
                    fallback_used=fallback_used,
                    cleanup_completed=cleanup_completed,
                    source_repos=repo_names,
                    periods=periods,
                    reason=reason,
                    suggestion=suggestion,
                    base_score=max_score,
                    summary=summary,
                    status=bucket,
                    repo_count=len(repo_names),
                    needs_manual_attention=needs_manual_attention,
                )
            )
        return sorted(items, key=lambda item: (-item.base_score, item.capability_id))

    @staticmethod
    def _choose_bucket(
        *,
        registry_status: str,
        first_seen: str,
        target_date: date,
        mention_count: int,
        consecutive: int,
        needs_review: bool,
        base_score: float,
    ) -> tuple[str, str, bool]:
        if registry_status == CapabilityStatus.ACTIVE.value and not needs_review:
            return "covered", "已自动归类为活跃能力，继续跟踪后续变化。", False
        if registry_status == CapabilityStatus.POC.value:
            return "enhancement_candidates", "已自动归类为 POC 跟踪项；若需要推进落地再人工复核。", needs_review
        if registry_status == CapabilityStatus.WATCHLIST.value:
            return "new_capabilities", "已自动加入观察清单；除非下方标记需要人工关注，否则可继续观察。", needs_review
        if registry_status == CapabilityStatus.DEPRECATED.value:
            return "risks", "由于置信度较低，已自动归类为忽略/弃用；仅在你认为重要时再人工核验。", True

        needs_manual_attention = needs_review or base_score < 0.6
        if first_seen == target_date.isoformat() and mention_count == 1 and consecutive <= 1:
            return "new_capabilities", "已根据今日证据自动归类；若置信度偏弱，请关注人工标记。", needs_manual_attention
        return "enhancement_candidates", "已根据重复信号与置信度自动归类。", needs_manual_attention

    def _render_markdown(
        self,
        target_date: date,
        payload: dict[str, object],
    ) -> str:
        if payload.get("report_format") == "skill-summary-v1":
            return self._render_skill_markdown(target_date, payload)

        summary = payload["summary"]
        executive_summary = payload["executive_summary"]
        highlights = payload["highlights"]
        capability_cards = payload["capability_cards"]
        taxonomy_gap_candidates = payload["taxonomy_gap_candidates"]
        artifact_links = payload["artifact_links"]
        repo_changes = executive_summary["repo_changes"]
        lines = [
            f"# 每日能力管理摘要 - {target_date.isoformat()}",
            "",
            "## 总览",
            "",
            f"一句话结论：{executive_summary['headline']}",
            (
                "统计："
                f"能力 {summary['total_capabilities']}｜"
                f"人工关注 {summary['manual_attention']}｜"
                f"新增 {summary['new_capabilities']}｜"
                f"增强候选 {summary['enhancement_candidates']}｜"
                f"已覆盖 {summary['covered']}｜"
                f"风险 {summary['risks']}｜"
                f"taxonomy gap {executive_summary['taxonomy_gap_count']} 类"
            ),
            (
                "仓库变化："
                f"今日 {repo_changes['today']} 个｜"
                f"新增 {repo_changes['new']} 个｜"
                f"移除 {repo_changes['dropped']} 个"
            ),
            "",
            "## 今日重点",
            "",
        ]
        if highlights:
            for highlight in highlights:
                lines.append(
                    f"- `{highlight['display_name']}`："
                    f"{highlight['status_label']}，"
                    f"优先级{highlight['priority_label']}，"
                    f"代表仓库 {self._render_repo_list(tuple(highlight['representative_repos']))}。"
                )
        else:
            lines.append("_今日暂无重点事项。_")
        lines.extend(["", "## 能力摘要", ""])
        if capability_cards:
            for card in capability_cards:
                lines.extend(
                    [
                        f"### {card['display_name']} (`{card['capability_id']}`)",
                        f"状态：{card['status_label']}",
                        f"优先级：{card['priority_label']}",
                        f"代表仓库：{self._render_repo_list(tuple(card['representative_repos']))}",
                        f"用途：{card['purpose']}",
                        f"建议：{card['suggestion']}",
                        "",
                    ]
                )
        else:
            lines.extend(["_今日未识别到能力项。_", ""])
        lines.extend(["", "## Taxonomy Gap 候选", ""])
        if taxonomy_gap_candidates:
            for candidate in taxonomy_gap_candidates:
                repo_text = self._render_repo_list(tuple(candidate["repo_full_names"]))
                lines.append(
                    f"- `{candidate['display_name']}`：涉及 {candidate['repo_count']} 个 repo，代表仓库 {repo_text}。"
                )
                lines.append(f"  原因：{candidate['reason']}")
        else:
            lines.append("_今日未识别到 taxonomy gap 候选。_")
        lines.append("")
        lines.extend(
            [
                "## 产物路径",
                "",
                f"- Markdown 报告：`{artifact_links['markdown_report']}`",
                f"- JSON 报告：`{artifact_links['json_report']}`",
                f"- 分类输入：`{artifact_links['classification_input']}`",
                f"- 分类输出：`{artifact_links['classification_output']}`",
                f"- 运行摘要：`{artifact_links['run_summary']}`",
            ]
        )
        return "\n".join(lines).strip() + "\n"

    def _build_report_payload(
        self,
        target_date: date,
        sections: dict[str, list[ReportItem]],
        repo_snapshot: dict[str, tuple[str, ...]],
    ) -> dict[str, object]:
        if self._has_skill_summary_artifacts(target_date):
            return self._build_skill_report_payload(target_date, repo_snapshot)

        skill_sync_payload = self._load_skill_sync_report(target_date)
        summary = {
            "total_capabilities": len(sections["summary"]),
            "manual_attention": len(sections["manual_attention"]),
            "new_capabilities": len(sections["new_capabilities"]),
            "enhancement_candidates": len(sections["enhancement_candidates"]),
            "covered": len(sections["covered"]),
            "risks": len(sections["risks"]),
        }
        highlight_items = sorted(sections["summary"], key=self._highlight_sort_key)[:5]
        taxonomy_gap_candidates = self._load_taxonomy_gap_candidates(target_date)
        integrated_capability_ids = self._collect_integrated_capability_ids(skill_sync_payload)
        cards = [
            *[self._build_capability_card(item, integrated_capability_ids) for item in sections["summary"]],
            *[self._build_taxonomy_gap_card(candidate) for candidate in taxonomy_gap_candidates],
        ]
        taxonomy_gap_summary = {
            "candidate_count": len(taxonomy_gap_candidates),
            "repo_count": sum(candidate["repo_count"] for candidate in taxonomy_gap_candidates),
        }
        return {
            "report_format": "management-summary-v1",
            "report_date": target_date.isoformat(),
            "summary": summary,
            "repo_snapshot": {key: list(value) for key, value in repo_snapshot.items()},
            "sections": {
                key: [item.to_dict() for item in items]
                for key, items in sections.items()
                if key != "summary"
            },
            "executive_summary": {
                "headline": self._build_headline(summary, taxonomy_gap_summary["candidate_count"]),
                "counts": summary,
                "taxonomy_gap_count": taxonomy_gap_summary["candidate_count"],
                "repo_changes": {
                    "today": len(repo_snapshot["today"]),
                    "new": len(repo_snapshot["new"]),
                    "dropped": len(repo_snapshot["dropped"]),
                },
            },
            "highlights": [self._build_highlight_entry(item, integrated_capability_ids) for item in highlight_items],
            "capability_cards": cards,
            "taxonomy_gap_summary": taxonomy_gap_summary,
            "taxonomy_gap_candidates": taxonomy_gap_candidates,
            "skill_sync_summary": skill_sync_payload["summary"],
            "skill_sync_actions": skill_sync_payload["actions"],
            "artifact_links": self._build_artifact_links(target_date),
        }

    @staticmethod
    def _build_headline(summary: dict[str, int], taxonomy_gap_count: int = 0) -> str:
        manual_attention = (
            f"{summary['manual_attention']} 个需要人工关注"
            if summary["manual_attention"]
            else "暂无人工关注项"
        )
        return (
            f"今日识别 {summary['total_capabilities']} 个能力，"
            f"{manual_attention}，"
            f"重点跟进 {summary['enhancement_candidates']} 个增强候选，"
            f"taxonomy gap {taxonomy_gap_count} 类。"
        )

    def _build_capability_card(self, item: ReportItem, integrated_capability_ids: set[str]) -> dict[str, object]:
        priority = self._priority_for_item(item)
        representative_repos = list(item.source_repos[:3])
        integration_status = self._integration_status_for_item(item, integrated_capability_ids)
        return {
            "capability_id": item.capability_id,
            "canonical_name": item.canonical_name,
            "display_name": item.display_name,
            "status": integration_status,
            "status_label": self._localize_status(integration_status),
            "taxonomy_status": item.status,
            "taxonomy_status_label": self._localize_taxonomy_status(item.status),
            "priority": priority,
            "priority_label": self._localize_priority(priority),
            "needs_manual_attention": item.needs_manual_attention,
            "repo_count": item.repo_count,
            "representative_repos": representative_repos,
            "source_repos": list(item.source_repos),
            "periods": list(item.periods),
            "periods_label": self._localize_periods(item.periods),
            "reason": item.reason,
            "summary": item.summary,
            "purpose": item.summary or item.reason or "_无_",
            "suggestion": item.suggestion,
            "base_score": item.base_score,
            "analysis": {
                "depth": item.analysis_depth,
                "depth_label": self._localize_analysis_depth(item.analysis_depth),
                "fallback_used": item.fallback_used,
                "cleanup_completed": item.cleanup_completed,
            },
            "evidence_preview": {
                "matched_files_total": len(item.matched_files),
                "matched_files_preview": list(item.matched_files[:3]),
                "snippet_count": len(item.evidence_snippets),
                "snippets": [snippet.to_dict() for snippet in item.evidence_snippets[:2]],
            },
        }

    def _build_highlight_entry(self, item: ReportItem, integrated_capability_ids: set[str]) -> dict[str, object]:
        priority = self._priority_for_item(item)
        integration_status = self._integration_status_for_item(item, integrated_capability_ids)
        return {
            "capability_id": item.capability_id,
            "display_name": item.display_name,
            "status": integration_status,
            "status_label": self._localize_status(integration_status),
            "taxonomy_status": item.status,
            "taxonomy_status_label": self._localize_taxonomy_status(item.status),
            "priority": priority,
            "priority_label": self._localize_priority(priority),
            "needs_manual_attention": item.needs_manual_attention,
            "representative_repos": list(item.source_repos[:3]),
            "summary": item.summary,
        }

    def _build_taxonomy_gap_card(self, candidate: dict[str, object]) -> dict[str, object]:
        repo_full_names = tuple(
            str(repo).strip()
            for repo in candidate.get("repo_full_names", ())
            if str(repo).strip()
        )
        priority = "high" if len(repo_full_names) >= 3 else "medium"
        reason = str(candidate.get("reason", "")).strip()
        capability_id = str(candidate.get("candidate_id", "")).strip()
        display_name = str(candidate.get("display_name", capability_id)).strip() or capability_id
        return {
            "capability_id": capability_id,
            "canonical_name": display_name,
            "display_name": display_name,
            "status": "pending_confirmation",
            "status_label": self._localize_status("pending_confirmation"),
            "taxonomy_status": "taxonomy_gap",
            "taxonomy_status_label": self._localize_taxonomy_status("taxonomy_gap"),
            "priority": priority,
            "priority_label": self._localize_priority(priority),
            "needs_manual_attention": True,
            "repo_count": len(repo_full_names),
            "representative_repos": list(repo_full_names[:3]),
            "source_repos": list(repo_full_names),
            "periods": [],
            "periods_label": "_无_",
            "reason": reason,
            "summary": "",
            "purpose": reason or "_无_",
            "suggestion": "当前 taxonomy 尚未覆盖该能力，建议确认是否扩展 taxonomy 并评估是否需要新建 skill。",
            "base_score": float(len(repo_full_names)),
            "analysis": {
                "depth": "",
                "depth_label": "_未提供_",
                "fallback_used": False,
                "cleanup_completed": True,
            },
            "evidence_preview": {
                "matched_files_total": 0,
                "matched_files_preview": [],
                "snippet_count": 0,
                "snippets": [],
            },
        }

    def _build_artifact_links(self, target_date: date) -> dict[str, str]:
        report_label = target_date.isoformat()
        run_base = self.run_dir / report_label
        return {
            "markdown_report": str(self.report_dir / f"{report_label}.md"),
            "json_report": str(self.report_dir / f"{report_label}.json"),
            "classification_input": str(run_base / "classification-input.json"),
            "classification_output": str(run_base / "classification-output.json"),
            "skill_candidates": str(run_base / "skill-candidates.json"),
            "skill_merge_decisions": str(run_base / "skill-merge-decisions.json"),
            "run_summary": str(run_base / "run-summary.json"),
            "capability_audit": str(run_base / "capability-audit.json"),
            "taxonomy_gap_candidates": str(run_base / "taxonomy-gap-candidates.json"),
            "skill_sync_report": str(run_base / "skill-sync-report.json"),
        }

    def _has_skill_summary_artifacts(self, target_date: date) -> bool:
        run_path = self.run_dir / target_date.isoformat()
        return run_path.joinpath("skill-candidates.json").exists() and run_path.joinpath("skill-merge-decisions.json").exists()

    def _build_skill_report_payload(
        self,
        target_date: date,
        repo_snapshot: dict[str, tuple[str, ...]],
    ) -> dict[str, object]:
        skill_sync_payload = self._load_skill_sync_report(target_date)
        installed_inventory = self._load_installed_skill_inventory()
        skill_candidates = self._load_skill_candidates(target_date)
        decisions = self._load_skill_merge_decisions(target_date)
        merged_skill_cards, discovered_skill_cards = self._build_daily_skill_cards(
            target_date=target_date,
            skill_candidates=skill_candidates,
            decisions=decisions,
            skill_sync_payload=skill_sync_payload,
            installed_inventory=installed_inventory,
        )
        installed_skill_cards = [
            self._build_installed_skill_card(record)
            for record in sorted(installed_inventory.values(), key=lambda item: item.display_name.casefold())
        ]
        integrated_count = sum(1 for card in merged_skill_cards if card["status"] == "integrated")
        pending_count = sum(1 for card in merged_skill_cards if card["status"] == "pending_confirmation")
        summary = {
            "merged_skills": len(merged_skill_cards),
            "integrated_skills": integrated_count,
            "pending_skills": pending_count,
            "installed_inventory": len(installed_skill_cards),
        }
        highlights = sorted(merged_skill_cards, key=self._skill_highlight_sort_key)[:5]
        return {
            "report_format": "skill-summary-v1",
            "report_date": target_date.isoformat(),
            "daily_skill_summary": summary,
            "repo_snapshot": {key: list(value) for key, value in repo_snapshot.items()},
            "executive_summary": {
                "headline": (
                    f"今日整理 {summary['merged_skills']} 个相关 skill，"
                    f"其中已集成 {summary['integrated_skills']} 个，"
                    f"待确认 {summary['pending_skills']} 个，"
                    f"当前 Codex 基线已装 {summary['installed_inventory']} 个 skill。"
                ),
                "repo_changes": {
                    "today": len(repo_snapshot["today"]),
                    "new": len(repo_snapshot["new"]),
                    "dropped": len(repo_snapshot["dropped"]),
                },
            },
            "highlights": highlights,
            "merged_skill_cards": merged_skill_cards,
            "discovered_skill_cards": discovered_skill_cards,
            "installed_skill_cards": installed_skill_cards,
            "skill_sync_summary": skill_sync_payload["summary"],
            "skill_sync_actions": skill_sync_payload["actions"],
            "artifact_links": self._build_artifact_links(target_date),
        }

    def _render_skill_markdown(
        self,
        target_date: date,
        payload: dict[str, object],
    ) -> str:
        summary = payload["daily_skill_summary"]
        executive_summary = payload["executive_summary"]
        highlights = payload["highlights"]
        merged_skill_cards = payload["merged_skill_cards"]
        installed_skill_cards = payload["installed_skill_cards"]
        artifact_links = payload["artifact_links"]
        repo_changes = executive_summary["repo_changes"]
        lines = [
            f"# 每日 Skill 管理摘要 - {target_date.isoformat()}",
            "",
            "## 总览",
            "",
            f"一句话结论：{executive_summary['headline']}",
            (
                "统计："
                f"相关 skill {summary['merged_skills']}｜"
                f"已集成 {summary['integrated_skills']}｜"
                f"需确认 {summary['pending_skills']}｜"
                f"当前已集成 {summary['installed_inventory']}"
            ),
            (
                "仓库变化："
                f"今日 {repo_changes['today']} 个｜"
                f"新增 {repo_changes['new']} 个｜"
                f"移除 {repo_changes['dropped']} 个"
            ),
            "",
            "## 今日重点",
            "",
        ]
        if highlights:
            for card in highlights:
                lines.append(
                    f"- `{card['display_name']}`：{card['status_label']}，来源仓库 {self._render_repo_list(tuple(card['source_repositories']))}。"
                )
        else:
            lines.append("_今日暂无重点 skill。_")
        lines.extend(["", "## Skill 摘要", ""])
        if merged_skill_cards:
            for card in merged_skill_cards:
                installed_paths = tuple(card["installed_paths"])
                lines.extend(
                    [
                        f"### {card['display_name']} (`{card['skill_id']}`)",
                        f"状态：{card['status_label']}",
                        f"来源仓库：{self._render_repo_list(tuple(card['source_repositories']))}",
                        f"用途：{card['purpose']}",
                        f"已集成位置：{self._render_path_list(installed_paths)}",
                        (
                            "合并来源："
                            + (", ".join(f"`{value}`" for value in card["merged_from"]) if card["merged_from"] else "_无_")
                        ),
                        "",
                    ]
                )
        else:
            lines.extend(["_今日未发现 skill 候选。_", ""])
        lines.extend(["", "## 当前已集成 Skills", ""])
        if installed_skill_cards:
            for card in installed_skill_cards:
                lines.extend(
                    [
                        f"### {card['display_name']} (`{card['skill_id']}`)",
                        f"状态：{card['status_label']}",
                        f"用途：{card['purpose']}",
                        f"已集成位置：{self._render_path_list(tuple(card['installed_paths']))}",
                        "",
                    ]
                )
        else:
            lines.extend(["_当前未扫描到可用的已安装 skill。_", ""])
        lines.extend(
            [
                "## 产物路径",
                "",
                f"- Markdown 报告：`{artifact_links['markdown_report']}`",
                f"- JSON 报告：`{artifact_links['json_report']}`",
                f"- Skill 候选：`{artifact_links['skill_candidates']}`",
                f"- Landing 决策：`{artifact_links['skill_merge_decisions']}`",
                f"- Skill Sync：`{artifact_links['skill_sync_report']}`",
                f"- 运行摘要：`{artifact_links['run_summary']}`",
            ]
        )
        return "\n".join(lines).strip() + "\n"

    def _load_installed_skill_inventory(self) -> dict[str, InstalledSkillRecord]:
        try:
            records = self.inventory_service.scan()
        except Exception:  # noqa: BLE001
            return {}
        return {
            slug: record
            for slug, record in records.items()
            if self._installed_skill_is_usable(record)
        }

    def _load_skill_candidates(self, target_date: date) -> dict[str, dict[str, object]]:
        path = self.run_dir / target_date.isoformat() / "skill-candidates.json"
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        raw_candidates = payload.get("candidates", [])
        if not isinstance(raw_candidates, list):
            return {}
        normalized: dict[str, dict[str, object]] = {}
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id", "")).strip()
            if not candidate_id:
                continue
            normalized[candidate_id] = item
        return normalized

    def _load_skill_merge_decisions(self, target_date: date) -> list[dict[str, object]]:
        path = self.run_dir / target_date.isoformat() / "skill-merge-decisions.json"
        if not path.exists():
            return []
        artifact_service = ClassificationArtifactService(base_dir=self.run_dir)
        try:
            records = artifact_service.read_skill_merge_decisions(path)
        except (OSError, ValueError, json.JSONDecodeError):
            return []
        return [
            {
                "candidate_id": record.candidate_id,
                "decision": record.decision,
                "canonical_name": record.canonical_name,
                "merge_target": record.merge_target,
                "accepted": record.accepted,
                "reason": record.reason,
            }
            for record in records
        ]

    def _build_daily_skill_cards(
        self,
        *,
        target_date: date,
        skill_candidates: dict[str, dict[str, object]],
        decisions: list[dict[str, object]],
        skill_sync_payload: dict[str, object],
        installed_inventory: dict[str, InstalledSkillRecord],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        groups: dict[str, dict[str, object]] = {}
        sync_actions = skill_sync_payload.get("actions", [])
        normalized_actions = [item for item in sync_actions if isinstance(item, dict)]
        for decision in decisions:
            candidate = skill_candidates.get(str(decision.get("candidate_id", "")).strip())
            if candidate is None:
                continue
            skill_id = self._normalize_skill_id(
                str(decision.get("merge_target") or decision.get("canonical_name") or candidate.get("slug") or "")
            )
            if not skill_id:
                continue
            display_name = str(decision.get("canonical_name") or candidate.get("display_name") or skill_id).strip() or skill_id
            group = groups.setdefault(
                skill_id,
                {
                    "skill_id": skill_id,
                    "display_name": display_name,
                    "status": "pending_confirmation",
                    "status_label": self._localize_status("pending_confirmation"),
                    "purpose": str(candidate.get("description", "")).strip() or str(decision.get("reason", "")).strip() or "_无_",
                    "installed_paths": [],
                    "source_repositories": [],
                    "merged_from": [],
                    "evidence_files": [],
                    "audit_status": None,
                    "audit_verdict": None,
                    "first_seen_at": target_date.isoformat(),
                    "last_seen_at": target_date.isoformat(),
                    "last_touched_at": target_date.isoformat(),
                },
            )
            group["source_repositories"].append(str(candidate.get("repo_full_name", "")).strip())
            group["merged_from"].append(str(candidate.get("slug", "")).strip() or str(candidate.get("candidate_id", "")).strip())
            group["evidence_files"].extend(str(item).strip() for item in candidate.get("files", []) if str(item).strip())
            action = self._match_sync_action(
                skill_id=skill_id,
                candidate_id=str(candidate.get("candidate_id", "")).strip(),
                candidate_repo=str(candidate.get("repo_full_name", "")).strip(),
                sync_actions=normalized_actions,
            )
            action_installed_path = self._valid_action_installed_path(
                action=action,
                installed_inventory=installed_inventory,
            )
            if bool(decision.get("accepted")) and (action_installed_path or skill_id in installed_inventory):
                group["status"] = "integrated"
                group["status_label"] = self._localize_status("integrated")
            if action is not None:
                if action_installed_path:
                    group["installed_paths"].append(action_installed_path)
                if action.get("audit_status"):
                    group["audit_status"] = action.get("audit_status")
                if action.get("audit_verdict"):
                    group["audit_verdict"] = action.get("audit_verdict")

        for skill_id, record in installed_inventory.items():
            if skill_id not in groups:
                continue
            groups[skill_id]["installed_paths"].append(str(record.skill_dir))

        cards = [
            {
                **value,
                "source_repositories": sorted({repo for repo in value["source_repositories"] if repo}),
                "merged_from": sorted({entry for entry in value["merged_from"] if entry}),
                "evidence_files": sorted({path for path in value["evidence_files"] if path}),
                "installed_paths": sorted({path for path in value["installed_paths"] if path}),
            }
            for value in groups.values()
        ]
        cards.sort(key=self._skill_highlight_sort_key)
        discovered = [card for card in cards if card["status"] == "pending_confirmation"]
        return cards, discovered

    def _build_installed_skill_card(self, record: InstalledSkillRecord) -> dict[str, object]:
        return {
            "skill_id": record.slug,
            "display_name": record.display_name,
            "status": "integrated",
            "status_label": self._localize_status("integrated"),
            "purpose": record.description or "_无_",
            "installed_paths": [str(record.skill_dir)],
            "source_repositories": [record.managed_source_repo_full_name] if record.managed_source_repo_full_name else [],
            "merged_from": list(record.aliases),
            "audit_status": None,
            "audit_verdict": None,
        }

    @staticmethod
    def _match_sync_action(
        *,
        skill_id: str,
        candidate_id: str,
        candidate_repo: str,
        sync_actions: list[dict[str, object]],
    ) -> dict[str, object] | None:
        del candidate_id
        for action in sync_actions:
            action_slug = str(action.get("slug", "")).strip()
            matched_slug = str(action.get("matched_installed_slug", "")).strip()
            action_repo = str(action.get("source_repo_full_name", "")).strip()
            if action_repo != candidate_repo:
                continue
            if action_slug == skill_id or matched_slug == skill_id:
                return action
        return None

    @staticmethod
    def _valid_action_installed_path(
        *,
        action: dict[str, object] | None,
        installed_inventory: dict[str, InstalledSkillRecord],
    ) -> str | None:
        if action is None:
            return None

        for slug_key in ("matched_installed_slug", "slug"):
            slug = str(action.get(slug_key, "")).strip()
            if slug in installed_inventory:
                return str(installed_inventory[slug].skill_dir)

        candidate_paths = (
            action.get("installed_path"),
            action.get("matched_installed_path"),
        )
        installed_paths = {
            record.skill_dir.resolve(strict=False): str(record.skill_dir)
            for record in installed_inventory.values()
        }
        for candidate in candidate_paths:
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            resolved = Path(candidate).resolve(strict=False)
            if resolved in installed_paths:
                return installed_paths[resolved]
        return None

    @staticmethod
    def _normalize_skill_id(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
        return normalized.strip("-")

    @staticmethod
    def _skill_highlight_sort_key(card: dict[str, object]) -> tuple[int, int, str]:
        status_order = {"pending_confirmation": 0, "integrated": 1}
        return (
            status_order.get(str(card.get("status", "")), 99),
            -len(card.get("source_repositories", [])),
            str(card.get("skill_id", "")).casefold(),
        )

    @staticmethod
    def _render_path_list(paths: tuple[str, ...]) -> str:
        if not paths:
            return "_未集成_"
        return "、".join(f"`{path}`" for path in paths)

    @staticmethod
    def _installed_skill_is_usable(record: InstalledSkillRecord) -> bool:
        manifest = record.skill_dir / "SKILL.md"
        if not manifest.exists():
            return False
        try:
            files = {
                path.relative_to(record.skill_dir).as_posix()
                for path in record.skill_dir.rglob("*")
                if path.is_file()
            }
        except OSError:
            return False
        if files == {"SKILL.md", "haotian-wrapper.json"}:
            return ReportService._managed_metadata_marks_full_package(record.skill_dir)
        return True

    @staticmethod
    def _managed_metadata_marks_full_package(skill_dir: Path) -> bool:
        metadata_path = skill_dir / "haotian-wrapper.json"
        if not metadata_path.exists():
            return False
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return False
        if not isinstance(payload, dict):
            return False
        if payload.get("install_type") == "full-package":
            return True
        return payload.get("files") == ["SKILL.md"] and bool(payload.get("source_repo_full_name"))

    def _load_taxonomy_gap_candidates(self, target_date: date) -> list[dict[str, object]]:
        path = self.run_dir / target_date.isoformat() / "taxonomy-gap-candidates.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return []
        if not isinstance(payload, dict):
            return []
        candidates = payload.get("candidates", [])
        if not isinstance(candidates, list):
            return []
        normalized: list[dict[str, object]] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            repo_full_names_raw = candidate.get("repo_full_names", [])
            if not isinstance(repo_full_names_raw, (list, tuple)):
                continue
            repo_full_names = tuple(str(repo) for repo in repo_full_names_raw if repo)
            normalized.append(
                {
                    "candidate_id": str(candidate.get("candidate_id", "")),
                    "display_name": str(candidate.get("display_name", "")),
                    "reason": str(candidate.get("reason", "")),
                    "repo_full_names": repo_full_names,
                    "repo_count": len(repo_full_names),
                }
            )
        return normalized

    def _load_skill_sync_report(self, target_date: date) -> dict[str, object]:
        path = self.run_dir / target_date.isoformat() / "skill-sync-report.json"
        default_payload = ClassificationArtifactService.empty_skill_sync_report_payload(target_date.isoformat())
        if not path.exists():
            return default_payload
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return default_payload
        if not isinstance(payload, dict):
            return default_payload

        summary = ClassificationArtifactService.default_skill_sync_summary()
        raw_summary = payload.get("summary", {})
        if isinstance(raw_summary, dict):
            summary["config_ready"] = bool(raw_summary.get("config_ready", summary["config_ready"]))
            for key in summary:
                if key == "config_ready":
                    continue
                try:
                    if key in raw_summary:
                        summary[key] = int(raw_summary[key])
                except (TypeError, ValueError):
                    continue

        actions: list[dict[str, object]] = []
        raw_actions = payload.get("actions", [])
        if isinstance(raw_actions, list):
            for item in raw_actions:
                if not isinstance(item, dict):
                    continue
                actions.append(
                    {
                        "action": str(item.get("action", "")),
                        "slug": str(item.get("slug", "")),
                        "display_name": str(item.get("display_name", "")),
                        "source_repo_full_name": str(item.get("source_repo_full_name", "")),
                        "repo_url": str(item.get("repo_url", "")),
                        "relative_root": str(item.get("relative_root", "")),
                        "files": list(item.get("files", [])) if isinstance(item.get("files", []), list) else [],
                        "capability_ids": [
                            str(value).strip()
                            for value in item.get("capability_ids", [])
                            if str(value).strip()
                        ]
                        if isinstance(item.get("capability_ids", []), list)
                        else [],
                        "matched_installed_slug": item.get("matched_installed_slug"),
                        "matched_installed_path": item.get("matched_installed_path"),
                        "installed_path": item.get("installed_path"),
                        "audit_status": item.get("audit_status"),
                        "audit_verdict": item.get("audit_verdict"),
                        "reason": str(item.get("reason", "")),
                    }
                )
        summary["action_count"] = len(actions)
        for action_name in (
            "aligned_existing",
            "installed_new",
            "discarded_non_integrable",
            "blocked_audit_failure",
            "blocked_ambiguous_match",
            "rolled_back_install_failure",
        ):
            summary[action_name] = sum(1 for item in actions if item.get("action") == action_name)

        return {
            "schema_version": 1,
            "report_date": target_date.isoformat(),
            "summary": summary,
            "actions": actions,
        }
    def _highlight_sort_key(self, item: ReportItem) -> tuple[int, int, float, str]:
        priority_order = {"high": 0, "medium": 1, "low": 2}
        status_order = {
            "risks": 0,
            "new_capabilities": 1,
            "enhancement_candidates": 2,
            "covered": 3,
        }
        priority = self._priority_for_item(item)
        return (
            priority_order[priority],
            status_order.get(item.status, 99),
            -item.base_score,
            item.capability_id,
        )

    @staticmethod
    def _priority_for_item(item: ReportItem) -> str:
        if item.needs_manual_attention or item.status == "risks":
            return "high"
        if item.status in {"new_capabilities", "enhancement_candidates"}:
            return "medium"
        return "low"

    @staticmethod
    def _localize_priority(priority: str) -> str:
        labels = {
            "high": "高",
            "medium": "中",
            "low": "低",
        }
        return labels.get(priority, priority)

    @staticmethod
    def _localize_status(status: str) -> str:
        labels = {
            "integrated": "已集成",
            "pending_confirmation": "需确认",
        }
        return labels.get(status, status)

    @staticmethod
    def _localize_taxonomy_status(status: str) -> str:
        labels = {
            "new_capabilities": "新能力",
            "enhancement_candidates": "增强候选",
            "covered": "已覆盖",
            "risks": "风险",
            "taxonomy_gap": "Taxonomy Gap",
        }
        return labels.get(status, status)

    @staticmethod
    def _collect_integrated_capability_ids(skill_sync_payload: dict[str, object]) -> set[str]:
        integrated_actions = {"aligned_existing", "installed_new"}
        capability_ids: set[str] = set()
        actions = skill_sync_payload.get("actions", [])
        if not isinstance(actions, list):
            return capability_ids
        for action in actions:
            if not isinstance(action, dict):
                continue
            if str(action.get("action", "")).strip() not in integrated_actions:
                continue
            raw_ids = action.get("capability_ids", [])
            if not isinstance(raw_ids, list):
                continue
            capability_ids.update(str(value).strip() for value in raw_ids if str(value).strip())
        return capability_ids

    @staticmethod
    def _integration_status_for_item(item: ReportItem, integrated_capability_ids: set[str]) -> str:
        if item.capability_id in integrated_capability_ids:
            return "integrated"
        return "pending_confirmation"

    @staticmethod
    def _render_repo_list(repos: tuple[str, ...]) -> str:
        if not repos:
            return "_无_"
        return "、".join(f"`{repo}`" for repo in repos)

    @staticmethod
    def _localize_capability_name(capability_id: str, fallback_name: str) -> str:
        capability_names = {
            "browser_automation": "浏览器自动化",
            "code_generation": "代码生成",
            "information_retrieval": "信息检索",
            "summarization": "摘要生成",
            "data_extraction": "数据提取",
            "workflow_orchestration": "工作流编排",
        }
        return capability_names.get(capability_id, fallback_name)

    @staticmethod
    def _localize_periods(periods: tuple[str, ...]) -> str:
        period_labels = {
            "daily": "每日",
            "weekly": "每周",
            "monthly": "每月",
        }
        return "、".join(period_labels.get(period, period) for period in periods)

    @staticmethod
    def _localize_analysis_depth(analysis_depth: str) -> str:
        if not analysis_depth:
            return "_未提供_"
        labels = {
            "layered": "分层",
            "fallback": "回退",
        }
        return "、".join(labels.get(value, value) for value in analysis_depth.split("、"))

    @staticmethod
    def _render_file_list(files: tuple[str, ...]) -> str:
        if not files:
            return "_无_"
        return ", ".join(f"`{file}`" for file in files)

    def _render_evidence_snippets(self, snippets: tuple[ReportEvidenceSnippet, ...]) -> list[str]:
        if not snippets:
            return ["- 关键证据：_无_", ""]

        lines = ["- 关键证据："]
        for snippet in snippets:
            parts = []
            if snippet.path:
                parts.append(f"`{snippet.path}`")
            if snippet.excerpt:
                parts.append(snippet.excerpt)
            if snippet.why_it_matters:
                parts.append(f"原因：{snippet.why_it_matters}")
            lines.append(f"  - {'：'.join(parts)}")
        lines.append("")
        return lines

    @staticmethod
    def _collect_analysis_depth(rows: list[sqlite3.Row]) -> str:
        depths: list[str] = []
        for row in rows:
            depth = row["analysis_depth"]
            if depth is None:
                continue
            normalized = str(depth).strip()
            if not normalized or normalized in depths:
                continue
            depths.append(normalized)
        return "、".join(depths)

    @staticmethod
    def _collect_matched_files(rows: list[sqlite3.Row]) -> tuple[str, ...]:
        files: list[str] = []
        for row in rows:
            files.extend(ReportService._parse_json_list(row["matched_files"]))
        return tuple(dict.fromkeys(file for file in files if file))

    @staticmethod
    def _collect_evidence_snippets(rows: list[sqlite3.Row]) -> tuple[ReportEvidenceSnippet, ...]:
        snippets: list[ReportEvidenceSnippet] = []
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            for snippet in ReportService._parse_evidence_snippets(row["evidence_snippets"]):
                key = (snippet.path, snippet.excerpt, snippet.why_it_matters)
                if key in seen:
                    continue
                seen.add(key)
                snippets.append(snippet)
        return tuple(snippets)

    @staticmethod
    def _parse_json_list(raw_value: object) -> list[str]:
        if isinstance(raw_value, list):
            return [str(item).strip() for item in raw_value if item is not None and str(item).strip()]
        if isinstance(raw_value, tuple):
            return [str(item).strip() for item in raw_value if item is not None and str(item).strip()]
        if isinstance(raw_value, str) and raw_value.strip():
            try:
                payload = json.loads(raw_value)
            except Exception:  # noqa: BLE001
                return []
            if isinstance(payload, list):
                return [str(item).strip() for item in payload if item is not None and str(item).strip()]
        return []

    @staticmethod
    def _parse_evidence_snippets(raw_value: object) -> tuple[ReportEvidenceSnippet, ...]:
        payload: object
        if isinstance(raw_value, (list, tuple)):
            payload = raw_value
        elif isinstance(raw_value, str) and raw_value.strip():
            try:
                payload = json.loads(raw_value)
            except Exception:  # noqa: BLE001
                return ()
        else:
            return ()

        snippets: list[ReportEvidenceSnippet] = []
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    path = item.get("path", "")
                    excerpt = item.get("excerpt", "")
                    why_it_matters = item.get("why_it_matters", "")
                    snippets.append(
                        ReportEvidenceSnippet(
                            path="" if path is None else str(path).strip(),
                            excerpt="" if excerpt is None else str(excerpt).strip(),
                            why_it_matters="" if why_it_matters is None else str(why_it_matters).strip(),
                        )
                    )
                elif isinstance(item, str) and item.strip():
                    snippets.append(ReportEvidenceSnippet(path="", excerpt=item.strip(), why_it_matters=""))
        return tuple(snippets)

    @staticmethod
    def _normalize_date(value: date | str) -> date:
        if isinstance(value, date):
            return value
        return date.fromisoformat(value)


def generate_daily_report(report_date: date | str) -> Path:
    """Convenience wrapper for the default daily report service."""

    return ReportService().generate_daily_report(report_date)
