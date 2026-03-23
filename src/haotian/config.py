"""Application configuration and environment loading."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()


class Settings(BaseModel):
    """Runtime settings sourced from environment variables."""

    database_url: str = Field(
        default="sqlite:///./data/app.db",
        alias="DATABASE_URL",
        description="Database connection URL.",
    )
    report_dir: Path = Field(
        default=Path("data/reports"),
        alias="REPORT_DIR",
        description="Directory where generated reports are written.",
    )
    run_dir: Path = Field(
        default=Path("data/runs"),
        alias="RUN_DIR",
        description="Directory where staged run artifacts are written.",
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
    settings.run_dir.mkdir(parents=True, exist_ok=True)
    return settings
