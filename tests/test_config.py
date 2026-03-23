from __future__ import annotations

from haotian.config import Settings


def test_settings_accepts_standard_openai_api_key_alias(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-standard-secret")

    settings = Settings.from_env()

    assert settings.openai_api_key == "test-standard-secret"


def test_settings_accepts_legacy_openaiapi_alias(monkeypatch) -> None:
    monkeypatch.setenv("OPENAIAPI", "test-legacy-secret")

    settings = Settings.from_env()

    assert settings.openai_api_key == "test-legacy-secret"
