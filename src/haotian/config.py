"""Application configuration and environment loading."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

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
        alias="OPENAI_API_KEY",
        description="API key for OpenAI-compatible providers.",
    )
    report_dir: Path = Field(
        default=Path("data/reports"),
        alias="REPORT_DIR",
        description="Directory where generated reports are written.",
    )

    @classmethod
    def from_env(cls) -> "Settings":
        """Create settings from current environment variables."""
        import os

        values = {
            field.alias: value
            for field in cls.model_fields.values()
            if field.alias and (value := os.getenv(field.alias)) is not None
        }
        return cls.model_validate(values)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance for the current process."""

    settings = Settings.from_env()
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    return settings
