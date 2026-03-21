from __future__ import annotations

from haotian.config import Settings


def test_settings_accepts_uppercase_openaiapi_alias(monkeypatch) -> None:
    monkeypatch.setenv("OPENAIAPI", "test-secret")

    settings = Settings.from_env()

    assert settings.openai_api_key == "test-secret"
