from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "start_haotian",
    Path(__file__).resolve().parent.parent / "start_haotian.py",
)
assert spec is not None and spec.loader is not None
start_haotian = importlib.util.module_from_spec(spec)
spec.loader.exec_module(start_haotian)


def test_launcher_dispatches_web_mode(monkeypatch) -> None:
    called: dict[str, object] = {}

    def fake_web(*, host: str, port: int) -> None:
        called['mode'] = 'web'
        called['host'] = host
        called['port'] = port

    monkeypatch.setattr(
        start_haotian,
        "_load_commands",
        lambda: (lambda: (_ for _ in ()).throw(AssertionError('cli should not run')), fake_web),
    )
    monkeypatch.setattr(start_haotian.sys, 'argv', ['start_haotian.py', '--mode', 'web', '--host', '0.0.0.0', '--port', '9631'])

    start_haotian.main()

    assert called == {'mode': 'web', 'host': '0.0.0.0', 'port': 9631}


def test_launcher_reports_missing_dependency(monkeypatch) -> None:
    message = start_haotian._missing_dependency_message("pydantic")

    assert "pydantic" in message
    assert "python -m pip install -e ." in message
