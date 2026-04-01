from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from haotian.config import PROJECT_ROOT
from haotian.config import Settings
from haotian.config import _default_codex_managed_skill_root
from haotian.config import get_settings


def test_settings_default_to_repo_database_path(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings.from_env()

    assert settings.database_url == "sqlite:///./data/haotian.db"


def test_settings_default_to_local_run_artifact_paths(monkeypatch) -> None:
    monkeypatch.delenv("REPORT_DIR", raising=False)
    monkeypatch.delenv("RUN_DIR", raising=False)

    settings = Settings.from_env()

    assert settings.report_dir == Path("data/reports")
    assert settings.run_dir == Path("data/runs")


def test_settings_support_semicolon_separated_codex_skill_roots_and_audit_script(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CODEX_SKILL_ROOTS", f" {tmp_path / 'skills-a'} ; {tmp_path / 'skills-b'} ")
    monkeypatch.setenv("CODEX_MANAGED_SKILL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setenv("SKILL_AUDIT_SCRIPT", str(tmp_path / "audit_skill.py"))

    settings = Settings.from_env()

    assert list(settings.codex_skill_roots) == [tmp_path / "skills-a", tmp_path / "skills-b"]
    assert settings.codex_managed_skill_root == tmp_path / "managed"
    assert settings.skill_audit_script == tmp_path / "audit_skill.py"


def test_get_settings_normalizes_codex_skill_paths(monkeypatch, tmp_path) -> None:
    first_cwd = tmp_path / "first-cwd"
    first_cwd.mkdir()
    monkeypatch.chdir(first_cwd)
    monkeypatch.setenv("CODEX_SKILL_ROOTS", "skills-a;skills-b")
    monkeypatch.setenv("CODEX_MANAGED_SKILL_ROOT", "managed")
    monkeypatch.setenv("SKILL_AUDIT_SCRIPT", "scripts/audit_skill.py")
    get_settings.cache_clear()
    try:
        settings = get_settings()

        assert settings.codex_skill_roots == (
            (PROJECT_ROOT / "skills-a").resolve(),
            (PROJECT_ROOT / "skills-b").resolve(),
        )
        assert settings.codex_managed_skill_root == (PROJECT_ROOT / "managed").resolve()
        assert settings.skill_audit_script == (PROJECT_ROOT / "scripts/audit_skill.py").resolve()
    finally:
        get_settings.cache_clear()


def test_get_settings_autodiscovers_skill_sync_defaults(monkeypatch, tmp_path) -> None:
    managed_root = tmp_path / "managed"
    skill_root = tmp_path / "skills"
    audit_script = tmp_path / "audit_skill.py"
    skill_root.mkdir()
    audit_script.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.delenv("CODEX_SKILL_ROOTS", raising=False)
    monkeypatch.delenv("CODEX_MANAGED_SKILL_ROOT", raising=False)
    monkeypatch.delenv("SKILL_AUDIT_SCRIPT", raising=False)
    monkeypatch.setattr("haotian.config._default_codex_skill_roots", lambda: (skill_root.resolve(),))
    monkeypatch.setattr("haotian.config._default_codex_managed_skill_root", lambda: managed_root)
    monkeypatch.setattr("haotian.config._default_skill_audit_script", lambda: audit_script.resolve())
    get_settings.cache_clear()
    try:
        settings = get_settings()

        assert settings.codex_skill_roots == (skill_root.resolve(),)
        assert settings.codex_managed_skill_root == managed_root.resolve()
        assert settings.skill_audit_script == audit_script.resolve()
    finally:
        get_settings.cache_clear()


def test_default_codex_managed_skill_root_uses_e_drive() -> None:
    assert _default_codex_managed_skill_root() == Path("E:/CodexHome/skills/haotian-managed")


def test_settings_include_repo_analysis_defaults(monkeypatch) -> None:
    monkeypatch.delenv("TMP_REPO_DIR", raising=False)
    monkeypatch.delenv("MAX_REPO_PROBE_FILES", raising=False)
    monkeypatch.delenv("MAX_REPO_PROBE_FILE_BYTES", raising=False)
    monkeypatch.delenv("MAX_EVIDENCE_SNIPPETS", raising=False)
    monkeypatch.delenv("MAX_DEEP_ANALYSIS_REPOS", raising=False)

    settings = Settings.from_env()

    assert settings.tmp_repo_dir == Path("data/tmp/repos")
    assert settings.max_repo_probe_files == 16
    assert settings.max_repo_probe_file_bytes == 24000
    assert settings.max_evidence_snippets == 6
    assert settings.max_deep_analysis_repos == 12


@pytest.mark.parametrize(
    ("env_var", "value"),
    [
        ("MAX_REPO_PROBE_FILES", "0"),
        ("MAX_REPO_PROBE_FILE_BYTES", "-1"),
        ("MAX_EVIDENCE_SNIPPETS", "0"),
        ("MAX_DEEP_ANALYSIS_REPOS", "0"),
    ],
)
def test_repo_analysis_settings_must_be_positive(monkeypatch, env_var, value) -> None:
    monkeypatch.setenv(env_var, value)

    with pytest.raises(ValidationError):
        Settings.from_env()


def test_settings_accepts_run_dir_override(monkeypatch) -> None:
    monkeypatch.setenv("RUN_DIR", "./custom-runs")

    settings = Settings.from_env()

    assert settings.run_dir == Path("custom-runs")


def test_settings_accepts_report_dir_override(monkeypatch) -> None:
    monkeypatch.setenv("REPORT_DIR", "./custom-reports")

    settings = Settings.from_env()

    assert settings.report_dir == Path("custom-reports")


def test_get_settings_normalizes_relative_artifact_paths_against_repo_root(monkeypatch, tmp_path) -> None:
    first_cwd = tmp_path / "first-cwd"
    first_cwd.mkdir()
    monkeypatch.chdir(first_cwd)
    monkeypatch.setenv("TMP_REPO_DIR", "tmp-repos")
    monkeypatch.setenv("REPORT_DIR", "reports")
    monkeypatch.setenv("RUN_DIR", "runs")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/custom.db")
    get_settings.cache_clear()
    try:
        settings = get_settings()

        assert settings.database_url == f"sqlite:///{(PROJECT_ROOT / 'data' / 'custom.db').resolve().as_posix()}"
        assert settings.tmp_repo_dir == (PROJECT_ROOT / "tmp-repos").resolve()
        assert settings.report_dir == (PROJECT_ROOT / "reports").resolve()
        assert settings.run_dir == (PROJECT_ROOT / "runs").resolve()
    finally:
        get_settings.cache_clear()


def test_docs_mention_skill_sync_report_and_skill_sync_configuration() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    ops_doc = (PROJECT_ROOT / "docs/ops.md").read_text(encoding="utf-8")
    architecture_doc = (PROJECT_ROOT / "docs/architecture.md").read_text(encoding="utf-8")

    assert "skill-sync-report.json" in readme
    assert "CODEX_SKILL_ROOTS" in env_example
    assert "CODEX_MANAGED_SKILL_ROOT" in env_example
    assert "SKILL_AUDIT_SCRIPT" in env_example
    assert "如果要真正安装新的 Haotian-managed skill，至少需要：" in ops_doc
    assert "- `CODEX_MANAGED_SKILL_ROOT`" in ops_doc
    assert "- `SKILL_AUDIT_SCRIPT`" in ops_doc
    assert (
        "其中 `CODEX_SKILL_ROOTS` 可选；它主要用于扫描和对齐当前机器上已经安装的 skill，不配置时仍然可以把新的审计通过 skill 安装到 `CODEX_MANAGED_SKILL_ROOT`。"
        in ops_doc
    )
    assert "capability-audit.json" in architecture_doc
    assert "taxonomy-gap-candidates.json" in architecture_doc
