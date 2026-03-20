"""Daily capability reporting helpers."""

from __future__ import annotations

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
    source_repo: str
    reason: str
    suggestion: str
    base_score: float
    summary: str
    status: str


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
        report_path = self.report_dir / f"{target_date.isoformat()}.md"
        report_path.write_text(self._render_markdown(target_date, sections), encoding='utf-8')
        return report_path

    def _load_sections(self, target_date: date) -> dict[str, list[ReportItem]]:
        with get_connection(self.database_url) as connection:
            rows = connection.execute(
                """
                SELECT
                    rc.capability_id AS capability_id,
                    COALESCE(cr.canonical_name, rc.capability_id) AS canonical_name,
                    COALESCE(cr.source_repo_full_name, rc.repo_full_name) AS source_repo,
                    rc.reason AS reason,
                    rc.summary AS summary,
                    rc.confidence AS base_score,
                    COALESCE(cr.status, 'pending_review') AS status,
                    COALESCE(cr.first_seen_at, rc.created_at) AS first_seen_at,
                    COALESCE(cr.last_seen_at, rc.created_at) AS last_seen_at,
                    COALESCE(cr.mention_count, 1) AS mention_count,
                    COALESCE(cr.consecutive_appearances, 1) AS consecutive_appearances,
                    rc.needs_review AS needs_review
                FROM repo_capabilities rc
                LEFT JOIN capability_registry cr ON cr.capability_id = rc.capability_id
                WHERE date(rc.created_at) = ?
                ORDER BY rc.confidence DESC, rc.capability_id ASC
                """,
                (target_date.isoformat(),),
            ).fetchall()
        items = [self._classify_row(row, target_date) for row in rows]
        return {
            'summary': items,
            'new_capabilities': [item for item in items if item.status == 'new_capabilities'],
            'enhancement_candidates': [item for item in items if item.status == 'enhancement_candidates'],
            'covered': [item for item in items if item.status == 'covered'],
            'risks': [item for item in items if item.status == 'risks'],
        }

    def _classify_row(self, row: sqlite3.Row, target_date: date) -> ReportItem:
        registry_status = str(row['status'])
        first_seen = str(row['first_seen_at'])[:10]
        mention_count = int(row['mention_count'])
        consecutive = int(row['consecutive_appearances'])
        needs_review = bool(row['needs_review'])
        base_score = float(row['base_score'])

        if first_seen == target_date.isoformat() and registry_status == CapabilityStatus.PENDING_REVIEW.value:
            bucket = 'new_capabilities'
            suggestion = 'Review and decide whether to add to watchlist, run a POC, or activate directly.'
        elif registry_status in {CapabilityStatus.WATCHLIST.value, CapabilityStatus.POC.value, CapabilityStatus.PENDING_REVIEW.value} and (
            base_score >= 0.7 or consecutive >= 2 or mention_count >= 2
        ):
            bucket = 'enhancement_candidates'
            suggestion = 'Investigate traction, compare with adjacent tools, and prepare a narrower validation plan.'
        elif registry_status in {CapabilityStatus.ACTIVE.value, CapabilityStatus.DEPRECATED.value} and not needs_review:
            bucket = 'covered'
            suggestion = 'Track for deltas only; no immediate action is required unless the implementation materially changes.'
        else:
            bucket = 'risks'
            suggestion = 'Review evidence quality, potential duplication, and downstream maintenance cost before promoting.'

        if registry_status == CapabilityStatus.REJECTED.value:
            bucket = 'risks'
            suggestion = 'Confirm whether the rejection still stands or whether momentum justifies a re-evaluation.'
        elif needs_review and bucket == 'covered':
            bucket = 'risks'
            suggestion = 'Resolve the review flag before treating the capability as fully covered.'

        return ReportItem(
            capability_id=row['capability_id'],
            canonical_name=row['canonical_name'],
            source_repo=row['source_repo'],
            reason=row['reason'],
            suggestion=suggestion,
            base_score=base_score,
            summary=row['summary'],
            status=bucket,
        )

    def _render_markdown(self, target_date: date, sections: dict[str, list[ReportItem]]) -> str:
        summary_items = sections['summary']
        lines = [
            f"# Daily Capability Report - {target_date.isoformat()}",
            '',
            '## Summary',
            '',
            f"- Total items: {len(summary_items)}",
            f"- New Capabilities: {len(sections['new_capabilities'])}",
            f"- Enhancement Candidates: {len(sections['enhancement_candidates'])}",
            f"- Covered: {len(sections['covered'])}",
            f"- Risks: {len(sections['risks'])}",
            '',
        ]
        lines.extend(self._render_section('New Capabilities', sections['new_capabilities']))
        lines.extend(self._render_section('Enhancement Candidates', sections['enhancement_candidates']))
        lines.extend(self._render_section('Covered', sections['covered']))
        lines.extend(self._render_section('Risks', sections['risks']))
        return "\n".join(lines).strip() + "\n"

    def _render_section(self, title: str, items: list[ReportItem]) -> list[str]:
        lines = [f"## {title}", '']
        if not items:
            lines.extend(['_No items for this section._', ''])
            return lines
        for item in items:
            lines.extend([
                f"### {item.canonical_name} (`{item.capability_id}`)",
                f"- Source Repo: `{item.source_repo}`",
                f"- Reason: {item.reason}",
                f"- Suggested Action: {item.suggestion}",
                f"- Base Score: {item.base_score:.2f}",
                f"- Summary: {item.summary}",
                '',
            ])
        return lines

    @staticmethod
    def _normalize_date(value: date | str) -> date:
        if isinstance(value, date):
            return value
        return date.fromisoformat(value)


def generate_daily_report(report_date: date | str) -> Path:
    """Convenience wrapper for the default daily report service."""

    return ReportService().generate_daily_report(report_date)
