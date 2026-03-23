from __future__ import annotations

import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "start_haotian",
    Path(__file__).resolve().parent.parent / "start_haotian.py",
)
assert spec is not None and spec.loader is not None
start_haotian = importlib.util.module_from_spec(spec)
spec.loader.exec_module(start_haotian)


def test_launcher_runs_core_pipeline(monkeypatch, capsys) -> None:
    called: dict[str, object] = {}

    def fake_run_once(*, report_date: str | None = None) -> dict[str, object]:
        called["report_date"] = report_date
        return {
            "status": "completed",
            "report_date": "2026-03-23",
            "markdown_report": "data/reports/2026-03-23.md",
            "stage_errors": [],
        }

    monkeypatch.setattr(start_haotian, "_load_runner", lambda: fake_run_once)
    monkeypatch.setattr(start_haotian.sys, "argv", ["start_haotian.py"])
    start_haotian.main()

    captured = json.loads(capsys.readouterr().out)
    assert called == {"report_date": None}
    assert captured["markdown_report"] == "data/reports/2026-03-23.md"


def test_launcher_reports_missing_dependency(monkeypatch) -> None:
    message = start_haotian._missing_dependency_message("pydantic")

    assert "pydantic" in message
    assert "python -m pip install -e ." in message
