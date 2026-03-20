"""SQLite schema management utilities."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from haotian.config import get_settings


CREATE_TRENDING_REPOS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS trending_repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    period TEXT NOT NULL,
    rank INTEGER NOT NULL,
    repo_full_name TEXT NOT NULL,
    repo_url TEXT NOT NULL,
    description TEXT,
    language TEXT,
    stars INTEGER,
    forks INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_date, period, repo_full_name)
);
"""

CREATE_TRENDING_REPOS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_trending_repos_snapshot_period
ON trending_repos (snapshot_date, period);
"""

CREATE_REPO_CAPABILITIES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS repo_capabilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_full_name TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    reason TEXT NOT NULL,
    summary TEXT NOT NULL,
    needs_review INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (repo_full_name, capability_id)
);
"""

CREATE_REPO_CAPABILITIES_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_repo_capabilities_repo_review
ON repo_capabilities (repo_full_name, needs_review);
"""


def resolve_sqlite_path(database_url: str | None = None) -> Path:
    """Translate a sqlite URL into a local filesystem path."""

    resolved_url = database_url or get_settings().database_url
    if not resolved_url.startswith("sqlite:///"):
        raise ValueError("Only sqlite:/// URLs are supported by the built-in schema helper.")
    return Path(resolved_url.removeprefix("sqlite:///"))


def get_connection(database_url: str | None = None) -> sqlite3.Connection:
    """Open a sqlite connection and ensure the parent directory exists."""

    db_path = resolve_sqlite_path(database_url)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_schema(database_url: str | None = None) -> None:
    """Create required database tables and indexes if absent."""

    with get_connection(database_url) as connection:
        connection.execute(CREATE_TRENDING_REPOS_TABLE_SQL)
        connection.execute(CREATE_TRENDING_REPOS_INDEX_SQL)
        connection.execute(CREATE_REPO_CAPABILITIES_TABLE_SQL)
        connection.execute(CREATE_REPO_CAPABILITIES_INDEX_SQL)
        connection.commit()
