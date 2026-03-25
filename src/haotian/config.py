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
        default="sqlite:///./data/haotian.db",
        alias="DATABASE_URL",
        description="Database connection URL.",
    )
    tmp_repo_dir: Path = Field(
        default=Path("data/tmp/repos"),
        alias="TMP_REPO_DIR",
        description="Directory where temporary repository clones are stored.",
    )
    max_repo_probe_files: int = Field(
        default=16,
        alias="MAX_REPO_PROBE_FILES",
        description="Maximum number of files to probe in a temporary clone.",
        gt=0,
    )
    max_repo_probe_file_bytes: int = Field(
        default=24000,
        alias="MAX_REPO_PROBE_FILE_BYTES",
        description="Maximum file size to inspect during repository probing.",
        gt=0,
    )
    max_evidence_snippets: int = Field(
        default=6,
        alias="MAX_EVIDENCE_SNIPPETS",
        description="Maximum number of evidence snippets to keep per analysis.",
        gt=0,
    )
    max_deep_analysis_repos: int = Field(
        default=12,
        alias="MAX_DEEP_ANALYSIS_REPOS",
        description="Maximum number of repositories to analyze in each deep-analysis batch.",
        gt=0,
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
    settings.tmp_repo_dir = _resolve_runtime_path(settings.tmp_repo_dir)
    settings.report_dir = _resolve_runtime_path(settings.report_dir)
    settings.run_dir = _resolve_runtime_path(settings.run_dir)
    settings.tmp_repo_dir.mkdir(parents=True, exist_ok=True)
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    settings.run_dir.mkdir(parents=True, exist_ok=True)
    return settings


def _resolve_runtime_path(path: Path) -> Path:
    base = Path.cwd()
    if not path.is_absolute():
        path = base / path
    return path.resolve(strict=False)
