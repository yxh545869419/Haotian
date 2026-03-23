from __future__ import annotations

from pathlib import Path

from haotian.config import Settings


def test_settings_default_to_local_run_artifact_paths(monkeypatch) -> None:
    monkeypatch.delenv("REPORT_DIR", raising=False)
    monkeypatch.delenv("RUN_DIR", raising=False)

    settings = Settings.from_env()

    assert settings.report_dir == Path("data/reports")
    assert settings.run_dir == Path("data/runs")


def test_settings_accepts_run_dir_override(monkeypatch) -> None:
    monkeypatch.setenv("RUN_DIR", "./custom-runs")

    settings = Settings.from_env()

    assert settings.run_dir == Path("custom-runs")


def test_settings_accepts_report_dir_override(monkeypatch) -> None:
    monkeypatch.setenv("REPORT_DIR", "./custom-reports")

    settings = Settings.from_env()

    assert settings.report_dir == Path("custom-reports")
