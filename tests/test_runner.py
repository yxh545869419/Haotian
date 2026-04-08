from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from haotian.runner import run_once
from haotian.collectors.github_repository_metadata import RepositoryMetadataPayload
from haotian.services.classification_artifact_service import ClassificationArtifactService
from haotian.services.orchestration_service import OrchestrationService
from haotian.services.report_service import ReportService
from haotian.services.repository_skill_package_service import DiscoveredSkillPackage
from tests.test_orchestration_service import BudgetCollector
from tests.test_orchestration_service import MutableCollector
from tests.test_orchestration_service import StubCollector
from tests.test_orchestration_service import StubMetadataFetcher
from tests.test_orchestration_service import StubRepositoryAnalysisService
from tests.test_orchestration_service import make_layered_result


def build_runner_service(
    tmp_path,
    *,
    collector: StubCollector | BudgetCollector | None = None,
    metadata_fetcher: StubMetadataFetcher | None = None,
    repository_analysis_service: StubRepositoryAnalysisService | None = None,
    max_deep_analysis_repos: int | None = None,
) -> OrchestrationService:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    return OrchestrationService(
        collector=collector or StubCollector(),
        metadata_fetcher=metadata_fetcher or StubMetadataFetcher(),
        artifact_service=ClassificationArtifactService(base_dir=tmp_path / "runs"),
        report_service=ReportService(database_url=database_url, report_dir=tmp_path / "reports"),
        repository_analysis_service=repository_analysis_service,
        max_deep_analysis_repos=max_deep_analysis_repos,
        database_url=database_url,
    )


def test_runner_stages_then_finalizes_reports(tmp_path) -> None:
    discovered_skill_packages = (
        DiscoveredSkillPackage(
            skill_name="browser-bot",
            package_root=tmp_path / "source" / "skills" / "browser-bot",
            relative_root="skills/browser-bot",
            files=("SKILL.md", "README.md", "settings.json"),
        ),
    )
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/browser-bot": make_layered_result(
                "acme/browser-bot",
                repo_url="https://github.com/acme/browser-bot",
                discovered_skill_packages=discovered_skill_packages,
            ),
            "acme/extractor": make_layered_result("acme/extractor", repo_url="https://github.com/acme/extractor"),
        }
    )
    service = build_runner_service(tmp_path, repository_analysis_service=analysis_service)

    first = run_once(report_date="2026-03-20", service=service)

    assert first["status"] == "awaiting_skill_decision"
    assert first["classification_input"].endswith("classification-input.json")
    assert first["skill_candidates"].endswith("skill-candidates.json")
    assert first["skill_merge_decisions"].endswith("skill-merge-decisions.json")
    assert first["stage_errors"] == []
    assert first["deep_analyzed_repos"] == 2
    assert first["cached_reused_repos"] == 0
    assert first["fallback_repos"] == 0
    assert first["skipped_due_to_budget"] == 0
    assert first["cleanup_warnings"] == 0

    decisions_path = service.artifact_service.skill_merge_decisions_path("2026-03-20")
    skill_candidates_payload = json.loads(Path(first["skill_candidates"]).read_text(encoding="utf-8"))
    decisions_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "report_date": "2026-03-20",
                "decisions": [
                    {
                        "candidate_id": skill_candidates_payload["candidates"][0]["candidate_id"],
                        "decision": "install",
                        "canonical_name": "Browser Bot Canonical",
                        "merge_target": "browser-bot-canonical",
                        "accepted": True,
                        "reason": "完整 skill 包，可直接安装。",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    second = run_once(report_date="2026-03-20", service=service)

    assert second["status"] == "completed"
    assert second["markdown_report"].endswith("2026-03-20.md")
    assert second["json_report"].endswith("2026-03-20.json")
    assert second["run_summary"].endswith("run-summary.json")
    assert second["stage_errors"] == []
    assert second["deep_analyzed_repos"] == 2
    assert second["cached_reused_repos"] == 0
    assert second["fallback_repos"] == 0
    assert second["skipped_due_to_budget"] == 0
    assert second["cleanup_warnings"] == 0
    assert second["capability_audit"].endswith("capability-audit.json")
    assert second["taxonomy_gap_candidates_report"].endswith("taxonomy-gap-candidates.json")
    assert second["skill_sync_report"].endswith("skill-sync-report.json")
    assert second["skill_sync_summary"]["candidate_count"] >= 0
    assert isinstance(second["skill_sync_actions"], list)
    assert "auto_promoted_capabilities" in second
    assert "risky_enhancement_candidates" in second
    assert "manual_attention_items" in second
    assert "taxonomy_gap_candidates" in second
    assert second["taxonomy_gap_candidates"] == []
    assert second["skill_merge_decisions"].endswith("skill-merge-decisions.json")


def test_runner_summary_includes_batch_counts(tmp_path) -> None:
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/alpha": make_layered_result("acme/alpha", repo_url="https://github.com/acme/alpha"),
            "acme/bravo": make_layered_result("acme/bravo", repo_url="https://github.com/acme/bravo"),
            "acme/charlie": make_layered_result("acme/charlie", repo_url="https://github.com/acme/charlie"),
        }
    )
    service = build_runner_service(
        tmp_path,
        collector=BudgetCollector(),
        repository_analysis_service=analysis_service,
        max_deep_analysis_repos=1,
    )

    first = run_once(report_date="2026-03-20", service=service)

    assert first["deep_analyzed_repos"] == 3
    assert first["cached_reused_repos"] == 0
    assert first["fallback_repos"] == 0
    assert first["skipped_due_to_budget"] == 0
    assert first["cleanup_warnings"] == 0


def test_runner_prepare_summary_mentions_auto_skill_decisions(tmp_path) -> None:
    package_root = tmp_path / "source" / "skills" / "agent-builder"
    package_root.mkdir(parents=True)
    package_root.joinpath("SKILL.md").write_text("# Agent Builder\n", encoding="utf-8")
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/codex-skills": make_layered_result(
                "acme/codex-skills",
                repo_url="https://github.com/acme/codex-skills",
                discovered_skill_packages=(
                    DiscoveredSkillPackage(
                        skill_name="agent-builder",
                        package_root=package_root,
                        relative_root="skills/agent-builder",
                        files=("SKILL.md",),
                    ),
                ),
            )
        }
    )
    service = build_runner_service(
        tmp_path,
        collector=MutableCollector(["acme/codex-skills"]),
        metadata_fetcher=StubMetadataFetcher(
            {
                "acme/codex-skills": RepositoryMetadataPayload(
                    readme="A collection of Codex skills.",
                    topics=("codex", "skills"),
                    pushed_at="2026-03-01T00:00:00Z",
                )
            }
        ),
        repository_analysis_service=analysis_service,
    )
    first = run_once(report_date="2026-03-20", service=service)

    assert first["status"] == "awaiting_skill_decision"
    assert "auto-generated skill-merge-decisions.json" in first["next_action"]


def test_runner_rebuilds_when_existing_artifacts_are_legacy_shallow(tmp_path) -> None:
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/browser-bot": make_layered_result("acme/browser-bot", repo_url="https://github.com/acme/browser-bot"),
            "acme/extractor": make_layered_result("acme/extractor", repo_url="https://github.com/acme/extractor"),
        }
    )
    service = build_runner_service(tmp_path, repository_analysis_service=analysis_service)
    report_date = "2026-03-20"
    input_path = service.artifact_service.classification_input_path(report_date)
    input_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "report_date": report_date,
                "taxonomy_path": "docs/capability-taxonomy.md",
                "expected_output_filename": "skill-merge-decisions.json",
                "items": [
                    {
                        "repo_full_name": "legacy/shallow-repo",
                        "repo_url": "https://github.com/legacy/shallow-repo",
                        "description": "Old shallow artifact with no deep-analysis evidence.",
                        "language": "Python",
                        "topics": [],
                        "periods": ["daily"],
                        "readme_excerpt": None,
                        "candidate_texts": ["legacy shallow repo"],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    decisions_path = service.artifact_service.skill_merge_decisions_path(report_date)
    decisions_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "report_date": report_date,
                "decisions": [
                    {
                        "candidate_id": "skillcand-legacy",
                        "decision": "discard",
                        "canonical_name": "legacy-shallow-repo",
                        "merge_target": None,
                        "accepted": False,
                        "reason": "旧版残留工件。",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = run_once(report_date=report_date, service=service)

    assert summary["status"] == "awaiting_skill_decision"
    assert summary["deep_analyzed_repos"] == 2
    assert summary["cached_reused_repos"] == 0
    assert summary["fallback_repos"] == 0
    assert summary["skipped_due_to_budget"] == 0
    assert not decisions_path.exists()
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    assert payload["items"][0]["analysis_depth"] == "layered"


def test_runner_reports_failed_prepare_when_ingest_fails(tmp_path, monkeypatch) -> None:
    service = build_runner_service(tmp_path)

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002, ARG001
        raise RuntimeError("ingest failed")

    monkeypatch.setattr(service.ingest_service, "ingest_trending_repos", boom)

    summary = run_once(report_date="2026-03-20", service=service)

    assert summary["status"] == "failed"
    assert summary["classification_input"] is None
    assert summary["next_action"] == "Inspect stage_errors and repair the run."
    assert "classification-output.json" not in summary["next_action"]


def test_runner_does_not_treat_legacy_classification_output_as_primary_finalize_contract(tmp_path) -> None:
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/browser-bot": make_layered_result("acme/browser-bot", repo_url="https://github.com/acme/browser-bot"),
            "acme/extractor": make_layered_result("acme/extractor", repo_url="https://github.com/acme/extractor"),
        }
    )
    service = build_runner_service(tmp_path, repository_analysis_service=analysis_service)

    first = run_once(report_date="2026-03-20", service=service)
    legacy_output_path = service.artifact_service.classification_output_path("2026-03-20")
    legacy_output_path.write_text(
        json.dumps(
            [
                {
                    "repo_full_name": "acme/browser-bot",
                    "capabilities": [
                        {
                            "capability_id": "browser_automation",
                            "confidence": 0.93,
                            "reason": "Legacy output should not finalize the main path.",
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

    second = run_once(report_date="2026-03-20", service=service)

    assert first["status"] == "awaiting_skill_decision"
    assert second["status"] == "awaiting_skill_decision"
    assert "skill-merge-decisions.json" in second["next_action"]
    assert "classification-output.json" not in second["next_action"]


def test_runner_does_not_finalize_empty_skill_decisions_when_candidates_exist(tmp_path) -> None:
    discovered_skill_packages = (
        DiscoveredSkillPackage(
            skill_name="browser-bot",
            package_root=tmp_path / "source" / "skills" / "browser-bot",
            relative_root="skills/browser-bot",
            files=("SKILL.md", "README.md"),
        ),
    )
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/browser-bot": make_layered_result(
                "acme/browser-bot",
                repo_url="https://github.com/acme/browser-bot",
                discovered_skill_packages=discovered_skill_packages,
            ),
            "acme/extractor": make_layered_result("acme/extractor", repo_url="https://github.com/acme/extractor"),
        }
    )
    service = build_runner_service(tmp_path, repository_analysis_service=analysis_service)

    first = run_once(report_date="2026-03-20", service=service)
    decisions_path = service.artifact_service.skill_merge_decisions_path("2026-03-20")
    decisions_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "report_date": "2026-03-20",
                "decisions": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    second = run_once(report_date="2026-03-20", service=service)

    assert first["status"] == "awaiting_skill_decision"
    assert second["status"] == "awaiting_skill_decision"
    assert second["skill_candidates"].endswith("skill-candidates.json")
    assert "skill-merge-decisions.json" in second["next_action"]


def test_runner_rebuilds_stale_auto_skill_decisions(tmp_path) -> None:
    package_root = tmp_path / "source" / "skills" / "agent-builder"
    package_root.mkdir(parents=True)
    package_root.joinpath("SKILL.md").write_text("# Agent Builder\n", encoding="utf-8")
    analysis_service = StubRepositoryAnalysisService(
        {
            "acme/codex-skills": make_layered_result(
                "acme/codex-skills",
                repo_url="https://github.com/acme/codex-skills",
                discovered_skill_packages=(
                    DiscoveredSkillPackage(
                        skill_name="agent-builder",
                        package_root=package_root,
                        relative_root="skills/agent-builder",
                        files=("SKILL.md",),
                    ),
                ),
            )
        }
    )
    service = build_runner_service(
        tmp_path,
        collector=MutableCollector(["acme/codex-skills"]),
        metadata_fetcher=StubMetadataFetcher(
            {
                "acme/codex-skills": RepositoryMetadataPayload(
                    readme="A collection of Codex skills.",
                    topics=("codex", "skills"),
                    pushed_at="2026-03-01T00:00:00Z",
                )
            }
        ),
        repository_analysis_service=analysis_service,
    )

    first = run_once(report_date="2026-03-20", service=service)
    decisions_path = service.artifact_service.skill_merge_decisions_path("2026-03-20")
    decisions_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "report_date": "2026-03-20",
                "decision_mode": "auto",
                "decisions": [
                    {
                        "candidate_id": "stale",
                        "decision": "install",
                        "canonical_name": "Stale",
                        "merge_target": "stale",
                        "accepted": True,
                        "reason": "old policy",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    second = run_once(report_date="2026-03-20", service=service)
    rebuilt_payload = json.loads(decisions_path.read_text(encoding="utf-8"))

    assert first["status"] == "awaiting_skill_decision"
    assert second["status"] == "awaiting_skill_decision"
    assert rebuilt_payload["auto_policy_version"] == 3
    assert rebuilt_payload["decisions"][0]["candidate_id"] != "stale"


def test_runner_workspace_scopes_repository_analysis_temp_root(tmp_path, monkeypatch) -> None:
    captured = {}

    class FakeOrchestrationService:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs
            self.artifact_service = kwargs["artifact_service"]

        def build_classification_input(self, report_date):  # noqa: ANN001
            return SimpleNamespace(
                report_date=report_date,
                repos_ingested=0,
                repository_items=0,
                deep_analyzed_repos=0,
                cached_reused_repos=0,
                fallback_repos=0,
                skipped_due_to_budget=0,
                cleanup_warnings=0,
                classification_input_path=self.artifact_service.classification_input_path(report_date.isoformat()),
                stage_errors=[],
            )

        def ingest_skill_merge_decisions(self, report_date, path):  # noqa: ANN001
            raise AssertionError("unexpected finalize path")

    monkeypatch.setattr("haotian.runner.OrchestrationService", FakeOrchestrationService)

    workspace = tmp_path / "workspace"
    run_once(report_date="2026-03-20", workspace=workspace)

    assert captured["kwargs"]["repository_tmp_dir"] == workspace / "data" / "tmp" / "repos"
