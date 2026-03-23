"""Skill-first daily pipeline orchestration service."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
import re

from haotian.analyzers.capability_normalizer import CapabilityNormalizer
from haotian.collectors.github_repository_metadata import GithubRepositoryMetadataFetcher
from haotian.collectors.github_trending import GithubTrendingCollector, TrendingRepo
from haotian.db.schema import get_connection, initialize_schema
from haotian.registry.capability_registry import (
    CapabilityApproval,
    CapabilityApprovalAction,
    CapabilityRegistryRecord,
    CapabilityRegistryRepository,
    CapabilityStatus,
)
from haotian.services.classification_artifact_service import ClassificationArtifactService, RepoClassificationRecord
from haotian.services.diff_service import CapabilityObservation, DiffService
from haotian.services.ingest_service import IngestService
from haotian.services.report_service import ReportService

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ClassificationInputBuildResult:
    """Staged input artifact summary."""

    report_date: date
    repos_ingested: int = 0
    repository_items: int = 0
    classification_input_path: Path | None = None
    stage_errors: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return not self.stage_errors


@dataclass(slots=True)
class DailyPipelineResult:
    """Finalized report summary after Codex classification."""

    report_date: date
    repos_ingested: int = 0
    capabilities_identified: int = 0
    alerts_generated: int = 0
    markdown_report_path: Path | None = None
    json_report_path: Path | None = None
    classification_output_path: Path | None = None
    stage_errors: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return not self.stage_errors

    @property
    def report_path(self) -> Path | None:
        return self.markdown_report_path


class OrchestrationService:
    """Run the deterministic parts of the Haotian skill-first workflow."""

    def __init__(
        self,
        *,
        collector: GithubTrendingCollector | None = None,
        ingest_service: IngestService | None = None,
        diff_service: DiffService | None = None,
        registry: CapabilityRegistryRepository | None = None,
        report_service: ReportService | None = None,
        metadata_fetcher: GithubRepositoryMetadataFetcher | None = None,
        artifact_service: ClassificationArtifactService | None = None,
        database_url: str | None = None,
    ) -> None:
        self.database_url = database_url
        self.collector = collector or GithubTrendingCollector()
        self.ingest_service = ingest_service or IngestService(database_url=database_url)
        self.diff_service = diff_service or DiffService()
        self.registry = registry or CapabilityRegistryRepository(database_url=database_url)
        self.report_service = report_service or ReportService(database_url=database_url)
        self.metadata_fetcher = metadata_fetcher or GithubRepositoryMetadataFetcher()
        self.artifact_service = artifact_service or ClassificationArtifactService()
        self.normalizer = CapabilityNormalizer()

    def build_classification_input(self, report_date: date | None = None) -> ClassificationInputBuildResult:
        target_date = report_date or datetime.now(UTC).date()
        initialize_schema(self.database_url)
        result = ClassificationInputBuildResult(report_date=target_date)
        repositories: list[TrendingRepo] = []
        items: list[dict[str, object]] = []

        try:
            LOGGER.info(
                "[ingest] fetching GitHub trending repositories for daily/weekly/monthly windows",
                extra={"report_date": target_date.isoformat()},
            )
            repositories = self._collect_trending_repositories(target_date)
            self.ingest_service.ingest_trending_repos(repositories)
            result.repos_ingested = len({repo.repo_full_name for repo in repositories})
            LOGGER.info(
                "[ingest] stored %s unique repositories across %s trending rows",
                result.repos_ingested,
                len(repositories),
            )
        except Exception as exc:  # noqa: BLE001
            self._record_stage_error(result, "ingest", exc, {"report_date": target_date.isoformat()})

        try:
            LOGGER.info("[stage] building classification input artifact for %s trending rows", len(repositories))
            items = self._build_classification_items(repositories)
            result.repository_items = len(items)
        except Exception as exc:  # noqa: BLE001
            self._record_stage_error(result, "stage", exc, {"repo_count": len(repositories)})

        try:
            result.classification_input_path = self.artifact_service.write_classification_input(
                report_date=target_date.isoformat(),
                items=items,
            )
            LOGGER.info("[stage] wrote classification input to %s", result.classification_input_path)
        except Exception as exc:  # noqa: BLE001
            self._record_stage_error(result, "artifact", exc, {"report_date": target_date.isoformat()})

        return result

    def ingest_classification_output(self, report_date: date | None = None, path: Path | None = None) -> DailyPipelineResult:
        target_date = report_date or datetime.now(UTC).date()
        initialize_schema(self.database_url)
        result = DailyPipelineResult(report_date=target_date)
        output_path = path or self.artifact_service.classification_output_path(target_date.isoformat())
        result.classification_output_path = output_path
        observations: list[CapabilityObservation] = []

        try:
            LOGGER.info("[ingest] reading classification output from %s", output_path)
            classified_repositories = self.artifact_service.read_classification_output(output_path)
            period_map = self._load_period_map(target_date)
            result.repos_ingested = len(period_map)
            observations = self._persist_classification_results(target_date, period_map, classified_repositories)
            result.capabilities_identified = len(observations)
            LOGGER.info("[ingest] persisted %s aggregated capabilities", result.capabilities_identified)
        except Exception as exc:  # noqa: BLE001
            self._record_stage_error(result, "classification_output", exc, {"path": str(output_path)})
            return result

        try:
            LOGGER.info("[diff] auto-configuring capability registry")
            result.alerts_generated = self._diff_and_persist(observations, target_date)
            LOGGER.info("[diff] generated %s alert-worthy capability updates", result.alerts_generated)
        except Exception as exc:  # noqa: BLE001
            self._record_stage_error(result, "diff", exc, {"observation_count": len(observations)})

        try:
            LOGGER.info("[report] generating markdown and json reports")
            result.markdown_report_path = self.report_service.generate_daily_report(target_date)
            result.json_report_path = self.report_service.generate_daily_report_json(target_date)
            LOGGER.info("[report] wrote reports to %s and %s", result.markdown_report_path, result.json_report_path)
        except Exception as exc:  # noqa: BLE001
            self._record_stage_error(result, "report", exc, {"report_date": target_date.isoformat()})

        return result

    def _collect_trending_repositories(self, report_date: date) -> list[TrendingRepo]:
        repositories: list[TrendingRepo] = []
        for period in ("daily", "weekly", "monthly"):
            for repo in self.collector.fetch_trending(period):
                repositories.append(
                    TrendingRepo(
                        snapshot_date=report_date.isoformat(),
                        period=repo.period,
                        rank=repo.rank,
                        repo_full_name=repo.repo_full_name,
                        repo_url=repo.repo_url,
                        description=repo.description,
                        language=repo.language,
                        stars=repo.stars,
                        forks=repo.forks,
                    )
                )
        return repositories

    def _build_classification_items(self, repositories: list[TrendingRepo]) -> list[dict[str, object]]:
        grouped: dict[str, dict[str, object]] = {}
        for repo in repositories:
            entry = grouped.setdefault(
                repo.repo_full_name,
                {
                    "repo_full_name": repo.repo_full_name,
                    "repo_url": repo.repo_url,
                    "description": repo.description,
                    "language": repo.language,
                    "periods": set(),
                },
            )
            entry["periods"].add(repo.period)
            if entry["description"] is None and repo.description:
                entry["description"] = repo.description
            if entry["language"] is None and repo.language:
                entry["language"] = repo.language

        items: list[dict[str, object]] = []
        for repo_full_name in sorted(grouped):
            entry = grouped[repo_full_name]
            supplemental = self.metadata_fetcher.fetch(repo_full_name)
            periods = sorted(str(period) for period in entry["periods"])
            topics = sorted(set(str(topic) for topic in supplemental.topics if topic))
            items.append(
                {
                    "repo_full_name": repo_full_name,
                    "repo_url": entry["repo_url"],
                    "description": entry["description"],
                    "language": entry["language"],
                    "topics": topics,
                    "periods": periods,
                    "readme_excerpt": self._truncate_text(supplemental.readme, 4000),
                    "candidate_texts": self._collect_candidate_texts(
                        repo_full_name=repo_full_name,
                        description=entry["description"],
                        readme=supplemental.readme,
                        topics=topics,
                        language=str(entry["language"]) if entry["language"] else None,
                        periods=periods,
                    ),
                }
            )
        return items

    def _persist_classification_results(
        self,
        report_date: date,
        period_map: dict[str, tuple[str, ...]],
        records: list[RepoClassificationRecord],
    ) -> list[CapabilityObservation]:
        seen_ids: dict[str, CapabilityObservation] = {}
        snapshot_date = report_date.isoformat()
        for record in records:
            periods = period_map.get(record.repo_full_name)
            if periods is None:
                raise ValueError(f"Classification output contains unknown repo '{record.repo_full_name}'.")
            self._persist_repo_capabilities(
                snapshot_date=snapshot_date,
                periods=periods,
                repo_full_name=record.repo_full_name,
                capabilities=record.capabilities,
            )
            for capability in record.capabilities:
                candidate = CapabilityObservation(
                    capability_id=capability.capability_id,
                    canonical_name=self.normalizer.capability_name(capability.capability_id),
                    summary=capability.summary,
                    score=capability.confidence,
                    observed_at=f"{report_date.isoformat()}T00:00:00Z",
                    source_repo_full_name=record.repo_full_name,
                    consecutive_appearances=1,
                )
                existing = seen_ids.get(capability.capability_id)
                if existing is None or candidate.score > existing.score:
                    seen_ids[capability.capability_id] = candidate
        return sorted(seen_ids.values(), key=lambda item: (-item.score, item.capability_id))

    def _diff_and_persist(self, observations: list[CapabilityObservation], report_date: date) -> int:
        alert_count = 0
        for observation in observations:
            existing = self.registry.get_capability(observation.capability_id)
            diff_result = self.diff_service.analyze(observation, existing)
            auto_action = self._select_auto_action(observation.score)
            updated = self._merge_registry_record(observation, existing, auto_action)
            self.registry.upsert_capability(updated)
            self.registry.add_approval(
                CapabilityApproval(
                    capability_id=observation.capability_id,
                    action=auto_action,
                    resulting_status=updated.status,
                    reviewer="auto-config",
                    note=f"Automatically configured from score={observation.score:.2f} and diff={diff_result.decision}.",
                    snapshot_date=report_date.isoformat(),
                )
            )
            if diff_result.should_alert:
                alert_count += 1
        return alert_count

    @staticmethod
    def _select_auto_action(score: float) -> CapabilityApprovalAction:
        if score >= 0.9:
            return CapabilityApprovalAction.ACTIVATE
        if score >= 0.75:
            return CapabilityApprovalAction.POC
        if score >= 0.55:
            return CapabilityApprovalAction.WATCHLIST
        return CapabilityApprovalAction.IGNORE

    def _persist_repo_capabilities(
        self,
        *,
        snapshot_date: str,
        periods: tuple[str, ...],
        repo_full_name: str,
        capabilities: tuple[object, ...],
    ) -> None:
        with get_connection(self.database_url) as connection:
            for period in periods:
                for capability in capabilities:
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
                        ON CONFLICT(snapshot_date, period, repo_full_name, capability_id)
                        DO UPDATE SET
                            confidence = excluded.confidence,
                            reason = excluded.reason,
                            summary = excluded.summary,
                            needs_review = excluded.needs_review,
                            created_at = excluded.created_at
                        """,
                        (
                            snapshot_date,
                            period,
                            repo_full_name,
                            capability.capability_id,
                            capability.confidence,
                            capability.reason,
                            capability.summary,
                            int(capability.needs_review),
                            _utc_now(),
                        ),
                    )
            connection.commit()

    def _load_period_map(self, report_date: date) -> dict[str, tuple[str, ...]]:
        with get_connection(self.database_url) as connection:
            rows = connection.execute(
                """
                SELECT repo_full_name, period
                FROM trending_repos
                WHERE snapshot_date = ?
                ORDER BY repo_full_name ASC, period ASC
                """,
                (report_date.isoformat(),),
            ).fetchall()
        grouped: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            grouped[str(row["repo_full_name"])].append(str(row["period"]))
        return {repo: tuple(dict.fromkeys(periods)) for repo, periods in grouped.items()}

    def _merge_registry_record(
        self,
        observation: CapabilityObservation,
        existing: CapabilityRegistryRecord | None,
        auto_action: CapabilityApprovalAction,
    ) -> CapabilityRegistryRecord:
        resulting_status = auto_action.resulting_status
        if existing is None:
            return CapabilityRegistryRecord(
                capability_id=observation.capability_id,
                canonical_name=observation.canonical_name,
                status=resulting_status,
                summary=observation.summary,
                first_seen_at=observation.observed_at,
                last_seen_at=observation.observed_at,
                last_score=observation.score,
                mention_count=1,
                consecutive_appearances=observation.consecutive_appearances,
                source_repo_full_name=observation.source_repo_full_name,
            )
        return CapabilityRegistryRecord(
            capability_id=existing.capability_id,
            canonical_name=observation.canonical_name or existing.canonical_name,
            status=self._max_status(existing.status, resulting_status),
            summary=observation.summary or existing.summary,
            first_seen_at=existing.first_seen_at,
            last_seen_at=observation.observed_at,
            last_score=max(existing.last_score, observation.score),
            mention_count=existing.mention_count + 1,
            consecutive_appearances=max(
                existing.consecutive_appearances,
                observation.consecutive_appearances,
            ),
            source_repo_full_name=observation.source_repo_full_name or existing.source_repo_full_name,
            created_at=existing.created_at,
        )

    @staticmethod
    def _max_status(left: CapabilityStatus, right: CapabilityStatus) -> CapabilityStatus:
        order = {
            CapabilityStatus.DEPRECATED: 0,
            CapabilityStatus.WATCHLIST: 1,
            CapabilityStatus.POC: 2,
            CapabilityStatus.ACTIVE: 3,
            CapabilityStatus.REJECTED: 0,
            CapabilityStatus.PENDING_REVIEW: 1,
        }
        return left if order[left] >= order[right] else right

    def _record_stage_error(
        self,
        result: ClassificationInputBuildResult | DailyPipelineResult,
        stage: str,
        exc: Exception,
        context: dict[str, object],
    ) -> None:
        message = f"[{stage}] {exc} | context={context}"
        LOGGER.exception(message)
        result.stage_errors.append(message)

    @staticmethod
    def _collect_candidate_texts(
        *,
        repo_full_name: str,
        description: object,
        readme: str | None,
        topics: list[str],
        language: str | None,
        periods: list[str],
    ) -> list[str]:
        candidates: list[str] = []
        candidates.extend(OrchestrationService._chunk_text(repo_full_name.replace("/", " ")))
        if isinstance(description, str):
            candidates.extend(OrchestrationService._chunk_text(description))
        if readme:
            candidates.extend(OrchestrationService._chunk_text(readme))
        candidates.extend(topic for topic in topics if topic)
        if language:
            candidates.append(language)
        candidates.extend(f"trending period {period}" for period in periods)
        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = candidate.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    @staticmethod
    def _chunk_text(text: str) -> list[str]:
        stripped = text.strip()
        if not stripped:
            return []
        normalized = re.sub(r"\r\n?", "\n", stripped)
        parts = re.split(r"[\n•\-*]+|(?<=[.!?])\s+", normalized)
        cleaned: list[str] = []
        for part in parts:
            candidate = re.sub(r"\s+", " ", part).strip(" #`>*")
            if len(candidate) < 3:
                continue
            cleaned.append(candidate[:240])
        return cleaned

    @staticmethod
    def _truncate_text(value: str | None, limit: int) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "..."


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
