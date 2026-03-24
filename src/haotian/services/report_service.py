"""Daily capability reporting helpers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import json
import sqlite3
from pathlib import Path

from haotian.config import get_settings
from haotian.db.schema import get_connection, initialize_schema
from haotian.registry.capability_registry import CapabilityStatus


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

    def __init__(self, database_url: str | None = None, report_dir: Path | None = None) -> None:
        settings = get_settings()
        self.database_url = database_url
        self.report_dir = report_dir or settings.report_dir

    def generate_daily_report(self, report_date: date | str) -> Path:
        target_date = self._normalize_date(report_date)
        initialize_schema(self.database_url)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        sections = self._load_sections(target_date)
        repo_snapshot = self._load_repo_snapshot(target_date)
        report_path = self.report_dir / f"{target_date.isoformat()}.md"
        report_path.write_text(self._render_markdown(target_date, sections, repo_snapshot), encoding="utf-8")
        return report_path

    def generate_daily_report_json(self, report_date: date | str) -> Path:
        target_date = self._normalize_date(report_date)
        initialize_schema(self.database_url)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        sections = self._load_sections(target_date)
        repo_snapshot = self._load_repo_snapshot(target_date)
        payload = {
            "report_date": target_date.isoformat(),
            "summary": {
                "total_capabilities": len(sections["summary"]),
                "manual_attention": len(sections["manual_attention"]),
                "new_capabilities": len(sections["new_capabilities"]),
                "enhancement_candidates": len(sections["enhancement_candidates"]),
                "covered": len(sections["covered"]),
                "risks": len(sections["risks"]),
            },
            "repo_snapshot": {
                key: list(value) for key, value in repo_snapshot.items()
            },
            "sections": {
                key: [item.to_dict() for item in items]
                for key, items in sections.items()
                if key != "summary"
            },
        }
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
        sections: dict[str, list[ReportItem]],
        repo_snapshot: dict[str, tuple[str, ...]],
    ) -> str:
        summary_items = sections["summary"]
        lines = [
            f"# 每日能力报告 - {target_date.isoformat()}",
            "",
            "## 摘要",
            "",
            f"- 能力总数：{len(summary_items)}",
            f"- 需要人工关注：{len(sections['manual_attention'])}",
            f"- 新能力：{len(sections['new_capabilities'])}",
            f"- 增强候选：{len(sections['enhancement_candidates'])}",
            f"- 已覆盖能力：{len(sections['covered'])}",
            f"- 风险：{len(sections['risks'])}",
            "",
        ]
        lines.extend(self._render_repo_snapshot(repo_snapshot))
        lines.extend(self._render_section("需要人工关注", sections["manual_attention"]))
        lines.extend(self._render_section("新能力", sections["new_capabilities"]))
        lines.extend(self._render_section("增强候选", sections["enhancement_candidates"]))
        lines.extend(self._render_section("已覆盖能力", sections["covered"]))
        lines.extend(self._render_section("风险", sections["risks"]))
        return "\n".join(lines).strip() + "\n"

    def _render_repo_snapshot(self, repo_snapshot: dict[str, tuple[str, ...]]) -> list[str]:
        today = repo_snapshot["today"]
        lines = [
            "## 仓库快照",
            "",
            f"- 今日仓库（{len(today)}）：{', '.join(f'`{repo}`' for repo in today) if today else '_无_'}",
            f"- 相较上一快照新增（{len(repo_snapshot['new'])}）：{', '.join(f'`{repo}`' for repo in repo_snapshot['new']) if repo_snapshot['new'] else '_无_'}",
            f"- 相较上一快照移除（{len(repo_snapshot['dropped'])}）：{', '.join(f'`{repo}`' for repo in repo_snapshot['dropped']) if repo_snapshot['dropped'] else '_无_'}",
            "",
        ]
        return lines

    def _render_section(self, title: str, items: list[ReportItem]) -> list[str]:
        lines = [f"## {title}", ""]
        if not items:
            lines.extend(["_本节暂无项目。_", ""])
            return lines
        for item in items:
            lines.extend(
                [
                    f"### {item.display_name} (`{item.capability_id}`)",
                    f"- 分析深度：{self._localize_analysis_depth(item.analysis_depth)}",
                    f"- 回退分析：{'是' if item.fallback_used else '否'}",
                    f"- 清理完成：{'是' if item.cleanup_completed else '否'}",
                    f"- 命中文件（{len(item.matched_files)}）：{self._render_file_list(item.matched_files)}",
                    f"- 需要人工关注：{'是' if item.needs_manual_attention else '否'}",
                    f"- 来源仓库（{item.repo_count}）：`{ '`, `'.join(item.source_repos) }`",
                    f"- 榜单周期：`{self._localize_periods(item.periods)}`",
                    f"- 归类依据：{item.reason}",
                    f"- 建议动作：{item.suggestion}",
                    f"- 基础分：{item.base_score:.2f}",
                    f"- 能力摘要：{item.summary}",
                    "",
                ]
            )
            lines.extend(self._render_evidence_snippets(item.evidence_snippets))
        return lines

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
