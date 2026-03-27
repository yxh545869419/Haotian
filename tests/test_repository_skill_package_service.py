from __future__ import annotations

import os
import shutil
from pathlib import Path
import subprocess

import pytest

from haotian.services.repository_analysis_service import RepositoryAnalysisResult
from haotian.services.repository_analysis_service import RepositoryAnalysisService
from haotian.services.repository_skill_package_service import DiscoveredSkillPackage
from haotian.services.repository_skill_package_service import RepositorySkillPackageService
from haotian.services.repository_workspace_service import ClonedWorkspace


def write_repo_file(root: Path, relative_path: str, content: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_analyze_repository_includes_discovered_skill_packages(tmp_path, monkeypatch) -> None:
    source_repo = tmp_path / "source"
    write_repo_file(source_repo, "SKILL.md", "# Root skill")
    write_repo_file(source_repo, "skills/browser/SKILL.md", "# Browser skill")
    write_repo_file(source_repo, "skills/browser/skill_runner.py", "print('browser')\n")

    service = RepositoryAnalysisService(run_label="2026-03-25", base_dir=tmp_path / "tmp-repos")

    def clone_repo(self, *, repo_full_name, repo_url):  # noqa: ANN001, ANN002
        del repo_full_name, repo_url
        target = self.workspace_path("acme/browser-bot")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_repo, target)
        return ClonedWorkspace(repo_full_name="acme/browser-bot", path=target)

    monkeypatch.setattr("haotian.services.repository_workspace_service.RepositoryWorkspaceService.clone_repo", clone_repo)

    result = service.analyze_repository(
        repo_full_name="acme/browser-bot",
        repo_url=str(source_repo),
    )

    assert result.analysis_depth == "layered"
    assert tuple(package.relative_root for package in result.discovered_skill_packages) == (
        ".",
        "skills/browser",
    )
    assert result.discovered_skill_packages[0].skill_name == "browser-bot"
    assert result.discovered_skill_packages[0].files == ("SKILL.md",)
    assert result.discovered_skill_packages[1].skill_name == "browser"
    assert result.discovered_skill_packages[1].files == ("SKILL.md", "skill_runner.py")


def test_discover_returns_root_and_nested_skill_packages_in_sorted_order(tmp_path) -> None:
    repo = tmp_path / "repo"
    write_repo_file(repo, "SKILL.md", "# Root skill")
    write_repo_file(repo, "AGENTS.md", "# Root agents")
    write_repo_file(repo, "codex.md", "# Root codex")
    write_repo_file(repo, "skills/automation/SKILL.md", "# Automation skill")
    write_repo_file(repo, "skills/automation/skill_runner.py", "print('automation')\n")
    write_repo_file(repo, "skills/browser/SKILL.md", "# Browser skill")
    write_repo_file(repo, "skills/browser/skill_runner.py", "print('browser')\n")

    result = RepositorySkillPackageService().discover(repo)

    assert result == (
        DiscoveredSkillPackage(
            skill_name="repo",
            package_root=repo,
            relative_root=".",
            files=("AGENTS.md", "SKILL.md", "codex.md"),
        ),
        DiscoveredSkillPackage(
            skill_name="automation",
            package_root=repo / "skills" / "automation",
            relative_root="skills/automation",
            files=("SKILL.md", "skill_runner.py"),
        ),
        DiscoveredSkillPackage(
            skill_name="browser",
            package_root=repo / "skills" / "browser",
            relative_root="skills/browser",
            files=("SKILL.md", "skill_runner.py"),
        ),
    )


def test_discover_ignores_supporting_docs_without_skill_manifest(tmp_path) -> None:
    repo = tmp_path / "repo"
    write_repo_file(repo, "AGENTS.md", "# Root agents")
    write_repo_file(repo, "codex.md", "# Root codex")
    write_repo_file(repo, "skills/browser/AGENTS.md", "# Browser agents")
    write_repo_file(repo, "skills/browser/codex.md", "# Browser codex")

    result = RepositorySkillPackageService().discover(repo)

    assert result == ()


def test_discover_ignores_windows_junction_skill_packages(tmp_path) -> None:
    if os.name != "nt" or not hasattr(Path("x"), "is_junction"):
        pytest.skip("Windows junctions are not available")

    repo = tmp_path / "repo"
    write_repo_file(repo, "skills/local/SKILL.md", "# Local skill")
    write_repo_file(repo, "skills/local/skill_runner.py", "print('local')\n")

    external_root = tmp_path / "external-skill"
    write_repo_file(external_root, "SKILL.md", "# External skill")
    write_repo_file(external_root, "skill_runner.py", "print('external')\n")

    junction_path = repo / "skills" / "external"
    junction_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction_path), str(external_root)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not junction_path.is_junction():
        pytest.skip("Windows junction creation is not supported in this environment")

    discovered = RepositorySkillPackageService().discover(repo)

    assert tuple(package.relative_root for package in discovered) == ("skills/local",)
    assert all(package.skill_name != "external" for package in discovered)


def test_analysis_result_exposes_discovered_skill_packages_in_classification_fields(tmp_path) -> None:
    repo = tmp_path / "repo"
    packages = (
        DiscoveredSkillPackage(
            skill_name="repo",
            package_root=repo,
            relative_root=".",
            files=("SKILL.md",),
        ),
        DiscoveredSkillPackage(
            skill_name="browser",
            package_root=repo / "skills" / "browser",
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

    payload = result.to_classification_input_fields()

    assert payload["discovered_skill_packages"] == [
        {
            "skill_name": "repo",
            "relative_root": ".",
            "files": ["SKILL.md"],
        },
        {
            "skill_name": "browser",
            "relative_root": "skills/browser",
            "files": ["SKILL.md", "skill_runner.py"],
        },
    ]
    assert "package_root" not in payload["discovered_skill_packages"][0]
    assert "package_root" not in payload["discovered_skill_packages"][1]
