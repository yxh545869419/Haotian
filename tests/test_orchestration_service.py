from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import date
from pathlib import Path

from haotian.collectors.github_trending import TrendingRepo
from haotian.services.repository_analysis_service import EvidenceSnippet as AnalysisEvidenceSnippet
from haotian.services.repository_analysis_service import RepositoryAnalysisResult
from haotian.services.repository_analysis_service import RepositoryAnalysisService
from haotian.services.repository_probe_service import RepositoryProbeService
from haotian.registry.capability_registry import CapabilityRegistryRecord
from haotian.registry.capability_registry import CapabilityRegistryRepository, CapabilityStatus
from haotian.services.classification_artifact_service import ClassificationArtifactService
from haotian.services.orchestration_service import OrchestrationService
from haotian.services.report_service import ReportService
from haotian.services.skill_sync_service import SkillSyncAction
from haotian.services.skill_sync_service import SkillSyncCandidate
from haotian.services.skill_sync_service import SkillSyncResult
from haotian.db.schema import get_connection


class StubCollector:
    def fetch_trending(self, period: str) -> list[TrendingRepo]:
        fixtures = {
            "daily": [
                TrendingRepo(
                    snapshot_date="2026-03-20",
                    period="daily",
                    rank=1,
                    repo_full_name="acme/browser-bot",
                    repo_url="https://github.com/acme/browser-bot",
                    description="Browser automation agent for websites.",
                    language="Python",
                    stars=100,
                    forks=10,
                )
            ],
            "weekly": [
                TrendingRepo(
                    snapshot_date="2026-03-20",
                    period="weekly",
                    rank=1,
                    repo_full_name="acme/browser-bot",
                    repo_url="https://github.com/acme/browser-bot",
                    description="Browser automation agent for websites.",
                    language="Python",
                    stars=120,
                    forks=12,
                )
            ],
            "monthly": [
                TrendingRepo(
                    snapshot_date="2026-03-20",
                    period="monthly",
                    rank=1,
                    repo_full_name="acme/extractor",
                    repo_url="https://github.com/acme/extractor",
                    description="Data extraction pipeline for unstructured documents.",
                    language="Python",
                    stars=80,
                    forks=8,
                )
            ],
        }
        return fixtures[period]


class StubMetadataFetcher:
    def __init__(self, payloads=None) -> None:  # noqa: ANN001
        from haotian.collectors.github_repository_metadata import RepositoryMetadataPayload

        default_payloads = {
            "acme/browser-bot": RepositoryMetadataPayload(
                readme="Browser automation workflows for websites.",
                topics=("browser-agent",),
                pushed_at="2026-03-01T00:00:00Z",
            ),
            "acme/extractor": RepositoryMetadataPayload(
                readme="Data extraction pipeline. Workflow orchestration across OCR and parsing jobs.",
                topics=("ocr", "automation"),
                pushed_at="2026-03-01T00:00:00Z",
            ),
            "acme/alpha": RepositoryMetadataPayload(
                readme="Alpha repo.",
                topics=("alpha",),
                pushed_at="2026-03-01T00:00:00Z",
            ),
            "acme/bravo": RepositoryMetadataPayload(
                readme="Bravo repo.",
                topics=("bravo",),
                pushed_at="2026-03-01T00:00:00Z",
            ),
            "acme/charlie": RepositoryMetadataPayload(
                readme="Charlie repo.",
                topics=("charlie",),
                pushed_at="2026-03-01T00:00:00Z",
            ),
        }
        if payloads:
            default_payloads.update(payloads)
        self.payloads = default_payloads

    def fetch(self, repo_full_name: str):
        return self.payloads[repo_full_name]


class StubRepositoryAnalysisService:
    def __init__(self, results_by_repo: dict[str, RepositoryAnalysisResult]) -> None:
        self.results_by_repo = results_by_repo
        self.calls: list[tuple[str, bool]] = []

    def analyze_repository(
        self,
        *,
        repo_full_name: str,
        repo_url: str,
        allow_deep_analysis: bool = True,
        report_date: date | None = None,
    ) -> RepositoryAnalysisResult:
        del repo_url, report_date
        self.calls.append((repo_full_name, allow_deep_analysis))
        result = self.results_by_repo[repo_full_name]
        if allow_deep_analysis:
            return result
        return RepositoryAnalysisResult(
            repo_full_name=result.repo_full_name,
            repo_url=result.repo_url,
            analysis_depth="fallback",
            clone_strategy="skipped-by-budget",
            clone_started=False,
            analysis_completed=False,
            cleanup_attempted=False,
            cleanup_required=False,
            cleanup_completed=False,
            fallback_used=True,
            root_files=(),
            matched_files=(),
            matched_keywords=(),
            architecture_signals=(),
            probe_summary=f"Skipped deep analysis for {repo_full_name} because the deep-analysis budget was exhausted.",
            evidence_snippets=(),
            analysis_limits=("skipped due to deep-analysis budget",),
        )


def make_layered_result(
    repo_full_name: str,
    *,
    repo_url: str = "https://github.com/acme/demo",
    discovered_skill_packages=(),
) -> RepositoryAnalysisResult:
    return RepositoryAnalysisResult(
        repo_full_name=repo_full_name,
        repo_url=repo_url,
        analysis_depth="layered",
        clone_strategy="shallow-clone",
        clone_started=True,
        analysis_completed=True,
        cleanup_attempted=True,
        cleanup_required=True,
        cleanup_completed=True,
        fallback_used=False,
        root_files=("README.md", "pyproject.toml"),
        matched_files=("README.md", "pyproject.toml", "main.py", "workflow.py"),
        matched_keywords=("README*", "pyproject.toml", "main*", "workflow*"),
        architecture_signals=("documentation-first", "entrypoint-driven", "workflow-orchestration"),
        probe_summary="Layered analysis complete.",
        evidence_snippets=(
            AnalysisEvidenceSnippet(
                path="README.md",
                excerpt="Overview",
                why_it_matters="Shows the repository purpose.",
            ),
        ),
        analysis_limits=(),
        discovered_skill_packages=discovered_skill_packages,
    )


def build_service(
    tmp_path,
    *,
    repository_analysis_service: RepositoryAnalysisService | StubRepositoryAnalysisService | None = None,
    collector: StubCollector | None = None,
    metadata_fetcher: StubMetadataFetcher | None = None,
    repository_tmp_dir: Path | None = None,
    max_deep_analysis_repos: int | None = None,
    skill_sync_service=None,
):
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    report_dir = tmp_path / "reports"
    run_dir = tmp_path / "runs"
    return OrchestrationService(
        collector=collector or StubCollector(),
        metadata_fetcher=metadata_fetcher or StubMetadataFetcher(),
        artifact_service=ClassificationArtifactService(base_dir=run_dir),
        report_service=ReportService(database_url=database_url, report_dir=report_dir),
        repository_analysis_service=repository_analysis_service,
        repository_tmp_dir=repository_tmp_dir,
        max_deep_analysis_repos=max_deep_analysis_repos,
        skill_sync_service=skill_sync_service,
        database_url=database_url,
    )


class StubSkillSyncService:
    def __init__(self) -> None:
        self.calls: list[tuple[date, tuple[SkillSyncCandidate, ...]]] = []

    def sync(
        self,
        *,
        report_date: date,
        candidates,
        inventory=None,
    ) -> SkillSyncResult:
        del inventory
        normalized = tuple(candidates)
        self.calls.append((report_date, normalized))
        return SkillSyncResult(
            report_date=report_date,
            summary={
                "config_ready": True,
                "candidate_count": len(normalized),
                "action_count": 1,
                "aligned_existing": 1,
                "installed_new": 0,
                "discarded_non_integrable": 0,
                "blocked_audit_failure": 0,
                "blocked_ambiguous_match": 0,
                "rolled_back_install_failure": 0,
            },
            actions=(
                SkillSyncAction(
                    action="aligned_existing",
                    slug="browser-bot",
                    display_name="browser-bot",
                    source_repo_full_name="acme/browser-bot",
                    repo_url="https://github.com/acme/browser-bot",
                    relative_root=".",
                    files=("SKILL.md",),
                    matched_installed_slug="browser-bot",
                    matched_installed_path=str(Path("managed") / "browser-bot"),
                ),
            ),
        )


class BudgetCollector:
    def fetch_trending(self, period: str) -> list[TrendingRepo]:
        fixtures = {
            "daily": [
                TrendingRepo(
                    snapshot_date="2026-03-20",
                    period="daily",
                    rank=1,
                    repo_full_name="acme/alpha",
                    repo_url="https://github.com/acme/alpha",
                    description="Alpha repo.",
                    language="Python",
                    stars=100,
                    forks=10,
                )
            ],
            "weekly": [
                TrendingRepo(
                    snapshot_date="2026-03-20",
                    period="weekly",
                    rank=1,
                    repo_full_name="acme/bravo",
                    repo_url="https://github.com/acme/bravo",
                    description="Bravo repo.",
                    language="Python",
                    stars=90,
                    forks=9,
                )
            ],
            "monthly": [
                TrendingRepo(
                    snapshot_date="2026-03-20",
                    period="monthly",
                    rank=1,
                    repo_full_name="acme/charlie",
                    repo_url="https://github.com/acme/charlie",
                    description="Charlie repo.",
                    language="Python",
                    stars=80,
                    forks=8,
                )
            ],
        }
        return fixtures[period]


class MutableCollector:
    def __init__(self, repo_full_names: list[str]) -> None:
        self.repo_full_names = repo_full_names

    def fetch_trending(self, period: str) -> list[TrendingRepo]:
        return [
            TrendingRepo(
                snapshot_date="2026-03-20",
                period=period,
                rank=index + 1,
                repo_full_name=repo_full_name,
                repo_url=f"https://github.com/{repo_full_name}",
                description=f"{repo_full_name} description.",
                language="Python",
                stars=100 - index,
                forks=10 - index,
            )
            for index, repo_full_name in enumerate(self.repo_full_names)
        ]


def test_build_classification_input_writes_repo_metadata(tmp_path) -> None:
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/browser-bot": make_layered_result("acme/browser-bot", repo_url="https://github.com/acme/browser-bot"),
            "acme/extractor": make_layered_result("acme/extractor", repo_url="https://github.com/acme/extractor"),
        }
    )
    service = build_service(tmp_path, repository_analysis_service=analysis_service)

    result = service.build_classification_input(date(2026, 3, 20))

    payload = json.loads(result.classification_input_path.read_text(encoding="utf-8"))
    assert result.repos_ingested == 2
    assert result.repository_items == 2
    assert result.stage_errors == []
    assert result.deep_analyzed_repos == 2
    assert result.fallback_repos == 0
    assert result.skipped_due_to_budget == 0
    assert result.cleanup_warnings == 0
    assert payload["report_date"] == "2026-03-20"
    assert payload["items"][0]["repo_full_name"] == "acme/browser-bot"
    assert payload["items"][0]["periods"] == ["daily", "weekly"]
    assert "Browser automation workflows for websites." in payload["items"][0]["candidate_texts"]
    assert payload["items"][0]["analysis_depth"] == "layered"
    assert payload["items"][0]["clone_strategy"] == "shallow-clone"
    assert payload["items"][0]["clone_started"] is True
    assert payload["items"][0]["analysis_completed"] is True
    assert payload["items"][0]["cleanup_attempted"] is True
    assert payload["items"][0]["cleanup_required"] is True
    assert payload["items"][0]["cleanup_completed"] is True
    assert payload["items"][0]["fallback_used"] is False

    with sqlite3.connect(tmp_path / "app.db") as connection:
        row_count = connection.execute("SELECT COUNT(*) FROM repo_analysis_snapshots").fetchone()[0]
    assert row_count == 2


def test_build_classification_input_aborts_on_ingest_failure_and_clears_snapshots(tmp_path, monkeypatch) -> None:
    service = build_service(tmp_path)

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002, ARG001
        raise RuntimeError("ingest failed")

    monkeypatch.setattr(service.ingest_service, "ingest_trending_repos", boom)

    result = service.build_classification_input(date(2026, 3, 20))

    assert result.stage_errors
    assert result.classification_input_path is None
    assert result.repository_items == 0
    with sqlite3.connect(tmp_path / "app.db") as connection:
        row_count = connection.execute(
            "SELECT COUNT(*) FROM repo_analysis_snapshots WHERE snapshot_date = ?",
            ("2026-03-20",),
        ).fetchone()[0]
    assert row_count == 0


def test_build_classification_input_removes_stale_input_when_same_date_ingest_fails(tmp_path, monkeypatch) -> None:
    service = build_service(tmp_path)
    first = service.build_classification_input(date(2026, 3, 20))
    assert first.classification_input_path is not None
    assert first.classification_input_path.exists()

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002, ARG001
        raise RuntimeError("ingest failed")

    monkeypatch.setattr(service.ingest_service, "ingest_trending_repos", boom)

    second = service.build_classification_input(date(2026, 3, 20))

    assert second.stage_errors
    assert second.classification_input_path is None
    assert not first.classification_input_path.exists()


def test_build_classification_input_survives_permission_error_when_removing_stale_input(
    tmp_path,
    monkeypatch,
) -> None:
    service = build_service(tmp_path)
    first = service.build_classification_input(date(2026, 3, 20))
    assert first.classification_input_path is not None
    assert first.classification_input_path.exists()

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002, ARG001
        raise RuntimeError("ingest failed")

    monkeypatch.setattr(service.ingest_service, "ingest_trending_repos", boom)

    def fail_unlink(*args, **kwargs):  # noqa: ANN001, ANN002, ARG001
        raise PermissionError("file is open")

    monkeypatch.setattr(type(first.classification_input_path), "unlink", fail_unlink)

    second = service.build_classification_input(date(2026, 3, 20))

    assert second.stage_errors
    assert second.classification_input_path is None
    assert any("cleanup warning" in error for error in second.stage_errors)


def test_get_connection_closes_connection_on_exit(tmp_path, monkeypatch) -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.row_factory = None
            self.closed = False

        def close(self) -> None:
            self.closed = True

        def __enter__(self):  # noqa: ANN001
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            del exc_type, exc, tb
            return False

    fake_connection = FakeConnection()
    monkeypatch.setattr("haotian.db.schema.sqlite3.connect", lambda db_path: fake_connection)

    with get_connection(f"sqlite:///{tmp_path / 'app.db'}") as connection:
        assert connection is fake_connection

    assert fake_connection.closed is True


def test_repository_analysis_service_marks_clone_failure_before_workspace_assignment(tmp_path, monkeypatch) -> None:
    analysis_service = RepositoryAnalysisService(run_label="2026-03-20", base_dir=tmp_path / "tmp-repos")

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002, ARG001
        raise RuntimeError("clone failed")

    monkeypatch.setattr("haotian.services.repository_workspace_service.RepositoryWorkspaceService.clone_repo", boom)

    result = analysis_service.analyze_repository(
        repo_full_name="acme/browser-bot",
        repo_url="https://github.com/acme/browser-bot",
    )

    assert result.analysis_depth == "fallback"
    assert result.clone_started is False
    assert result.cleanup_attempted is False
    assert result.cleanup_completed is False
    assert result.cleanup_required is False
    assert result.fallback_used is True
    assert result.analysis_completed is False


def test_repository_analysis_service_falls_back_when_workspace_path_validation_fails(tmp_path, monkeypatch) -> None:
    analysis_service = RepositoryAnalysisService(run_label="2026-03-20", base_dir=tmp_path / "tmp-repos")

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002, ARG001
        raise ValueError("workspace path alias detected")

    monkeypatch.setattr("haotian.services.repository_workspace_service.RepositoryWorkspaceService.workspace_path", boom)

    result = analysis_service.analyze_repository(
        repo_full_name="acme/browser-bot",
        repo_url="https://github.com/acme/browser-bot",
    )

    assert result.analysis_depth == "fallback"
    assert result.clone_started is False
    assert result.cleanup_attempted is False
    assert result.cleanup_completed is False
    assert result.cleanup_required is False
    assert result.fallback_used is True
    assert result.analysis_completed is False


def test_repository_analysis_service_cleans_up_partial_clone_when_clone_fails_after_workspace_creation(
    tmp_path,
    monkeypatch,
) -> None:
    analysis_service = RepositoryAnalysisService(run_label="2026-03-20", base_dir=tmp_path / "tmp-repos")

    def partial_clone(self, *, repo_full_name, repo_url):  # noqa: ANN001, ANN002, ARG001
        target = self.workspace_path(repo_full_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir(parents=True, exist_ok=True)
        (target / "PARTIAL.txt").write_text("partial clone\n", encoding="utf-8")
        raise RuntimeError("clone failed after workspace creation")

    monkeypatch.setattr("haotian.services.repository_workspace_service.RepositoryWorkspaceService.clone_repo", partial_clone)

    result = analysis_service.analyze_repository(
        repo_full_name="acme/browser-bot",
        repo_url="https://github.com/acme/browser-bot",
    )

    target = analysis_service.workspace_service.workspace_path("acme/browser-bot")
    assert result.analysis_depth == "fallback"
    assert result.cleanup_required is True
    assert result.cleanup_attempted is True
    assert result.cleanup_completed is True
    assert not target.exists()
    assert result.fallback_used is True
    assert result.analysis_completed is False


def test_build_classification_input_batches_all_repositories_under_batch_size(tmp_path) -> None:
    results_by_repo = {
        "acme/alpha": make_layered_result("acme/alpha", repo_url="https://github.com/acme/alpha"),
        "acme/bravo": make_layered_result("acme/bravo", repo_url="https://github.com/acme/bravo"),
        "acme/charlie": make_layered_result("acme/charlie", repo_url="https://github.com/acme/charlie"),
    }
    analysis_service = StubRepositoryAnalysisService(results_by_repo)
    service = build_service(
        tmp_path,
        collector=BudgetCollector(),
        repository_analysis_service=analysis_service,
        max_deep_analysis_repos=1,
    )

    result = service.build_classification_input(date(2026, 3, 20))
    payload = json.loads(result.classification_input_path.read_text(encoding="utf-8"))

    assert result.deep_analyzed_repos == 3
    assert result.fallback_repos == 0
    assert result.skipped_due_to_budget == 0
    assert result.cached_reused_repos == 0
    assert analysis_service.calls == [
        ("acme/alpha", True),
        ("acme/bravo", True),
        ("acme/charlie", True),
    ]
    assert all(item["analysis_depth"] == "layered" for item in payload["items"])
    assert all(item["analysis_source"] == "fresh" for item in payload["items"])


def test_build_classification_input_clears_partial_snapshots_on_mid_stage_failure(tmp_path) -> None:
    class ExplodingAnalysisService:
        def __init__(self) -> None:
            self.calls = 0

        def analyze_repository(
            self,
            *,
            repo_full_name: str,
            repo_url: str,
            allow_deep_analysis: bool = True,
        ) -> RepositoryAnalysisResult:
            self.calls += 1
            if self.calls == 1:
                return make_layered_result(repo_full_name, repo_url=repo_url)
            raise RuntimeError("analysis failed mid-stage")

    service = build_service(
        tmp_path,
        collector=BudgetCollector(),
        repository_analysis_service=ExplodingAnalysisService(),
        max_deep_analysis_repos=3,
    )

    result = service.build_classification_input(date(2026, 3, 20))

    assert result.stage_errors
    with sqlite3.connect(tmp_path / "app.db") as connection:
        row_count = connection.execute(
            "SELECT COUNT(*) FROM repo_analysis_snapshots WHERE snapshot_date = ?",
            ("2026-03-20",),
        ).fetchone()[0]
    assert row_count == 0


def test_repository_analysis_service_preserves_config_and_code_signals_under_budget(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.name", "Test User"], check=True)
    write_paths = {
        "README.md": "# Demo\n",
        "doc-0.md": "doc 0\n",
        "doc-1.md": "doc 1\n",
        "doc-2.md": "doc 2\n",
        "doc-3.md": "doc 3\n",
        "pyproject.toml": "[project]\nname = \"demo\"\n",
        "main.py": "def main() -> None:\n    pass\n",
        "workflow.py": "def run_workflow() -> None:\n    pass\n",
    }
    for relative_path, content in write_paths.items():
        file_path = source / relative_path
        file_path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", relative_path], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-m", "initial"], check=True)

    service = RepositoryAnalysisService(
        run_label="2026-03-20",
        base_dir=tmp_path / "tmp-repos",
        probe_service=RepositoryProbeService(max_files=4, max_file_bytes=256),
    )
    result = service.analyze_repository(
        repo_full_name="acme/demo",
        repo_url=str(source),
    )

    assert result.analysis_depth == "layered"
    assert "README.md" in result.matched_files
    assert "pyproject.toml" in result.matched_files
    assert "main.py" in result.matched_files
    assert "workflow.py" in result.matched_files
    assert not any(path.startswith("doc-") for path in result.matched_files)
    assert result.cleanup_completed is True


def test_ingest_classification_output_uses_repo_analysis_snapshots_for_final_counters(tmp_path) -> None:
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/alpha": make_layered_result("acme/alpha", repo_url="https://github.com/acme/alpha"),
            "acme/bravo": make_layered_result("acme/bravo", repo_url="https://github.com/acme/bravo"),
            "acme/charlie": make_layered_result("acme/charlie", repo_url="https://github.com/acme/charlie"),
        }
    )
    service = build_service(
        tmp_path,
        collector=BudgetCollector(),
        repository_analysis_service=analysis_service,
        max_deep_analysis_repos=1,
    )

    staged = service.build_classification_input(date(2026, 3, 20))
    assert not service.artifact_service.run_summary_path("2026-03-20").exists()

    output_path = staged.classification_input_path.with_name("classification-output.json")
    output_path.write_text(
        json.dumps(
            [
                {
                    "repo_full_name": "acme/alpha",
                    "capabilities": [],
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = service.ingest_classification_output(date(2026, 3, 20), output_path)

    assert result.deep_analyzed_repos == 3
    assert result.fallback_repos == 0
    assert result.skipped_due_to_budget == 0
    assert result.cached_reused_repos == 0
    assert result.cleanup_warnings == 0


def test_build_classification_input_reuses_cached_analysis_until_repo_pushed_at_advances_by_90_days(tmp_path) -> None:
    from haotian.collectors.github_repository_metadata import RepositoryMetadataPayload
    from haotian.services.repository_skill_package_service import DiscoveredSkillPackage

    package_root = tmp_path / "source"
    discovered_skill_packages = (
        DiscoveredSkillPackage(
            skill_name="browser-bot",
            package_root=package_root,
            relative_root=".",
            files=("SKILL.md",),
        ),
        DiscoveredSkillPackage(
            skill_name="browser",
            package_root=package_root / "skills" / "browser",
            relative_root="skills/browser",
            files=("SKILL.md", "skill_runner.py"),
        ),
    )
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/alpha": make_layered_result(
                "acme/alpha",
                repo_url="https://github.com/acme/alpha",
                discovered_skill_packages=discovered_skill_packages,
            ),
        }
    )
    collector = MutableCollector(["acme/alpha"])
    metadata_fetcher = StubMetadataFetcher(
        {
            "acme/alpha": RepositoryMetadataPayload(
                readme="Alpha repo.",
                topics=("alpha",),
                pushed_at="2025-12-01T00:00:00Z",
            )
        }
    )
    service = build_service(
        tmp_path,
        collector=collector,
        metadata_fetcher=metadata_fetcher,
        repository_analysis_service=analysis_service,
        max_deep_analysis_repos=1,
    )

    first = service.build_classification_input(date(2026, 3, 20))
    first_payload = json.loads(first.classification_input_path.read_text(encoding="utf-8"))
    assert first.deep_analyzed_repos == 1
    assert first.cached_reused_repos == 0
    assert analysis_service.calls == [("acme/alpha", True)]

    analysis_service.calls.clear()
    second = service.build_classification_input(date(2026, 3, 21))
    second_payload = json.loads(second.classification_input_path.read_text(encoding="utf-8"))
    assert second.deep_analyzed_repos == 1
    assert second.cached_reused_repos == 1
    assert analysis_service.calls == []
    assert first_payload["items"][0]["discovered_skill_packages"] == [
        {
            "skill_name": "browser-bot",
            "relative_root": ".",
            "files": ["SKILL.md"],
        },
        {
            "skill_name": "browser",
            "relative_root": "skills/browser",
            "files": ["SKILL.md", "skill_runner.py"],
        },
    ]
    assert second_payload["items"][0]["discovered_skill_packages"] == first_payload["items"][0]["discovered_skill_packages"]
    assert second_payload["items"][0]["analysis_source"] == "cache"

    metadata_fetcher.payloads["acme/alpha"] = RepositoryMetadataPayload(
        readme="Alpha repo refreshed.",
        topics=("alpha",),
        pushed_at="2026-03-05T00:00:00Z",
    )
    third = service.build_classification_input(date(2026, 3, 22))
    third_payload = json.loads(third.classification_input_path.read_text(encoding="utf-8"))
    assert third.deep_analyzed_repos == 1
    assert third.cached_reused_repos == 0
    assert analysis_service.calls == [("acme/alpha", True)]
    assert third_payload["items"][0]["analysis_source"] == "fresh"


def test_build_classification_input_reconciles_repo_analysis_snapshots_for_same_date_rerun(tmp_path) -> None:
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/alpha": make_layered_result("acme/alpha", repo_url="https://github.com/acme/alpha"),
            "acme/bravo": make_layered_result("acme/bravo", repo_url="https://github.com/acme/bravo"),
            "acme/charlie": make_layered_result("acme/charlie", repo_url="https://github.com/acme/charlie"),
        }
    )
    collector = MutableCollector(["acme/alpha", "acme/bravo", "acme/charlie"])
    service = build_service(
        tmp_path,
        collector=collector,
        repository_analysis_service=analysis_service,
        max_deep_analysis_repos=3,
    )

    service.build_classification_input(date(2026, 3, 20))
    collector.repo_full_names = ["acme/alpha"]
    staged = service.build_classification_input(date(2026, 3, 20))

    with sqlite3.connect(tmp_path / "app.db") as connection:
        row_count = connection.execute(
            "SELECT COUNT(*) FROM repo_analysis_snapshots WHERE snapshot_date = ?",
            ("2026-03-20",),
        ).fetchone()[0]
    assert row_count == 1

    output_path = staged.classification_input_path.with_name("classification-output.json")
    output_path.write_text(
        json.dumps(
            [
                {
                    "repo_full_name": "acme/alpha",
                    "capabilities": [],
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = service.ingest_classification_output(date(2026, 3, 20), output_path)

    assert result.deep_analyzed_repos == 1
    assert result.fallback_repos == 0
    assert result.skipped_due_to_budget == 0


def test_build_classification_input_creates_date_scoped_analysis_service_per_report_date(
    tmp_path,
    monkeypatch,
) -> None:
    created: list[tuple[str, Path]] = []

    class FakeRepositoryAnalysisService:
        def __init__(self, *, run_label: str, base_dir: Path | str | None = None, **kwargs) -> None:
            del kwargs
            base_path = Path(base_dir) if base_dir is not None else Path("missing-base")
            created.append((run_label, base_path))
            self.run_label = run_label
            self.base_dir = base_path

        def analyze_repository(
            self,
            *,
            repo_full_name: str,
            repo_url: str,
            allow_deep_analysis: bool = True,
        ) -> RepositoryAnalysisResult:
            del allow_deep_analysis
            return make_layered_result(repo_full_name, repo_url=repo_url)

    monkeypatch.setattr("haotian.services.orchestration_service.RepositoryAnalysisService", FakeRepositoryAnalysisService)

    service = build_service(tmp_path, repository_tmp_dir=tmp_path / "tmp-repos")

    first = service.build_classification_input(date(2026, 3, 20))
    second = service.build_classification_input(date(2026, 3, 21))

    assert first.stage_errors == []
    assert second.stage_errors == []
    assert created == [
        ("2026-03-20", tmp_path / "tmp-repos"),
        ("2026-03-21", tmp_path / "tmp-repos"),
    ]


def test_ingest_classification_output_auto_configures_registry_and_generates_reports(tmp_path) -> None:
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/browser-bot": make_layered_result("acme/browser-bot", repo_url="https://github.com/acme/browser-bot"),
            "acme/extractor": make_layered_result("acme/extractor", repo_url="https://github.com/acme/extractor"),
        }
    )
    service = build_service(tmp_path, repository_analysis_service=analysis_service)
    staged = service.build_classification_input(date(2026, 3, 20))
    output_path = staged.classification_input_path.with_name("classification-output.json")
    output_path.write_text(
        json.dumps(
            [
                {
                    "repo_full_name": "acme/browser-bot",
                    "capabilities": [
                        {
                            "capability_id": "browser_automation",
                            "confidence": 0.93,
                            "reason": "The repo description and README both focus on browser workflows.",
                            "summary": "Automates browser workflows for websites.",
                            "needs_review": False,
                            "source_label": "codex",
                        }
                    ],
                },
                {
                    "repo_full_name": "acme/extractor",
                    "capabilities": [
                        {
                            "capability_id": "data_extraction",
                            "confidence": 0.9,
                            "reason": "The repo description focuses on extracting structured data from documents.",
                            "summary": "Extracts structured information from unstructured inputs.",
                            "needs_review": False,
                            "source_label": "codex",
                        },
                        {
                            "capability_id": "workflow_orchestration",
                            "confidence": 0.82,
                            "reason": "The README describes a multi-step OCR and parsing workflow.",
                            "summary": "Coordinates OCR and parsing steps into a repeatable workflow.",
                            "needs_review": False,
                            "source_label": "codex",
                        },
                    ],
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = service.ingest_classification_output(date(2026, 3, 20), output_path)

    assert result.repos_ingested == 2
    assert result.capabilities_identified == 3
    assert result.alerts_generated >= 2
    assert result.markdown_report_path == tmp_path / "reports" / "2026-03-20.md"
    assert result.json_report_path == tmp_path / "reports" / "2026-03-20.json"
    assert result.markdown_report_path.exists()
    assert result.json_report_path.exists()
    assert result.stage_errors == []

    repository = CapabilityRegistryRepository(database_url=f"sqlite:///{tmp_path / 'app.db'}")
    capabilities = {item.capability_id: item for item in repository.list_capabilities()}
    assert capabilities["browser_automation"].status in {
        CapabilityStatus.WATCHLIST,
        CapabilityStatus.POC,
        CapabilityStatus.ACTIVE,
    }
    assert capabilities["data_extraction"].status in {CapabilityStatus.WATCHLIST, CapabilityStatus.POC, CapabilityStatus.ACTIVE}
    assert "workflow_orchestration" in capabilities

    content = result.markdown_report_path.read_text(encoding="utf-8")
    assert "## 总览" in content
    assert "仓库变化：今日 2 个｜新增 2 个｜移除 0 个" in content
    assert "## 今日重点" in content
    assert "### 浏览器自动化 (`browser_automation`)" in content
    assert "### 数据提取 (`data_extraction`)" in content


def test_ingest_classification_output_removes_withdrawn_repo_capabilities_on_same_day_rerun(tmp_path) -> None:
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/browser-bot": make_layered_result("acme/browser-bot", repo_url="https://github.com/acme/browser-bot"),
            "acme/extractor": make_layered_result("acme/extractor", repo_url="https://github.com/acme/extractor"),
        }
    )
    service = build_service(tmp_path, repository_analysis_service=analysis_service)
    staged = service.build_classification_input(date(2026, 3, 20))
    output_path = staged.classification_input_path.with_name("classification-output.json")

    output_path.write_text(
        json.dumps(
            [
                {
                    "repo_full_name": "acme/browser-bot",
                    "capabilities": [
                        {
                            "capability_id": "browser_automation",
                            "confidence": 0.93,
                            "reason": "The repo centers on browser workflows.",
                            "summary": "Automates browser workflows for websites.",
                            "needs_review": False,
                            "source_label": "codex",
                        }
                    ],
                },
                {
                    "repo_full_name": "acme/extractor",
                    "capabilities": [],
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    service.ingest_classification_output(date(2026, 3, 20), output_path)

    output_path.write_text(
        json.dumps(
            [
                {
                    "repo_full_name": "acme/browser-bot",
                    "capabilities": [],
                },
                {
                    "repo_full_name": "acme/extractor",
                    "capabilities": [],
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    result = service.ingest_classification_output(date(2026, 3, 20), output_path)

    with get_connection(f"sqlite:///{tmp_path / 'app.db'}") as connection:
        withdrawn_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM repo_capabilities
            WHERE snapshot_date = ?
              AND repo_full_name = ?
              AND capability_id = ?
            """,
            ("2026-03-20", "acme/browser-bot", "browser_automation"),
        ).fetchone()[0]
    report_payload = json.loads(result.json_report_path.read_text(encoding="utf-8"))

    assert withdrawn_count == 0
    assert report_payload["summary"]["total_capabilities"] == 0


def test_ingest_classification_output_auto_promotes_low_risk_enhancement_candidates(tmp_path) -> None:
    class SummaryCollector:
        def fetch_trending(self, period: str) -> list[TrendingRepo]:
            return [
                TrendingRepo(
                    snapshot_date="2026-03-20",
                    period=period,
                    rank=1,
                    repo_full_name="acme/summary-skill",
                    repo_url="https://github.com/acme/summary-skill",
                    description="Summarizes multi-source research into concise briefs.",
                    language="Python",
                    stars=50,
                    forks=5,
                )
            ]

    from haotian.collectors.github_repository_metadata import RepositoryMetadataPayload

    metadata_fetcher = StubMetadataFetcher(
        {
            "acme/summary-skill": RepositoryMetadataPayload(
                readme="This repository researches recent topics and produces grounded summaries.",
                topics=("summary", "research"),
                pushed_at="2026-03-01T00:00:00Z",
            )
        }
    )
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/summary-skill": RepositoryAnalysisResult(
                repo_full_name="acme/summary-skill",
                repo_url="https://github.com/acme/summary-skill",
                analysis_depth="layered",
                clone_strategy="shallow-clone",
                clone_started=True,
                analysis_completed=True,
                cleanup_attempted=True,
                cleanup_required=True,
                cleanup_completed=True,
                fallback_used=False,
                root_files=("README.md", "SKILL.md"),
                matched_files=("README.md", "SKILL.md", "main.py"),
                matched_keywords=("README*", "*.md", "skill*", "main*"),
                architecture_signals=("documentation-first", "skill-centric", "entrypoint-driven"),
                probe_summary="Layered analysis complete.",
                evidence_snippets=(
                    AnalysisEvidenceSnippet(
                        path="README.md",
                        excerpt="Produces grounded summaries from multi-source research.",
                        why_it_matters="Summarization is the core user-facing behavior.",
                    ),
                ),
                analysis_limits=(),
            )
        }
    )
    service = build_service(
        tmp_path,
        collector=SummaryCollector(),
        metadata_fetcher=metadata_fetcher,
        repository_analysis_service=analysis_service,
    )
    staged = service.build_classification_input(date(2026, 3, 20))
    output_path = staged.classification_input_path.with_name("classification-output.json")
    output_path.write_text(
        json.dumps(
            [
                {
                    "repo_full_name": "acme/summary-skill",
                    "capabilities": [
                        {
                            "capability_id": "summarization",
                            "confidence": 0.86,
                            "reason": "The repository researches multiple sources and condenses them into grounded summaries.",
                            "summary": "Produces concise grounded summaries from multi-source research.",
                            "needs_review": False,
                            "source_label": "codex",
                        }
                    ],
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = service.ingest_classification_output(date(2026, 3, 20), output_path)

    repository = CapabilityRegistryRepository(database_url=f"sqlite:///{tmp_path / 'app.db'}")
    capability = repository.get_capability("summarization")
    audit_payload = json.loads((tmp_path / "runs" / "2026-03-20" / "capability-audit.json").read_text(encoding="utf-8"))
    report_payload = json.loads(result.json_report_path.read_text(encoding="utf-8"))

    assert capability is not None
    assert capability.status is CapabilityStatus.ACTIVE
    assert audit_payload["auto_promoted"][0]["capability_id"] == "summarization"
    assert audit_payload["manual_attention"] == []
    assert report_payload["summary"]["enhancement_candidates"] == 0
    assert report_payload["summary"]["covered"] == 1


def test_ingest_classification_output_writes_skill_sync_report_and_exposes_sync_payload(tmp_path) -> None:
    from haotian.services.repository_skill_package_service import DiscoveredSkillPackage

    class SingleRepoCollector:
        def fetch_trending(self, period: str) -> list[TrendingRepo]:
            return [
                TrendingRepo(
                    snapshot_date="2026-03-20",
                    period=period,
                    rank=1,
                    repo_full_name="acme/browser-bot",
                    repo_url="https://github.com/acme/browser-bot",
                    description="Browser automation agent for websites.",
                    language="Python",
                    stars=100,
                    forks=10,
                )
            ]

    discovered_skill_packages = (
        DiscoveredSkillPackage(
            skill_name="browser-bot",
            package_root=tmp_path / "source",
            relative_root=".",
            files=("SKILL.md",),
        ),
    )
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/browser-bot": make_layered_result(
                "acme/browser-bot",
                repo_url="https://github.com/acme/browser-bot",
                discovered_skill_packages=discovered_skill_packages,
            ),
        }
    )
    skill_sync_service = StubSkillSyncService()
    service = build_service(
        tmp_path,
        collector=SingleRepoCollector(),
        repository_analysis_service=analysis_service,
        skill_sync_service=skill_sync_service,
    )
    staged = service.build_classification_input(date(2026, 3, 20))
    output_path = staged.classification_input_path.with_name("classification-output.json")
    output_path.write_text(
        json.dumps(
            [
                {
                    "repo_full_name": "acme/browser-bot",
                    "capabilities": [
                        {
                            "capability_id": "browser_automation",
                            "confidence": 0.93,
                            "reason": "The repo centers on browser workflow automation.",
                            "summary": "Automates browser workflows for websites.",
                            "needs_review": False,
                            "source_label": "codex",
                        }
                    ],
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = service.ingest_classification_output(date(2026, 3, 20), output_path)
    report_payload = json.loads(result.json_report_path.read_text(encoding="utf-8"))
    sync_payload = json.loads((tmp_path / "runs" / "2026-03-20" / "skill-sync-report.json").read_text(encoding="utf-8"))

    assert skill_sync_service.calls
    assert skill_sync_service.calls[0][1][0].slug == "browser-bot"
    assert skill_sync_service.calls[0][1][0].capability_ids == ("browser_automation",)
    assert result.skill_sync_summary["aligned_existing"] == 1
    assert result.skill_sync_actions[0]["action"] == "aligned_existing"
    assert sync_payload["summary"]["aligned_existing"] == 1
    assert report_payload["skill_sync_summary"]["aligned_existing"] == 1
    assert report_payload["skill_sync_actions"][0]["action"] == "aligned_existing"


def test_ingest_classification_output_writes_taxonomy_gap_candidates_for_unclassified_repositories(tmp_path) -> None:
    class GapCollector:
        def fetch_trending(self, period: str) -> list[TrendingRepo]:
            fixtures = [
                (
                    "acme/money-printer",
                    "Automates the generation of short-form videos and social posts.",
                ),
                (
                    "acme/context-vault",
                    "Stores and serves agent memory, context, and resources.",
                ),
                (
                    "acme/security-scanner",
                    "Scans repositories for vulnerabilities, secrets, and misconfigurations.",
                ),
            ]
            return [
                TrendingRepo(
                    snapshot_date="2026-03-20",
                    period=period,
                    rank=index + 1,
                    repo_full_name=repo_full_name,
                    repo_url=f"https://github.com/{repo_full_name}",
                    description=description,
                    language="Python",
                    stars=30 - index,
                    forks=3 - index,
                )
                for index, (repo_full_name, description) in enumerate(fixtures)
            ]

    from haotian.collectors.github_repository_metadata import RepositoryMetadataPayload

    metadata_fetcher = StubMetadataFetcher(
        {
            "acme/money-printer": RepositoryMetadataPayload(
                readme="Creates videos, tweets, and outreach content automatically.",
                topics=("video", "youtube", "twitter"),
                pushed_at="2026-03-01T00:00:00Z",
            ),
            "acme/context-vault": RepositoryMetadataPayload(
                readme="A context and memory database for AI agents.",
                topics=("memory", "context"),
                pushed_at="2026-03-01T00:00:00Z",
            ),
            "acme/security-scanner": RepositoryMetadataPayload(
                readme="Finds vulnerabilities, secrets, and SBOM issues in source code.",
                topics=("security", "vulnerability"),
                pushed_at="2026-03-01T00:00:00Z",
            ),
        }
    )
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/money-printer": RepositoryAnalysisResult(
                repo_full_name="acme/money-printer",
                repo_url="https://github.com/acme/money-printer",
                analysis_depth="layered",
                clone_strategy="shallow-clone",
                clone_started=True,
                analysis_completed=True,
                cleanup_attempted=True,
                cleanup_required=True,
                cleanup_completed=True,
                fallback_used=False,
                root_files=("README.md",),
                matched_files=("README.md", "main.py", "docs/YouTube.md"),
                matched_keywords=("README*", "*.md", "main*", "docs/**/*.md"),
                architecture_signals=("documentation-first", "entrypoint-driven"),
                probe_summary="Layered analysis complete.",
                evidence_snippets=(),
                analysis_limits=(),
            ),
            "acme/context-vault": RepositoryAnalysisResult(
                repo_full_name="acme/context-vault",
                repo_url="https://github.com/acme/context-vault",
                analysis_depth="layered",
                clone_strategy="shallow-clone",
                clone_started=True,
                analysis_completed=True,
                cleanup_attempted=True,
                cleanup_required=True,
                cleanup_completed=True,
                fallback_used=False,
                root_files=("README.md",),
                matched_files=("README.md", "server.py", "memory.py"),
                matched_keywords=("README*", "server*", "main*", "app*"),
                architecture_signals=("documentation-first", "entrypoint-driven"),
                probe_summary="Layered analysis complete.",
                evidence_snippets=(),
                analysis_limits=(),
            ),
            "acme/security-scanner": RepositoryAnalysisResult(
                repo_full_name="acme/security-scanner",
                repo_url="https://github.com/acme/security-scanner",
                analysis_depth="layered",
                clone_strategy="shallow-clone",
                clone_started=True,
                analysis_completed=True,
                cleanup_attempted=True,
                cleanup_required=True,
                cleanup_completed=True,
                fallback_used=False,
                root_files=("README.md",),
                matched_files=("README.md", "cli.py", "scanner.py"),
                matched_keywords=("README*", "cli*", "main*", "server*"),
                architecture_signals=("documentation-first", "entrypoint-driven"),
                probe_summary="Layered analysis complete.",
                evidence_snippets=(),
                analysis_limits=(),
            ),
        }
    )
    service = build_service(
        tmp_path,
        collector=GapCollector(),
        metadata_fetcher=metadata_fetcher,
        repository_analysis_service=analysis_service,
    )
    staged = service.build_classification_input(date(2026, 3, 20))
    output_path = staged.classification_input_path.with_name("classification-output.json")
    output_path.write_text(
        json.dumps(
            [
                {"repo_full_name": "acme/money-printer", "capabilities": []},
                {"repo_full_name": "acme/context-vault", "capabilities": []},
                {"repo_full_name": "acme/security-scanner", "capabilities": []},
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    service.ingest_classification_output(date(2026, 3, 20), output_path)

    gap_payload = json.loads((tmp_path / "runs" / "2026-03-20" / "taxonomy-gap-candidates.json").read_text(encoding="utf-8"))
    candidate_ids = {item["candidate_id"] for item in gap_payload["candidates"]}
    display_names = {item["candidate_id"]: item["display_name"] for item in gap_payload["candidates"]}

    assert "content_generation" in candidate_ids
    assert "memory_context_management" in candidate_ids
    assert "security_analysis" in candidate_ids
    assert display_names["content_generation"] == "Content Generation / Marketing Automation"
    assert display_names["memory_context_management"] == "Memory & Context Management"
    assert display_names["security_analysis"] == "Security Analysis"
