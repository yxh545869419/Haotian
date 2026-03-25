from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from haotian.config import Settings
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


def test_settings_support_codex_skill_roots_and_audit_script(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CODEX_SKILL_ROOTS", f"{tmp_path / 'skills-a'};{tmp_path / 'skills-b'}")
    monkeypatch.setenv("CODEX_MANAGED_SKILL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setenv("SKILL_AUDIT_SCRIPT", str(tmp_path / "audit_skill.py"))

    settings = Settings.from_env()

    assert list(settings.codex_skill_roots) == [tmp_path / "skills-a", tmp_path / "skills-b"]
    assert settings.codex_managed_skill_root == tmp_path / "managed"
    assert settings.skill_audit_script == tmp_path / "audit_skill.py"


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


def test_get_settings_normalizes_relative_artifact_paths_against_load_cwd(monkeypatch, tmp_path) -> None:
    first_cwd = tmp_path / "first-cwd"
    first_cwd.mkdir()
    monkeypatch.chdir(first_cwd)
    monkeypatch.setenv("TMP_REPO_DIR", "tmp-repos")
    monkeypatch.setenv("REPORT_DIR", "reports")
    monkeypatch.setenv("RUN_DIR", "runs")
    get_settings.cache_clear()
    try:
        settings = get_settings()

        assert settings.tmp_repo_dir == (first_cwd / "tmp-repos").resolve()
        assert settings.report_dir == (first_cwd / "reports").resolve()
        assert settings.run_dir == (first_cwd / "runs").resolve()
    finally:
        get_settings.cache_clear()
