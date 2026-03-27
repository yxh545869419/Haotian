"""Persistent cache helpers for cross-day repository analysis reuse."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json

from haotian.db.schema import get_connection
from haotian.services.repository_analysis_service import EvidenceSnippet
from haotian.services.repository_analysis_service import RepositoryAnalysisResult
from haotian.services.repository_skill_package_service import DiscoveredSkillPackage


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class CachedRepositoryAnalysis:
    repo_full_name: str
    repo_url: str
    source_pushed_at: str | None
    analyzed_at: str
    analysis_depth: str
    root_files: tuple[str, ...]
    matched_files: tuple[str, ...]
    matched_keywords: tuple[str, ...]
    architecture_signals: tuple[str, ...]
    probe_summary: str
    evidence_snippets: tuple[EvidenceSnippet, ...]
    analysis_limits: tuple[str, ...]
    discovered_skill_packages: tuple[DiscoveredSkillPackage, ...] = ()

    def to_reused_result(self, *, repo_url: str | None = None) -> RepositoryAnalysisResult:
        return RepositoryAnalysisResult(
            repo_full_name=self.repo_full_name,
            repo_url=repo_url or self.repo_url,
            analysis_depth=self.analysis_depth,
            clone_strategy="cache-hit",
            clone_started=False,
            analysis_completed=True,
            cleanup_attempted=False,
            cleanup_required=False,
            cleanup_completed=True,
            fallback_used=False,
            root_files=self.root_files,
            matched_files=self.matched_files,
            matched_keywords=self.matched_keywords,
            architecture_signals=self.architecture_signals,
            probe_summary=self.probe_summary,
            evidence_snippets=self.evidence_snippets,
            analysis_limits=self.analysis_limits,
            discovered_skill_packages=self.discovered_skill_packages,
            analysis_source="cache",
        )


class RepositoryAnalysisCacheService:
    """Store successful repository analyses for cross-day reuse."""

    refresh_window = timedelta(days=90)

    def __init__(self, *, database_url: str | None = None) -> None:
        self.database_url = database_url

    def load(self, repo_full_name: str) -> CachedRepositoryAnalysis | None:
        with get_connection(self.database_url) as connection:
            row = connection.execute(
                """
                SELECT
                    repo_full_name,
                    repo_url,
                    source_pushed_at,
                    analyzed_at,
                    analysis_depth,
                    root_files,
                    matched_files,
                    matched_keywords,
                    architecture_signals,
                    probe_summary,
                    evidence_snippets,
                    analysis_limits,
                    discovered_skill_packages
                FROM repo_analysis_cache
                WHERE repo_full_name = ?
                """,
                (repo_full_name,),
            ).fetchone()
        if row is None:
            return None
        return CachedRepositoryAnalysis(
            repo_full_name=str(row["repo_full_name"]),
            repo_url=str(row["repo_url"]),
            source_pushed_at=str(row["source_pushed_at"]) if row["source_pushed_at"] is not None else None,
            analyzed_at=str(row["analyzed_at"]),
            analysis_depth=str(row["analysis_depth"]),
            root_files=tuple(self._parse_json_list(row["root_files"])),
            matched_files=tuple(self._parse_json_list(row["matched_files"])),
            matched_keywords=tuple(self._parse_json_list(row["matched_keywords"])),
            architecture_signals=tuple(self._parse_json_list(row["architecture_signals"])),
            probe_summary=str(row["probe_summary"] or ""),
            evidence_snippets=self._parse_evidence_snippets(row["evidence_snippets"]),
            analysis_limits=tuple(self._parse_json_list(row["analysis_limits"])),
            discovered_skill_packages=self._parse_discovered_skill_packages(row["discovered_skill_packages"]),
        )

    def should_refresh(
        self,
        *,
        cached: CachedRepositoryAnalysis,
        current_pushed_at: str | None,
    ) -> bool:
        cached_pushed_at = _parse_timestamp(cached.source_pushed_at)
        latest_pushed_at = _parse_timestamp(current_pushed_at)
        if cached_pushed_at is None or latest_pushed_at is None:
            return False
        if latest_pushed_at <= cached_pushed_at:
            return False
        return latest_pushed_at - cached_pushed_at >= self.refresh_window

    def upsert(
        self,
        *,
        result: RepositoryAnalysisResult,
        source_pushed_at: str | None,
        analyzed_at: str,
    ) -> None:
        with get_connection(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO repo_analysis_cache (
                    repo_full_name,
                    repo_url,
                    source_pushed_at,
                    analyzed_at,
                    analysis_depth,
                    root_files,
                    matched_files,
                    matched_keywords,
                    architecture_signals,
                    probe_summary,
                    evidence_snippets,
                    analysis_limits,
                    discovered_skill_packages,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(repo_full_name) DO UPDATE SET
                    repo_url = excluded.repo_url,
                    source_pushed_at = excluded.source_pushed_at,
                    analyzed_at = excluded.analyzed_at,
                    analysis_depth = excluded.analysis_depth,
                    root_files = excluded.root_files,
                    matched_files = excluded.matched_files,
                    matched_keywords = excluded.matched_keywords,
                    architecture_signals = excluded.architecture_signals,
                    probe_summary = excluded.probe_summary,
                    evidence_snippets = excluded.evidence_snippets,
                    analysis_limits = excluded.analysis_limits,
                    discovered_skill_packages = excluded.discovered_skill_packages,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    result.repo_full_name,
                    result.repo_url,
                    source_pushed_at,
                    analyzed_at,
                    result.analysis_depth,
                    json.dumps([*result.root_files], ensure_ascii=False),
                    json.dumps([*result.matched_files], ensure_ascii=False),
                    json.dumps([*result.matched_keywords], ensure_ascii=False),
                    json.dumps([*result.architecture_signals], ensure_ascii=False),
                    result.probe_summary,
                    json.dumps(
                        [
                            {
                                "path": snippet.path,
                                "excerpt": snippet.excerpt,
                                "why_it_matters": snippet.why_it_matters,
                            }
                            for snippet in result.evidence_snippets
                        ],
                        ensure_ascii=False,
                    ),
                    json.dumps([*result.analysis_limits], ensure_ascii=False),
                    json.dumps(
                        [package.to_serialized_payload() for package in result.discovered_skill_packages],
                        ensure_ascii=False,
                    ),
                ),
            )
            connection.commit()

    @staticmethod
    def _parse_json_list(raw_value: object) -> list[str]:
        if not isinstance(raw_value, str) or not raw_value.strip():
            return []
        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return [str(item).strip() for item in payload if item is not None and str(item).strip()]

    @staticmethod
    def _parse_evidence_snippets(raw_value: object) -> tuple[EvidenceSnippet, ...]:
        if not isinstance(raw_value, str) or not raw_value.strip():
            return ()
        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError:
            return ()
        if not isinstance(payload, list):
            return ()
        snippets: list[EvidenceSnippet] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            snippets.append(
                EvidenceSnippet(
                    path=str(item.get("path", "")).strip(),
                    excerpt=str(item.get("excerpt", "")).strip(),
                    why_it_matters=str(item.get("why_it_matters", "")).strip(),
                )
            )
        return tuple(snippets)

    @staticmethod
    def _parse_discovered_skill_packages(raw_value: object) -> tuple[DiscoveredSkillPackage, ...]:
        if not isinstance(raw_value, str) or not raw_value.strip():
            return ()
        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError:
            return ()
        if not isinstance(payload, list):
            return ()
        packages: list[DiscoveredSkillPackage] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            packages.append(DiscoveredSkillPackage.from_serialized_payload(item))
        return tuple(packages)
