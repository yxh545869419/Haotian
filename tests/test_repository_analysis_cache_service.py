from __future__ import annotations

from haotian.db.schema import initialize_schema
from haotian.services.repository_analysis_cache_service import RepositoryAnalysisCacheService
from haotian.services.repository_analysis_service import RepositoryAnalysisResult
from haotian.services.repository_skill_package_service import DiscoveredSkillPackage


def test_repository_analysis_cache_round_trips_discovered_skill_packages(tmp_path) -> None:
    cache_service = RepositoryAnalysisCacheService(database_url=f"sqlite:///{tmp_path / 'app.db'}")
    initialize_schema(f"sqlite:///{tmp_path / 'app.db'}")
    packages = (
        DiscoveredSkillPackage(
            skill_name="browser-bot",
            package_root=tmp_path / "clone" / "repo",
            relative_root=".",
            files=("SKILL.md",),
        ),
        DiscoveredSkillPackage(
            skill_name="browser",
            package_root=tmp_path / "clone" / "repo" / "skills" / "browser",
            relative_root="skills/browser",
            files=("SKILL.md", "skill_runner.py"),
        ),
    )
    result = RepositoryAnalysisResult(
        repo_full_name="acme/browser-bot",
        repo_url="https://github.com/acme/browser-bot",
        analysis_depth="layered",
        clone_strategy="shallow-clone",
        clone_started=True,
        analysis_completed=True,
        cleanup_attempted=True,
        cleanup_required=True,
        cleanup_completed=True,
        fallback_used=False,
        root_files=("SKILL.md",),
        matched_files=("SKILL.md", "skills/browser/SKILL.md"),
        matched_keywords=("SKILL.md", "skills/**/*.md"),
        architecture_signals=("codex-skill-package",),
        probe_summary="Layered analysis complete.",
        evidence_snippets=(),
        analysis_limits=(),
        discovered_skill_packages=packages,
    )

    cache_service.upsert(
        result=result,
        source_pushed_at="2026-03-01T00:00:00Z",
        analyzed_at="2026-03-25T00:00:00Z",
    )

    cached = cache_service.load("acme/browser-bot")
    assert cached is not None

    reused = cached.to_reused_result(repo_url="https://github.com/acme/browser-bot")
    payload = reused.to_classification_input_fields()

    assert tuple(package.relative_root for package in reused.discovered_skill_packages) == (
        ".",
        "skills/browser",
    )
    assert payload["discovered_skill_packages"] == [
            {
                "skill_name": "browser-bot",
                "relative_root": ".",
                "files": ["SKILL.md"],
                "source_package_root": str(tmp_path / "clone" / "repo"),
                "description": "",
            },
            {
                "skill_name": "browser",
                "relative_root": "skills/browser",
                "files": ["SKILL.md", "skill_runner.py"],
                "source_package_root": str(tmp_path / "clone" / "repo" / "skills" / "browser"),
                "description": "",
            },
        ]
