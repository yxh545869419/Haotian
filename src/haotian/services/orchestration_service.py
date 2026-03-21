"""Daily pipeline orchestration service."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from haotian.analyzers.capability_classifier import CapabilityClassifier, RepoMetadata
from haotian.collectors.github_trending import GithubTrendingCollector, TrendingRepo
from haotian.db.schema import get_connection, initialize_schema
from haotian.registry.capability_registry import (
    CapabilityApproval,
    CapabilityApprovalAction,
    CapabilityRegistryRecord,
    CapabilityRegistryRepository,
    CapabilityStatus,
)
from haotian.services.diff_service import CapabilityObservation, DiffService
from haotian.services.ingest_service import IngestService
from haotian.services.report_service import ReportService

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DailyPipelineResult:
    report_date: date
    repos_ingested: int = 0
    capabilities_identified: int = 0
    alerts_generated: int = 0
    report_path: Path | None = None
    stage_errors: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return not self.stage_errors


class OrchestrationService:
    """Run the MVP daily workflow end to end against the local SQLite database."""

    def __init__(
        self,
        *,
        collector: GithubTrendingCollector | None = None,
        ingest_service: IngestService | None = None,
        classifier: CapabilityClassifier | None = None,
        diff_service: DiffService | None = None,
        registry: CapabilityRegistryRepository | None = None,
        report_service: ReportService | None = None,
        database_url: str | None = None,
    ) -> None:
        self.database_url = database_url
        self.collector = collector or GithubTrendingCollector()
        self.ingest_service = ingest_service or IngestService(database_url=database_url)
        self.classifier = classifier or CapabilityClassifier()
        self.diff_service = diff_service or DiffService()
        self.registry = registry or CapabilityRegistryRepository(database_url=database_url)
        self.report_service = report_service or ReportService(database_url=database_url)

    def run_daily_pipeline(self, report_date: date | None = None) -> DailyPipelineResult:
        target_date = report_date or datetime.now(UTC).date()
        initialize_schema(self.database_url)
        result = DailyPipelineResult(report_date=target_date)
        repositories: list[TrendingRepo] = []
        metadata_items: list[tuple[RepoMetadata, str, str]] = []
        observations: list[CapabilityObservation] = []

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
            LOGGER.info("[enrich] building repository metadata for %s records", len(repositories))
            metadata_items = [self._build_repo_metadata(repo) for repo in repositories]
        except Exception as exc:  # noqa: BLE001
            self._record_stage_error(result, "enrich", exc, {"repo_count": len(repositories)})

        try:
            LOGGER.info("[analyze] classifying repository capabilities")
            observations = self._analyze_capabilities(metadata_items, target_date)
            result.capabilities_identified = len(observations)
            LOGGER.info("[analyze] identified %s aggregated capabilities", result.capabilities_identified)
        except Exception as exc:  # noqa: BLE001
            self._record_stage_error(result, "analyze", exc, {"repo_count": len(metadata_items)})

        try:
            LOGGER.info("[diff] auto-configuring capability registry")
            result.alerts_generated = self._diff_and_persist(observations, target_date)
            LOGGER.info("[diff] generated %s alert-worthy capability updates", result.alerts_generated)
        except Exception as exc:  # noqa: BLE001
            self._record_stage_error(result, "diff", exc, {"observation_count": len(observations)})

        try:
            LOGGER.info("[report] generating markdown report")
            result.report_path = self.report_service.generate_daily_report(target_date)
            LOGGER.info("[report] wrote report to %s", result.report_path)
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

    def _analyze_capabilities(
        self,
        metadata_items: list[tuple[RepoMetadata, str, str]],
        report_date: date,
    ) -> list[CapabilityObservation]:
        seen_ids: dict[str, CapabilityObservation] = {}
        for metadata, period, snapshot_date in metadata_items:
            classification = self.classifier.classify(metadata)
            self._persist_repo_capabilities(
                snapshot_date=snapshot_date,
                period=period,
                repo_full_name=metadata.repo_full_name,
                capabilities=classification.capabilities,
            )
            for capability in classification.capabilities:
                candidate = CapabilityObservation(
                    capability_id=capability.capability_id,
                    canonical_name=capability.name,
                    summary=capability.summary,
                    score=capability.confidence,
                    observed_at=f"{report_date.isoformat()}T00:00:00Z",
                    source_repo_full_name=metadata.repo_full_name,
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

    @staticmethod
    def _build_repo_metadata(repo: TrendingRepo) -> tuple[RepoMetadata, str, str]:
        return (
            RepoMetadata(
                repo_full_name=repo.repo_full_name,
                description=repo.description,
                language=repo.language,
                topics=[repo.language] if repo.language else [],
                tags=[repo.period],
            ),
            repo.period,
            repo.snapshot_date,
        )

    def _persist_repo_capabilities(
        self,
        *,
        snapshot_date: str,
        period: str,
        repo_full_name: str,
        capabilities: list[object],
    ) -> None:
        with get_connection(self.database_url) as connection:
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
        result: DailyPipelineResult,
        stage: str,
        exc: Exception,
        context: dict[str, object],
    ) -> None:
        message = f"[{stage}] {exc} | context={context}"
        LOGGER.exception(message)
        result.stage_errors.append(message)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
