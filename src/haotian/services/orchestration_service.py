"""Skill-first daily pipeline orchestration service."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
import re

from haotian.analyzers.capability_normalizer import CapabilityNormalizer
from haotian.config import get_settings
from haotian.collectors.github_repository_metadata import GithubRepositoryMetadataFetcher
from haotian.collectors.github_repository_metadata import RepositoryMetadataPayload
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
from haotian.services.repository_analysis_cache_service import RepositoryAnalysisCacheService
from haotian.services.repository_analysis_service import RepositoryAnalysisResult
from haotian.services.repository_analysis_service import RepositoryAnalysisService
from haotian.services.report_service import ReportService
from haotian.services.repository_skill_package_service import DiscoveredSkillPackage
from haotian.services.skill_sync_service import SkillSyncCandidate, SkillSyncService

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ClassificationInputBuildResult:
    """Staged input artifact summary."""

    report_date: date
    repos_ingested: int = 0
    repository_items: int = 0
    deep_analyzed_repos: int = 0
    cached_reused_repos: int = 0
    fallback_repos: int = 0
    skipped_due_to_budget: int = 0
    cleanup_warnings: int = 0
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
    deep_analyzed_repos: int = 0
    cached_reused_repos: int = 0
    fallback_repos: int = 0
    skipped_due_to_budget: int = 0
    cleanup_warnings: int = 0
    markdown_report_path: Path | None = None
    json_report_path: Path | None = None
    classification_output_path: Path | None = None
    capability_audit_path: Path | None = None
    taxonomy_gap_candidates_path: Path | None = None
    skill_sync_report_path: Path | None = None
    auto_promoted_capabilities: list[dict[str, object]] = field(default_factory=list)
    risky_enhancement_candidates: list[dict[str, object]] = field(default_factory=list)
    manual_attention_items: list[dict[str, object]] = field(default_factory=list)
    taxonomy_gap_candidates: list[dict[str, object]] = field(default_factory=list)
    skill_sync_summary: dict[str, object] = field(default_factory=dict)
    skill_sync_actions: list[dict[str, object]] = field(default_factory=list)
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
        skill_sync_service: SkillSyncService | None = None,
        metadata_fetcher: GithubRepositoryMetadataFetcher | None = None,
        artifact_service: ClassificationArtifactService | None = None,
        repository_analysis_service: RepositoryAnalysisService | None = None,
        analysis_cache_service: RepositoryAnalysisCacheService | None = None,
        repository_tmp_dir: Path | None = None,
        max_deep_analysis_repos: int | None = None,
        database_url: str | None = None,
    ) -> None:
        self.database_url = database_url
        self.collector = collector or GithubTrendingCollector()
        self.ingest_service = ingest_service or IngestService(database_url=database_url)
        self.diff_service = diff_service or DiffService()
        self.registry = registry or CapabilityRegistryRepository(database_url=database_url)
        self.report_service = report_service or ReportService(database_url=database_url)
        self.skill_sync_service = skill_sync_service or SkillSyncService()
        self.metadata_fetcher = metadata_fetcher or GithubRepositoryMetadataFetcher()
        self.artifact_service = artifact_service or ClassificationArtifactService()
        self.repository_analysis_service = repository_analysis_service
        self.analysis_cache_service = analysis_cache_service or RepositoryAnalysisCacheService(database_url=database_url)
        self.repository_tmp_dir = repository_tmp_dir
        self.max_deep_analysis_repos = max_deep_analysis_repos
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
            self._clear_repo_analysis_snapshots(target_date)
            cleanup_warning = self._remove_classification_input(target_date)
            if cleanup_warning:
                result.stage_errors.append(cleanup_warning)
            return result

        try:
            LOGGER.info("[stage] building classification input artifact for %s trending rows", len(repositories))
            analysis_service = self._resolve_repository_analysis_service(target_date)
            items, analysis_results = self._build_classification_items(
                repositories,
                report_date=target_date,
                analysis_service=analysis_service,
            )
            result.repository_items = len(items)
            result.deep_analyzed_repos = sum(1 for analysis_result in analysis_results if analysis_result.analysis_depth != "fallback")
            result.cached_reused_repos = sum(1 for analysis_result in analysis_results if analysis_result.analysis_source == "cache")
            result.fallback_repos = sum(1 for analysis_result in analysis_results if analysis_result.fallback_used)
            result.skipped_due_to_budget = sum(
                1 for analysis_result in analysis_results if any("deep-analysis budget" in limit for limit in analysis_result.analysis_limits)
            )
            result.cleanup_warnings = sum(
                1 for analysis_result in analysis_results if analysis_result.cleanup_required and not analysis_result.cleanup_completed
            )
        except Exception as exc:  # noqa: BLE001
            self._record_stage_error(result, "stage", exc, {"repo_count": len(repositories)})
            self._clear_repo_analysis_snapshots(target_date)
            cleanup_warning = self._remove_classification_input(target_date)
            if cleanup_warning:
                result.stage_errors.append(cleanup_warning)
            return result

        try:
            result.classification_input_path = self.artifact_service.write_classification_input(
                report_date=target_date.isoformat(),
                items=items,
            )
            LOGGER.info("[stage] wrote classification input to %s", result.classification_input_path)
        except Exception as exc:  # noqa: BLE001
            self._record_stage_error(result, "artifact", exc, {"report_date": target_date.isoformat()})
            self._clear_repo_analysis_snapshots(target_date)
            cleanup_warning = self._remove_classification_input(target_date)
            if cleanup_warning:
                result.stage_errors.append(cleanup_warning)
            return result

        return result

    def ingest_classification_output(self, report_date: date | None = None, path: Path | None = None) -> DailyPipelineResult:
        target_date = report_date or datetime.now(UTC).date()
        initialize_schema(self.database_url)
        result = DailyPipelineResult(report_date=target_date)
        output_path = path or self.artifact_service.classification_output_path(target_date.isoformat())
        result.classification_output_path = output_path
        analysis_counters = self._load_repo_analysis_counters(target_date)
        result.deep_analyzed_repos = analysis_counters["deep_analyzed_repos"]
        result.cached_reused_repos = analysis_counters["cached_reused_repos"]
        result.fallback_repos = analysis_counters["fallback_repos"]
        result.skipped_due_to_budget = analysis_counters["skipped_due_to_budget"]
        result.cleanup_warnings = analysis_counters["cleanup_warnings"]
        observations: list[CapabilityObservation] = []
        result.skill_sync_summary = self.artifact_service.default_skill_sync_summary()

        try:
            LOGGER.info("[ingest] reading classification output from %s", output_path)
            classified_repositories = self.artifact_service.read_classification_output(output_path)
            period_map = self._load_period_map(target_date)
            result.repos_ingested = len(period_map)
            self._clear_repo_capabilities(target_date)
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
            LOGGER.info("[audit] auto-auditing enhancement candidates and taxonomy gaps")
            audit_payload = self._run_enhancement_audit(target_date)
            taxonomy_gap_payload = self._build_taxonomy_gap_candidates(target_date, classified_repositories)
            result.capability_audit_path = self.artifact_service.write_json_artifact(
                path=self.artifact_service.capability_audit_path(target_date.isoformat()),
                payload=audit_payload,
            )
            result.taxonomy_gap_candidates_path = self.artifact_service.write_json_artifact(
                path=self.artifact_service.taxonomy_gap_candidates_path(target_date.isoformat()),
                payload=taxonomy_gap_payload,
            )
            result.auto_promoted_capabilities = list(audit_payload["auto_promoted"])
            result.risky_enhancement_candidates = list(audit_payload["risky_enhancement_candidates"])
            result.manual_attention_items = list(audit_payload["manual_attention"])
            result.taxonomy_gap_candidates = list(taxonomy_gap_payload["candidates"])
        except Exception as exc:  # noqa: BLE001
            self._record_stage_error(result, "audit", exc, {"report_date": target_date.isoformat()})

        skill_sync_payload = self.artifact_service.empty_skill_sync_report_payload(target_date.isoformat())
        try:
            LOGGER.info("[skill-sync] deriving deterministic skill sync candidates")
            sync_candidates = self._build_skill_sync_candidates(target_date, classified_repositories)
            skill_sync_result = self.skill_sync_service.sync(
                report_date=target_date,
                candidates=sync_candidates,
            )
            skill_sync_payload = skill_sync_result.to_payload()
        except Exception as exc:  # noqa: BLE001
            self._record_stage_error(result, "skill_sync", exc, {"report_date": target_date.isoformat()})
        finally:
            try:
                result.skill_sync_report_path = self.artifact_service.write_json_artifact(
                    path=self.artifact_service.skill_sync_report_path(target_date.isoformat()),
                    payload=skill_sync_payload,
                )
                result.skill_sync_summary = dict(skill_sync_payload.get("summary", {}))
                result.skill_sync_actions = [
                    dict(item)
                    for item in skill_sync_payload.get("actions", [])
                    if isinstance(item, dict)
                ]
            except Exception as exc:  # noqa: BLE001
                self._record_stage_error(result, "skill_sync_artifact", exc, {"report_date": target_date.isoformat()})

        try:
            LOGGER.info("[report] generating markdown and json reports")
            result.markdown_report_path = self.report_service.generate_daily_report(target_date)
            result.json_report_path = self.report_service.generate_daily_report_json(target_date)
            LOGGER.info("[report] wrote reports to %s and %s", result.markdown_report_path, result.json_report_path)
        except Exception as exc:  # noqa: BLE001
            self._record_stage_error(result, "report", exc, {"report_date": target_date.isoformat()})

        return result

    def _build_skill_sync_candidates(
        self,
        report_date: date,
        classified_repositories: list[RepoClassificationRecord],
    ) -> list[SkillSyncCandidate]:
        capability_ids_by_repo = {
            record.repo_full_name: tuple(capability.capability_id for capability in record.capabilities)
            for record in classified_repositories
        }
        candidates: list[SkillSyncCandidate] = []
        seen: set[tuple[str, str, str]] = set()
        for item in self.artifact_service.read_classification_input_items(report_date.isoformat()):
            repo_full_name = str(item.get("repo_full_name", "")).strip()
            repo_url = str(item.get("repo_url", "")).strip()
            packages = item.get("discovered_skill_packages", [])
            if not isinstance(packages, list):
                continue
            for raw_package in packages:
                if not isinstance(raw_package, dict):
                    continue
                package = DiscoveredSkillPackage.from_serialized_payload(raw_package)
                slug = self._build_skill_candidate_slug(package, repo_full_name)
                key = (slug, repo_full_name, package.relative_root)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    SkillSyncCandidate(
                        slug=slug,
                        display_name=package.skill_name or slug,
                        source_repo_full_name=repo_full_name,
                        repo_url=repo_url,
                        relative_root=package.relative_root or ".",
                        files=package.files,
                        capability_ids=capability_ids_by_repo.get(repo_full_name, ()),
                    )
                )
        candidates.sort(key=lambda item: (item.slug.casefold(), item.source_repo_full_name.casefold(), item.relative_root.casefold()))
        return candidates

    @staticmethod
    def _build_skill_candidate_slug(package: DiscoveredSkillPackage, repo_full_name: str) -> str:
        candidate = package.skill_name.strip()
        if not candidate:
            candidate = package.relative_root.strip().split("/")[-1] or repo_full_name.rsplit("/", 1)[-1]
        slug = re.sub(r"[^a-z0-9]+", "-", candidate.lower()).strip("-")
        return slug or repo_full_name.rsplit("/", 1)[-1].lower()

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

    def _build_classification_items(
        self,
        repositories: list[TrendingRepo],
        *,
        report_date: date,
        analysis_service: RepositoryAnalysisService,
    ) -> tuple[list[dict[str, object]], list[RepositoryAnalysisResult]]:
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

        sorted_repo_names = sorted(grouped)
        supplemental_by_repo = {
            repo_full_name: self.metadata_fetcher.fetch(repo_full_name)
            for repo_full_name in sorted_repo_names
        }
        analysis_results_by_repo: dict[str, RepositoryAnalysisResult] = {}
        fresh_queue: list[tuple[str, dict[str, object], RepositoryMetadataPayload]] = []

        for repo_full_name in sorted_repo_names:
            entry = grouped[repo_full_name]
            supplemental = supplemental_by_repo[repo_full_name]
            cached = self.analysis_cache_service.load(repo_full_name)
            if cached is not None and not self.analysis_cache_service.should_refresh(
                cached=cached,
                current_pushed_at=getattr(supplemental, "pushed_at", None),
            ):
                analysis_results_by_repo[repo_full_name] = cached.to_reused_result(repo_url=str(entry["repo_url"]))
                continue
            fresh_queue.append((repo_full_name, entry, supplemental))

        batch_size = self._resolve_analysis_batch_size()
        total_batches = max(1, (len(fresh_queue) + batch_size - 1) // batch_size) if fresh_queue else 0
        analyzed_at = f"{report_date.isoformat()}T00:00:00Z"

        for batch_index, batch_start in enumerate(range(0, len(fresh_queue), batch_size), start=1):
            batch = fresh_queue[batch_start : batch_start + batch_size]
            LOGGER.info(
                "[stage] analyzing deep batch %s/%s with %s repositories",
                batch_index,
                total_batches,
                len(batch),
            )
            for repo_full_name, entry, supplemental in batch:
                analysis_result = analysis_service.analyze_repository(
                    repo_full_name=repo_full_name,
                    repo_url=str(entry["repo_url"]),
                    allow_deep_analysis=True,
                )
                analysis_results_by_repo[repo_full_name] = analysis_result
                if self._should_cache_analysis_result(analysis_result):
                    self.analysis_cache_service.upsert(
                        result=analysis_result,
                        source_pushed_at=getattr(supplemental, "pushed_at", None),
                        analyzed_at=analyzed_at,
                    )

        items: list[dict[str, object]] = []
        analysis_results: list[RepositoryAnalysisResult] = []
        for repo_full_name in sorted_repo_names:
            entry = grouped[repo_full_name]
            supplemental = supplemental_by_repo[repo_full_name]
            periods = sorted(str(period) for period in entry["periods"])
            topics = sorted(set(str(topic) for topic in supplemental.topics if topic))
            analysis_result = analysis_results_by_repo[repo_full_name]
            self._persist_repo_analysis_snapshot(report_date=report_date, result=analysis_result)
            analysis_results.append(analysis_result)
            items.append(
                {
                    "repo_full_name": repo_full_name,
                    "repo_url": entry["repo_url"],
                    "description": entry["description"],
                    "language": entry["language"],
                    "topics": topics,
                    "periods": periods,
                    "repo_pushed_at": supplemental.pushed_at,
                    "readme_excerpt": self._truncate_text(supplemental.readme, 4000),
                    "candidate_texts": self._collect_candidate_texts(
                        repo_full_name=repo_full_name,
                        description=entry["description"],
                        readme=supplemental.readme,
                        topics=topics,
                        language=str(entry["language"]) if entry["language"] else None,
                        periods=periods,
                    ),
                    **analysis_result.to_classification_input_fields(),
                }
            )
        self._reconcile_repo_analysis_snapshots(report_date=report_date, active_repo_full_names=tuple(sorted(grouped)))
        return items, analysis_results

    def _resolve_analysis_batch_size(self) -> int:
        batch_size = self.max_deep_analysis_repos
        if batch_size is None:
            batch_size = get_settings().max_deep_analysis_repos
        return max(1, int(batch_size))

    @staticmethod
    def _should_cache_analysis_result(result: RepositoryAnalysisResult) -> bool:
        return (
            result.analysis_depth != "fallback"
            and result.analysis_completed
            and result.cleanup_completed
            and not result.fallback_used
        )

    def _resolve_repository_analysis_service(self, report_date: date) -> RepositoryAnalysisService:
        if self.repository_analysis_service is not None:
            return self.repository_analysis_service
        settings = get_settings()
        base_dir = self.repository_tmp_dir or settings.tmp_repo_dir
        return RepositoryAnalysisService(run_label=report_date.isoformat(), base_dir=base_dir)

    def _load_repo_analysis_counters(self, report_date: date) -> dict[str, int]:
        counters = {
            "deep_analyzed_repos": 0,
            "cached_reused_repos": 0,
            "fallback_repos": 0,
            "skipped_due_to_budget": 0,
            "cleanup_warnings": 0,
        }
        with get_connection(self.database_url) as connection:
            rows = connection.execute(
                """
                SELECT analysis_source, analysis_depth, fallback_used, cleanup_required, cleanup_completed, analysis_limits
                FROM repo_analysis_snapshots
                WHERE snapshot_date = ?
                """,
                (report_date.isoformat(),),
            ).fetchall()

        for row in rows:
            analysis_source = str(row["analysis_source"] or "")
            analysis_depth = str(row["analysis_depth"] or "")
            fallback_used = bool(row["fallback_used"])
            cleanup_required = bool(row["cleanup_required"])
            cleanup_completed = bool(row["cleanup_completed"])
            analysis_limits = self._parse_json_list(row["analysis_limits"])

            if analysis_depth != "fallback":
                counters["deep_analyzed_repos"] += 1
            if analysis_source == "cache":
                counters["cached_reused_repos"] += 1
            if fallback_used:
                counters["fallback_repos"] += 1
            if any("deep-analysis budget" in limit for limit in analysis_limits):
                counters["skipped_due_to_budget"] += 1
            if cleanup_required and not cleanup_completed:
                counters["cleanup_warnings"] += 1

        return counters

    def _persist_repo_analysis_snapshot(self, *, report_date: date, result: RepositoryAnalysisResult) -> None:
        with get_connection(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO repo_analysis_snapshots (
                    snapshot_date,
                    repo_full_name,
                    repo_url,
                    analysis_source,
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_date, repo_full_name)
                DO UPDATE SET
                    repo_url = excluded.repo_url,
                    analysis_source = excluded.analysis_source,
                    analysis_depth = excluded.analysis_depth,
                    clone_strategy = excluded.clone_strategy,
                    clone_started = excluded.clone_started,
                    analysis_completed = excluded.analysis_completed,
                    cleanup_attempted = excluded.cleanup_attempted,
                    cleanup_required = excluded.cleanup_required,
                    cleanup_completed = excluded.cleanup_completed,
                    fallback_used = excluded.fallback_used,
                    root_files = excluded.root_files,
                    matched_files = excluded.matched_files,
                    matched_keywords = excluded.matched_keywords,
                    architecture_signals = excluded.architecture_signals,
                    probe_summary = excluded.probe_summary,
                    evidence_snippets = excluded.evidence_snippets,
                    analysis_limits = excluded.analysis_limits
                """,
                (
                    report_date.isoformat(),
                    result.repo_full_name,
                    result.repo_url,
                    result.analysis_source,
                    result.analysis_depth,
                    result.clone_strategy,
                    int(result.clone_started),
                    int(result.analysis_completed),
                    int(result.cleanup_attempted),
                    int(result.cleanup_required),
                    int(result.cleanup_completed),
                    int(result.fallback_used),
                    json.dumps(list(result.root_files), ensure_ascii=False),
                    json.dumps(list(result.matched_files), ensure_ascii=False),
                    json.dumps(list(result.matched_keywords), ensure_ascii=False),
                    json.dumps(list(result.architecture_signals), ensure_ascii=False),
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
                    json.dumps(list(result.analysis_limits), ensure_ascii=False),
                ),
            )
            connection.commit()

    def _reconcile_repo_analysis_snapshots(self, *, report_date: date, active_repo_full_names: tuple[str, ...]) -> None:
        snapshot_date = report_date.isoformat()
        with get_connection(self.database_url) as connection:
            if active_repo_full_names:
                placeholders = ", ".join("?" for _ in active_repo_full_names)
                connection.execute(
                    f"""
                    DELETE FROM repo_analysis_snapshots
                    WHERE snapshot_date = ?
                      AND repo_full_name NOT IN ({placeholders})
                    """,
                    (snapshot_date, *active_repo_full_names),
                )
            else:
                connection.execute(
                    "DELETE FROM repo_analysis_snapshots WHERE snapshot_date = ?",
                    (snapshot_date,),
            )
            connection.commit()

    def _clear_repo_analysis_snapshots(self, report_date: date) -> None:
        with get_connection(self.database_url) as connection:
            connection.execute(
                "DELETE FROM repo_analysis_snapshots WHERE snapshot_date = ?",
                (report_date.isoformat(),),
            )
            connection.commit()

    def _clear_repo_capabilities(self, report_date: date) -> None:
        with get_connection(self.database_url) as connection:
            connection.execute(
                "DELETE FROM repo_capabilities WHERE snapshot_date = ?",
                (report_date.isoformat(),),
            )
            connection.commit()

    def _remove_classification_input(self, report_date: date) -> str | None:
        input_path = self.artifact_service.classification_input_path(report_date.isoformat())
        if input_path.exists():
            try:
                input_path.unlink()
            except PermissionError as exc:
                return f"cleanup warning: {exc} | context={{'path': '{input_path}'}}"
        return None

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

    def _run_enhancement_audit(self, report_date: date) -> dict[str, object]:
        promotable: list[object] = []
        sections = self.report_service._load_sections(report_date)
        for item in sections["enhancement_candidates"]:
            if self._can_auto_promote_enhancement(item):
                promotable.append(item)

        auto_promoted: list[dict[str, object]] = []
        for item in promotable:
            existing = self.registry.get_capability(item.capability_id)
            if existing is None or existing.status is CapabilityStatus.ACTIVE:
                continue
            updated = CapabilityRegistryRecord(
                capability_id=existing.capability_id,
                canonical_name=existing.canonical_name,
                status=CapabilityStatus.ACTIVE,
                summary=item.summary or existing.summary,
                first_seen_at=existing.first_seen_at,
                last_seen_at=f"{report_date.isoformat()}T00:00:00Z",
                last_score=max(existing.last_score, item.base_score),
                mention_count=existing.mention_count,
                consecutive_appearances=existing.consecutive_appearances,
                source_repo_full_name=item.source_repos[0] if item.source_repos else existing.source_repo_full_name,
                created_at=existing.created_at,
            )
            self.registry.upsert_capability(updated)
            self.registry.add_approval(
                CapabilityApproval(
                    capability_id=item.capability_id,
                    action=CapabilityApprovalAction.ACTIVATE,
                    resulting_status=CapabilityStatus.ACTIVE,
                    reviewer="auto-audit",
                    note="Automatically promoted after low-risk enhancement audit.",
                    snapshot_date=report_date.isoformat(),
                )
            )
            auto_promoted.append(
                {
                    "capability_id": item.capability_id,
                    "display_name": item.display_name,
                    "from_status": existing.status.value,
                    "to_status": CapabilityStatus.ACTIVE.value,
                    "reason": "证据完整、无人工关注、无回退且基础分达到自动增强阈值。",
                    "source_repos": list(item.source_repos),
                }
            )

        sections = self.report_service._load_sections(report_date)
        return {
            "schema_version": 1,
            "report_date": report_date.isoformat(),
            "auto_promoted": auto_promoted,
            "risky_enhancement_candidates": [
                self._serialize_audit_item(item, reasons=self._enhancement_blockers(item))
                for item in sections["enhancement_candidates"]
                if self._enhancement_blockers(item)
            ],
            "manual_attention": [
                self._serialize_audit_item(item, reasons=self._manual_attention_reasons(item))
                for item in sections["manual_attention"]
            ],
        }

    @staticmethod
    def _can_auto_promote_enhancement(item: object) -> bool:
        return (
            item.status == "enhancement_candidates"
            and not item.needs_manual_attention
            and not item.fallback_used
            and item.cleanup_completed
            and item.base_score >= 0.85
            and bool(item.matched_files)
        )

    @staticmethod
    def _enhancement_blockers(item: object) -> list[str]:
        blockers: list[str] = []
        if item.needs_manual_attention:
            blockers.append("仍存在需要人工确认的仓库级信号。")
        if item.fallback_used:
            blockers.append("至少部分证据来自 fallback analysis。")
        if not item.cleanup_completed:
            blockers.append("临时仓库清理未完成。")
        if item.base_score < 0.85:
            blockers.append("基础分低于自动增强阈值 0.85。")
        if not item.matched_files:
            blockers.append("缺少稳定的命中文件证据。")
        return blockers

    def _manual_attention_reasons(self, item: object) -> list[str]:
        reasons = self._enhancement_blockers(item)
        if not reasons:
            reasons.append("存在人工关注标记，需要人工复核。")
        return reasons

    @staticmethod
    def _serialize_audit_item(item: object, *, reasons: list[str]) -> dict[str, object]:
        return {
            "capability_id": item.capability_id,
            "display_name": item.display_name,
            "status": item.status,
            "status_label": item.status,
            "base_score": item.base_score,
            "source_repos": list(item.source_repos),
            "reasons": reasons,
            "suggestion": item.suggestion,
        }

    def _build_taxonomy_gap_candidates(
        self,
        report_date: date,
        classified_repositories: list[RepoClassificationRecord],
    ) -> dict[str, object]:
        items_by_repo = {
            str(item.get("repo_full_name")): item
            for item in self.artifact_service.read_classification_input_items(report_date.isoformat())
        }
        grouped: dict[str, dict[str, object]] = {}
        for record in classified_repositories:
            if record.capabilities:
                continue
            item = items_by_repo.get(record.repo_full_name)
            if item is None:
                continue
            inferred = self._infer_taxonomy_gap_candidate(item)
            if inferred is None:
                continue
            bucket = grouped.setdefault(
                inferred["candidate_id"],
                {
                    "candidate_id": inferred["candidate_id"],
                    "display_name": inferred["display_name"],
                    "reason": inferred["reason"],
                    "repo_full_names": [],
                },
            )
            bucket["repo_full_names"].append(record.repo_full_name)

        candidates = [
            {
                **value,
                "repo_full_names": sorted(value["repo_full_names"]),
                "repo_count": len(value["repo_full_names"]),
            }
            for value in grouped.values()
        ]
        candidates.sort(key=lambda item: (-int(item["repo_count"]), str(item["candidate_id"])))
        return {
            "schema_version": 1,
            "report_date": report_date.isoformat(),
            "candidates": candidates,
        }

    @staticmethod
    def _infer_taxonomy_gap_candidate(item: dict[str, object]) -> dict[str, str] | None:
        texts = [
            str(item.get("repo_full_name") or ""),
            str(item.get("description") or ""),
            str(item.get("readme_excerpt") or ""),
            " ".join(str(value) for value in item.get("topics") or []),
            " ".join(str(value) for value in item.get("matched_keywords") or []),
            " ".join(str(value) for value in item.get("architecture_signals") or []),
        ]
        blob = " ".join(texts).lower()
        if any(token in blob for token in ("video", "youtube", "twitter", "tweet", "outreach", "affiliate", "content")):
            return {
                "candidate_id": "content_generation",
                "display_name": "内容生成 / 营销自动化",
                "reason": "仓库更像内容生产或营销自动化工具，当前 taxonomy 没有覆盖这一能力。",
            }
        if any(token in blob for token in ("memory", "context", "context database", "resource", "vault")):
            return {
                "candidate_id": "memory_context_management",
                "display_name": "记忆与上下文管理",
                "reason": "仓库核心价值是为代理存储、管理和供给记忆/上下文，当前 taxonomy 仅用 information_retrieval 覆盖仍偏窄。",
            }
        if any(token in blob for token in ("vulnerability", "misconfiguration", "secret", "sbom", "security")):
            return {
                "candidate_id": "security_analysis",
                "display_name": "安全分析",
                "reason": "仓库主要面向漏洞、配置错误、密钥或 SBOM 扫描，当前 taxonomy 没有对应能力。",
            }
        if any(token in blob for token in ("plugin", "hook", "slash-command", "statusline", "awesome skills")):
            return {
                "candidate_id": "skill_plugin_ecosystem",
                "display_name": "技能与插件生态",
                "reason": "仓库主要提供技能、插件或代理扩展生态，不适合强行归入现有 taxonomy。",
            }
        if any(token in blob for token in ("training", "fine-tuning", "open models", "gemma", "qwen")):
            return {
                "candidate_id": "model_training",
                "display_name": "模型训练与微调",
                "reason": "仓库主线是模型训练或微调，不适合归入现有能力 taxonomy。",
            }
        return None

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
    def _parse_json_list(raw_value: object) -> list[str]:
        if isinstance(raw_value, str) and raw_value.strip():
            try:
                payload = json.loads(raw_value)
            except Exception:  # noqa: BLE001
                return []
            if isinstance(payload, list):
                return [str(item) for item in payload]
        return []

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
