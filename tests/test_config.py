from __future__ import annotations

from haotian.config import Settings


def test_settings_accepts_standard_openai_api_key_alias(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-standard-secret")

    settings = Settings.from_env()

    assert settings.openai_api_key == "test-standard-secret"


def test_settings_accepts_legacy_openaiapi_alias(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAIAPI", "test-legacy-secret")

    settings = Settings.from_env()

    assert settings.openai_api_key == "test-legacy-secret"


def test_settings_prefers_standard_alias_when_both_are_present(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-standard-secret")
    monkeypatch.setenv("OPENAIAPI", "test-legacy-secret")

    settings = Settings.from_env()

    assert settings.openai_api_key == "test-standard-secret"
