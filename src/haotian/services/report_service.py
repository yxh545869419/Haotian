"""Daily capability reporting helpers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import sqlite3
from pathlib import Path

from haotian.config import get_settings
from haotian.db.schema import get_connection, initialize_schema
from haotian.registry.capability_registry import CapabilityStatus


@dataclass(frozen=True, slots=True)
class ReportItem:
    capability_id: str
    canonical_name: str
    source_repos: tuple[str, ...]
    periods: tuple[str, ...]
    reason: str
    suggestion: str
    base_score: float
    summary: str
    status: str
    repo_count: int
    needs_manual_attention: bool


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
                    COALESCE(cr.consecutive_appearances, 1) AS consecutive_appearances
                FROM repo_capabilities rc
                LEFT JOIN capability_registry cr ON cr.capability_id = rc.capability_id
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
            return "covered", "Auto-configured as active; continue monitoring for changes.", False
        if registry_status == CapabilityStatus.POC.value:
            return "enhancement_candidates", "Auto-configured for POC tracking; review only if rollout work is required.", needs_review
        if registry_status == CapabilityStatus.WATCHLIST.value:
            return "new_capabilities", "Auto-configured into watchlist; manual follow-up is optional unless marked below.", needs_review
        if registry_status == CapabilityStatus.DEPRECATED.value:
            return "risks", "Auto-configured to ignore/deprecate due to low confidence; verify only if this looks important.", True

        needs_manual_attention = needs_review or base_score < 0.6
        if first_seen == target_date.isoformat() and mention_count == 1 and consecutive <= 1:
            return "new_capabilities", "Automatically configured from today's evidence; see manual flag if confidence is weak.", needs_manual_attention
        return "enhancement_candidates", "Automatically configured based on repeated signals and confidence.", needs_manual_attention

    def _render_markdown(
        self,
        target_date: date,
        sections: dict[str, list[ReportItem]],
        repo_snapshot: dict[str, tuple[str, ...]],
    ) -> str:
        summary_items = sections["summary"]
        lines = [
            f"# Daily Capability Report - {target_date.isoformat()}",
            "",
            "## Summary",
            "",
            f"- Total capabilities: {len(summary_items)}",
            f"- Manual Attention: {len(sections['manual_attention'])}",
            f"- New Capabilities: {len(sections['new_capabilities'])}",
            f"- Enhancement Candidates: {len(sections['enhancement_candidates'])}",
            f"- Covered: {len(sections['covered'])}",
            f"- Risks: {len(sections['risks'])}",
            "",
        ]
        lines.extend(self._render_repo_snapshot(repo_snapshot))
        lines.extend(self._render_section("Manual Attention", sections["manual_attention"]))
        lines.extend(self._render_section("New Capabilities", sections["new_capabilities"]))
        lines.extend(self._render_section("Enhancement Candidates", sections["enhancement_candidates"]))
        lines.extend(self._render_section("Covered", sections["covered"]))
        lines.extend(self._render_section("Risks", sections["risks"]))
        return "\n".join(lines).strip() + "\n"

    def _render_repo_snapshot(self, repo_snapshot: dict[str, tuple[str, ...]]) -> list[str]:
        today = repo_snapshot["today"]
        lines = [
            "## Repo Snapshot",
            "",
            f"- Today's repos ({len(today)}): {', '.join(f'`{repo}`' for repo in today) if today else '_None_'}",
            f"- New vs previous snapshot ({len(repo_snapshot['new'])}): {', '.join(f'`{repo}`' for repo in repo_snapshot['new']) if repo_snapshot['new'] else '_None_'}",
            f"- Dropped vs previous snapshot ({len(repo_snapshot['dropped'])}): {', '.join(f'`{repo}`' for repo in repo_snapshot['dropped']) if repo_snapshot['dropped'] else '_None_'}",
            "",
        ]
        return lines

    def _render_section(self, title: str, items: list[ReportItem]) -> list[str]:
        lines = [f"## {title}", ""]
        if not items:
            lines.extend(["_No items for this section._", ""])
            return lines
        for item in items:
            lines.extend(
                [
                    f"### {item.canonical_name} (`{item.capability_id}`)",
                    f"- Manual Attention: {'YES' if item.needs_manual_attention else 'NO'}",
                    f"- Source Repos ({item.repo_count}): `{ '`, `'.join(item.source_repos) }`",
                    f"- Periods: `{', '.join(item.periods)}`",
                    f"- Reason: {item.reason}",
                    f"- Suggested Action: {item.suggestion}",
                    f"- Base Score: {item.base_score:.2f}",
                    f"- Summary: {item.summary}",
                    "",
                ]
            )
        return lines

    @staticmethod
    def _normalize_date(value: date | str) -> date:
        if isinstance(value, date):
            return value
        return date.fromisoformat(value)


def generate_daily_report(report_date: date | str) -> Path:
    """Convenience wrapper for the default daily report service."""

    return ReportService().generate_daily_report(report_date)
