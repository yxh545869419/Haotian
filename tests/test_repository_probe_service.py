from __future__ import annotations

import os
import shutil
from pathlib import Path
import subprocess

import pytest

from haotian.services.repository_probe_service import EvidenceSnippet
from haotian.services.repository_probe_service import RepositoryProbeService


FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures" / "repos"


def copy_fixture_repo(name: str, tmp_path: Path) -> Path:
    source = FIXTURES_ROOT / name
    target = tmp_path / name
    shutil.copytree(source, target)
    return target


def write_repo_file(root: Path, relative_path: str, content: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_probe_prioritizes_full_skill_path_matrix(tmp_path) -> None:
    repo = tmp_path / "repo"
    write_repo_file(repo, "SKILL.md", "# Root skill")
    write_repo_file(repo, "AGENTS.md", "# Root agents")
    write_repo_file(repo, "codex.md", "# Root codex")
    write_repo_file(repo, "skills/app-store-optimization/SKILL.md", "# Nested skill")
    write_repo_file(repo, "skills/app-store-optimization/AGENTS.md", "# Nested agents")
    write_repo_file(repo, "skills/app-store-optimization/codex.md", "# Nested codex")
    write_repo_file(repo, "agents/planner.md", "# Agent guide")
    write_repo_file(repo, "commands/refresh.md", "# Command guide")
    write_repo_file(repo, "references/glossary.md", "# Reference guide")
    write_repo_file(repo, "scripts/sync.py", "print('sync')\n")

    result = RepositoryProbeService(max_files=12, max_file_bytes=256).probe(repo)

    assert "SKILL.md" in result.matched_files
    assert "AGENTS.md" in result.matched_files
    assert "codex.md" in result.matched_files
    assert "skills/app-store-optimization/SKILL.md" in result.matched_files
    assert "skills/app-store-optimization/AGENTS.md" in result.matched_files
    assert "skills/app-store-optimization/codex.md" in result.matched_files
    assert "agents/planner.md" in result.matched_files
    assert "commands/refresh.md" in result.matched_files
    assert "references/glossary.md" in result.matched_files
    assert "scripts/sync.py" in result.matched_files
    assert "SKILL.md" in result.matched_keywords
    assert "AGENTS.md" in result.matched_keywords
    assert "codex.md" in result.matched_keywords
    assert "skills/**/*.md" in result.matched_keywords
    assert "agents/**/*.md" in result.matched_keywords
    assert "commands/**/*.md" in result.matched_keywords
    assert "references/**/*.md" in result.matched_keywords
    assert "scripts/**/*.py" in result.matched_keywords
    assert "codex-skill-package" in result.architecture_signals
    assert "skill-ecosystem" in result.architecture_signals
    assert "plugin-ecosystem" in result.architecture_signals


def test_probe_preserves_basename_signals_inside_skill_directories(tmp_path) -> None:
    repo = tmp_path / "repo"
    write_repo_file(repo, "skills/app-store-optimization/SKILL.md", "# Nested skill")
    write_repo_file(repo, "skills/app-store-optimization/main.py", "def main() -> None:\n    pass\n")
    write_repo_file(repo, "skills/app-store-optimization/workflow.py", "def run_workflow() -> None:\n    pass\n")
    write_repo_file(repo, "skills/app-store-optimization/app.py", "print('skill package')\n")
    write_repo_file(repo, "skills/app-store-optimization/scripts/sync.py", "print('sync')\n")

    result = RepositoryProbeService(max_files=8, max_file_bytes=256).probe(repo)

    assert "main*" in result.matched_keywords
    assert "workflow*" in result.matched_keywords
    assert "app*" in result.matched_keywords
    assert "scripts/**/*.py" in result.matched_keywords
    assert "entrypoint-driven" in result.architecture_signals
    assert "workflow-orchestration" in result.architecture_signals
    assert "plugin-ecosystem" in result.architecture_signals


def test_probe_does_not_treat_skill_package_directory_name_as_entrypoint(tmp_path) -> None:
    repo = tmp_path / "repo"
    write_repo_file(repo, "skills/app-store-optimization/SKILL.md", "# Nested skill")

    result = RepositoryProbeService(max_files=8, max_file_bytes=256).probe(repo)

    assert "app*" not in result.matched_keywords
    assert "entrypoint-driven" not in result.architecture_signals


def test_probe_does_not_promote_root_agent_docs_to_skill_package_without_manifest(tmp_path) -> None:
    repo = tmp_path / "repo"
    write_repo_file(repo, "AGENTS.md", "# Root agents")
    write_repo_file(repo, "codex.md", "# Root codex")
    write_repo_file(repo, "main.py", "def main() -> None:\n    pass\n")
    write_repo_file(repo, "workflow.py", "def run_workflow() -> None:\n    pass\n")

    result = RepositoryProbeService(max_files=2, max_file_bytes=256).probe(repo)

    assert result.matched_files == ("main.py", "workflow.py")
    assert "AGENTS.md" not in result.matched_files
    assert "codex.md" not in result.matched_files
    assert "codex-skill-package" not in result.architecture_signals
    assert "skill-ecosystem" not in result.architecture_signals


def test_probe_ignores_windows_junction_skill_evidence(tmp_path) -> None:
    if os.name != "nt" or not hasattr(Path("x"), "is_junction"):
        pytest.skip("Windows junctions are not available")

    repo = tmp_path / "repo"
    write_repo_file(repo, "main.py", "def main() -> None:\n    pass\n")

    external_root = tmp_path / "external-skill"
    write_repo_file(external_root, "SKILL.md", "# External skill")
    write_repo_file(external_root, "AGENTS.md", "# External agents")
    write_repo_file(external_root, "scripts/sync.py", "print('external')\n")

    junction_path = repo / "skills" / "external"
    junction_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction_path), str(external_root)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not junction_path.is_junction():
        pytest.skip("Windows junction creation is not supported in this environment")

    probe = RepositoryProbeService(max_files=10, max_file_bytes=256).probe(repo)

    assert probe.matched_files == ("main.py",)
    assert "entrypoint-driven" in probe.architecture_signals
    assert "codex-skill-package" not in probe.architecture_signals
    assert "skill-ecosystem" not in probe.architecture_signals
    assert "plugin-ecosystem" not in probe.architecture_signals


def test_probe_ignores_root_alias_files_in_first_pass(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    root_skill = write_repo_file(repo, "SKILL.md", "# External-looking root skill")
    write_repo_file(repo, "main.py", "def main() -> None:\n    pass\n")

    for target in (
        "haotian.services.repository_probe_service.is_alias_path",
        "haotian.services.path_alias_guard.is_alias_path",
    ):
        monkeypatch.setattr(target, lambda path: path == root_skill)

    probe = RepositoryProbeService(max_files=10, max_file_bytes=256).probe(repo)

    assert probe.matched_files == ("main.py",)
    assert "entrypoint-driven" in probe.architecture_signals
    assert "codex-skill-package" not in probe.architecture_signals
    assert "skill-ecosystem" not in probe.architecture_signals


def test_probe_prioritizes_skill_and_markdown_files(tmp_path) -> None:
    repo = copy_fixture_repo("skill-heavy", tmp_path)

    result = RepositoryProbeService(max_files=8, max_file_bytes=256).probe(repo)

    assert result.analysis_depth == "layered"
    assert result.root_files == ("SKILL.md",)
    assert result.matched_files == (
        "SKILL.md",
        "docs/guide.md",
        "agents/browser/notes.md",
        "skills/browser/SKILL.md",
        "skills/browser/skill_runner.py",
        "prompts/system/agent.md",
    )
    assert "skill*" in result.matched_keywords
    assert "*.md" in result.matched_keywords
    assert "documentation-first" in result.architecture_signals


def test_probe_extracts_representative_source_files_only(tmp_path) -> None:
    repo = copy_fixture_repo("agent-heavy", tmp_path)

    result = RepositoryProbeService(max_files=4, max_file_bytes=256).probe(repo)

    assert result.root_files == ("pyproject.toml",)
    assert result.matched_files == ("pyproject.toml", "src/agent/main.py", "src/agent/workflow.py")
    assert "entrypoint-driven" in result.architecture_signals
    assert "workflow-orchestration" in result.architecture_signals
    assert "main*" in result.matched_keywords
    assert "workflow*" in result.matched_keywords


def test_probe_records_file_budget_limits(tmp_path) -> None:
    repo = copy_fixture_repo("agent-heavy", tmp_path)

    result = RepositoryProbeService(max_files=2, max_file_bytes=256).probe(repo)

    assert len(result.matched_files) == 2
    assert any("max_files" in limit for limit in result.analysis_limits)


def test_probe_truncates_evidence_snippets(tmp_path) -> None:
    repo = copy_fixture_repo("docs-heavy", tmp_path)

    result = RepositoryProbeService(max_files=4, max_file_bytes=20).probe(repo)

    assert result.evidence_snippets
    assert result.evidence_snippets[0] == EvidenceSnippet(
        path=result.evidence_snippets[0].path,
        excerpt=result.evidence_snippets[0].excerpt,
        why_it_matters=result.evidence_snippets[0].why_it_matters,
    )
    assert result.evidence_snippets[0].excerpt.endswith("...")
    assert any("truncated" in limit for limit in result.analysis_limits)


def test_probe_handles_repository_with_no_deep_signals(tmp_path) -> None:
    repo = copy_fixture_repo("no-signal", tmp_path)

    result = RepositoryProbeService(max_files=4, max_file_bytes=256).probe(repo)

    assert result.analysis_depth == "layered"
    assert result.root_files == ("NOTICE.txt",)
    assert result.matched_files == ()
    assert result.matched_keywords == ()
    assert result.architecture_signals == ()
    assert "no deep signals" in result.probe_summary.lower()


def test_probe_marks_missing_root_as_fallback(tmp_path) -> None:
    missing_repo = tmp_path / "missing-repo"

    result = RepositoryProbeService(max_files=4, max_file_bytes=256).probe(missing_repo)

    assert result.analysis_depth == "fallback"
    assert result.fallback_used is True
    assert result.root_files == ()
    assert result.matched_files == ()


def test_probe_reads_only_bounded_bytes_from_disk(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    target_file = write_repo_file(repo, "docs/methodology.md", "0123456789" * 20)
    read_sizes: list[int] = []

    original_open = Path.open

    def open_spy(self, mode="r", *args, **kwargs):  # noqa: A002
        handle = original_open(self, mode, *args, **kwargs)
        if self.resolve(strict=False) != target_file.resolve():
            return handle

        class ReadSpy:
            def __init__(self, wrapped) -> None:
                self._wrapped = wrapped

            def read(self, size=-1):
                read_sizes.append(size)
                assert size == 11
                return self._wrapped.read(size)

            def __getattr__(self, name):
                return getattr(self._wrapped, name)

            def __enter__(self):
                self._wrapped.__enter__()
                return self

            def __exit__(self, exc_type, exc, tb):
                return self._wrapped.__exit__(exc_type, exc, tb)

        return ReadSpy(handle)

    monkeypatch.setattr(Path, "open", open_spy)

    result = RepositoryProbeService(max_files=4, max_file_bytes=10).probe(repo)

    assert read_sizes == [11]
    assert result.evidence_snippets[0].excerpt.endswith("...")


def test_probe_keeps_code_signals_when_docs_exceed_budget(tmp_path) -> None:
    repo = tmp_path / "repo"
    write_repo_file(repo, "README.md", "overview")
    for index in range(5):
        write_repo_file(repo, f"docs/doc-{index}.md", f"doc {index}")
    write_repo_file(repo, "main.py", "def main() -> None:\n    pass\n")
    write_repo_file(repo, "workflow.py", "def run_workflow() -> None:\n    pass\n")

    result = RepositoryProbeService(max_files=4, max_file_bytes=256).probe(repo)

    assert "main.py" in result.matched_files
    assert "workflow.py" in result.matched_files
    assert any(path.startswith("docs/") for path in result.matched_files)
    assert "entrypoint-driven" in result.architecture_signals
    assert "workflow-orchestration" in result.architecture_signals


def test_probe_keeps_root_config_and_code_ahead_of_root_markdown_budget_pressure(tmp_path) -> None:
    repo = tmp_path / "repo"
    write_repo_file(repo, "README.md", "overview")
    for index in range(6):
        write_repo_file(repo, f"doc-{index}.md", f"root doc {index}")
    write_repo_file(repo, "pyproject.toml", "[project]\nname = \"demo\"\n")
    write_repo_file(repo, "main.py", "def main() -> None:\n    pass\n")
    write_repo_file(repo, "workflow.py", "def run_workflow() -> None:\n    pass\n")

    result = RepositoryProbeService(max_files=4, max_file_bytes=256).probe(repo)

    assert "README.md" in result.matched_files
    assert "pyproject.toml" in result.matched_files
    assert "main.py" in result.matched_files
    assert "workflow.py" in result.matched_files
    assert not any(path.startswith("doc-") for path in result.matched_files)
    assert "entrypoint-driven" in result.architecture_signals
    assert "workflow-orchestration" in result.architecture_signals


def test_probe_matches_mixed_case_directories_case_insensitively(tmp_path) -> None:
    repo = tmp_path / "repo"
    write_repo_file(repo, "Docs/guide.md", "Mixed-case docs")
    write_repo_file(repo, "Agents/browser/notes.md", "Mixed-case agents docs")
    write_repo_file(repo, "Skills/browser/SKILL.md", "Mixed-case skill docs")
    write_repo_file(repo, "Prompts/system/guide.md", "Mixed-case prompts docs")

    result = RepositoryProbeService(max_files=10, max_file_bytes=256).probe(repo)

    assert "Docs/guide.md" in result.matched_files
    assert "Agents/browser/notes.md" in result.matched_files
    assert "Skills/browser/SKILL.md" in result.matched_files
    assert "Prompts/system/guide.md" in result.matched_files
    assert "docs/**/*.md" in result.matched_keywords
    assert "agents/**/*.md" in result.matched_keywords
    assert "skills/**/*.md" in result.matched_keywords
    assert "prompts/**/*.md" in result.matched_keywords
    assert "documentation-first" in result.architecture_signals
    assert "skill-centric" in result.architecture_signals
    assert "agent-centric" in result.architecture_signals
