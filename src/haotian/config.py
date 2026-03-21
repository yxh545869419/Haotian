"""Application configuration and environment loading."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import AliasChoices, BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    """Runtime settings sourced from environment variables."""

    database_url: str = Field(
        default="sqlite:///./data/app.db",
        alias="DATABASE_URL",
        description="Database connection URL.",
    )
    llm_provider: str = Field(
        default="openai",
        alias="LLM_PROVIDER",
        description="LLM provider identifier.",
    )
    openai_api_key: str | None = Field(
        default=None,
        alias="OpenAIAPI",
        validation_alias=AliasChoices("OpenAIAPI", "OPENAIAPI"),
        description="API key loaded from the Codex Secret named OpenAIAPI.",
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        alias="OPENAI_BASE_URL",
        description="Base URL for the OpenAI-compatible API.",
    )
    openai_model: str = Field(
        default="gpt-5-mini",
        alias="OPENAI_MODEL",
        description="Default model used for capability extraction.",
    )
    telegram_bot_token: str | None = Field(
        default=None,
        alias="TelegramBotToken",
        description="Telegram bot token loaded from the TelegramBotToken secret.",
    )
    report_dir: Path = Field(
        default=Path("data/reports"),
        alias="REPORT_DIR",
        description="Directory where generated reports are written.",
    )

    @classmethod
    def from_env(cls) -> "Settings":
        """Create settings from the current runtime, including injected Codex Secrets."""
        import os

        values = {}
        for name, field in cls.model_fields.items():
            aliases = []
            if field.alias:
                aliases.append(field.alias)
            validation_alias = getattr(field, "validation_alias", None)
            choices = getattr(validation_alias, "choices", None)
            if choices:
                aliases.extend(choice for choice in choices if isinstance(choice, str))
            for alias in aliases:
                value = os.getenv(alias)
                if value is not None:
                    values[field.alias or name] = value
                    break
        return cls.model_validate(values)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance for the current process."""

    settings = Settings.from_env()
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    return settings
