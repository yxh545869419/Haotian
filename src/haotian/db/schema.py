"""SQLite schema management utilities."""

from __future__ import annotations

from contextlib import contextmanager
import sqlite3
from pathlib import Path
from collections.abc import Iterator

from haotian.config import PROJECT_ROOT, get_settings


CAPABILITY_REGISTRY_STATUS_VALUES = (
    "active",
    "pending_review",
    "watchlist",
    "poc",
    "rejected",
    "deprecated",
)
CAPABILITY_APPROVAL_ACTION_VALUES = (
    "ignore",
    "watchlist",
    "poc",
    "activate",
    "reject",
)
STATUS_CHECK_SQL = ", ".join(f"'{value}'" for value in CAPABILITY_REGISTRY_STATUS_VALUES)
ACTION_CHECK_SQL = ", ".join(f"'{value}'" for value in CAPABILITY_APPROVAL_ACTION_VALUES)

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
    snapshot_date TEXT NOT NULL DEFAULT '',
    period TEXT NOT NULL DEFAULT 'daily',
    repo_full_name TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    reason TEXT NOT NULL,
    summary TEXT NOT NULL,
    needs_review INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_date, period, repo_full_name, capability_id)
);
"""

CREATE_REPO_CAPABILITIES_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_repo_capabilities_snapshot_period
ON repo_capabilities (snapshot_date, period, capability_id);
"""

CREATE_REPO_ANALYSIS_SNAPSHOTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS repo_analysis_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    repo_full_name TEXT NOT NULL,
    repo_url TEXT NOT NULL,
    analysis_source TEXT NOT NULL DEFAULT 'fresh',
    analysis_depth TEXT NOT NULL,
    clone_strategy TEXT NOT NULL,
    clone_started INTEGER NOT NULL DEFAULT 0,
    analysis_completed INTEGER NOT NULL DEFAULT 0,
    cleanup_attempted INTEGER NOT NULL DEFAULT 0,
    cleanup_required INTEGER NOT NULL DEFAULT 0,
    cleanup_completed INTEGER NOT NULL DEFAULT 0,
    fallback_used INTEGER NOT NULL DEFAULT 0,
    root_files TEXT NOT NULL DEFAULT '[]',
    matched_files TEXT NOT NULL DEFAULT '[]',
    matched_keywords TEXT NOT NULL DEFAULT '[]',
    architecture_signals TEXT NOT NULL DEFAULT '[]',
    probe_summary TEXT NOT NULL DEFAULT '',
    evidence_snippets TEXT NOT NULL DEFAULT '[]',
    analysis_limits TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_date, repo_full_name)
);
"""

CREATE_REPO_ANALYSIS_SNAPSHOTS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_repo_analysis_snapshots_snapshot_date
ON repo_analysis_snapshots (snapshot_date, repo_full_name);
"""

CREATE_REPO_ANALYSIS_CACHE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS repo_analysis_cache (
    repo_full_name TEXT PRIMARY KEY,
    repo_url TEXT NOT NULL,
    source_pushed_at TEXT,
    analyzed_at TEXT NOT NULL,
    analysis_depth TEXT NOT NULL,
    root_files TEXT NOT NULL DEFAULT '[]',
    matched_files TEXT NOT NULL DEFAULT '[]',
    matched_keywords TEXT NOT NULL DEFAULT '[]',
    architecture_signals TEXT NOT NULL DEFAULT '[]',
    probe_summary TEXT NOT NULL DEFAULT '',
    evidence_snippets TEXT NOT NULL DEFAULT '[]',
    analysis_limits TEXT NOT NULL DEFAULT '[]',
    discovered_skill_packages TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_REPO_ANALYSIS_CACHE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_repo_analysis_cache_updated
ON repo_analysis_cache (updated_at DESC, repo_full_name);
"""

CREATE_CAPABILITY_REGISTRY_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS capability_registry (
    capability_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ({STATUS_CHECK_SQL})),
    summary TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_score REAL NOT NULL DEFAULT 0,
    mention_count INTEGER NOT NULL DEFAULT 1,
    consecutive_appearances INTEGER NOT NULL DEFAULT 1,
    source_repo_full_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_CAPABILITY_REGISTRY_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_capability_registry_status_seen
ON capability_registry (status, last_seen_at DESC);
"""

CREATE_CAPABILITY_APPROVALS_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS capability_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capability_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ({ACTION_CHECK_SQL})),
    resulting_status TEXT NOT NULL CHECK (resulting_status IN ({STATUS_CHECK_SQL})),
    reviewer TEXT,
    note TEXT,
    snapshot_date TEXT,
    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (capability_id) REFERENCES capability_registry(capability_id)
);
"""

CREATE_CAPABILITY_APPROVALS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_capability_approvals_capability_decided
ON capability_approvals (capability_id, decided_at DESC);
"""


def resolve_sqlite_path(database_url: str | None = None) -> Path:
    """Translate a sqlite URL into a local filesystem path."""

    resolved_url = database_url or get_settings().database_url
    if not resolved_url.startswith("sqlite:///"):
        raise ValueError("Only sqlite:/// URLs are supported by the built-in schema helper.")
    raw_path = Path(resolved_url.removeprefix("sqlite:///"))
    if not raw_path.is_absolute():
        raw_path = PROJECT_ROOT / raw_path
    return raw_path.resolve(strict=False)


@contextmanager
def get_connection(database_url: str | None = None) -> Iterator[sqlite3.Connection]:
    """Open a sqlite connection, yield it, and always close it on exit."""

    db_path = resolve_sqlite_path(database_url)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def initialize_schema(database_url: str | None = None) -> None:
    """Create required database tables and indexes if absent."""

    with get_connection(database_url) as connection:
        connection.execute(CREATE_TRENDING_REPOS_TABLE_SQL)
        connection.execute(CREATE_TRENDING_REPOS_INDEX_SQL)
        connection.execute(CREATE_REPO_CAPABILITIES_TABLE_SQL)
        connection.execute(CREATE_REPO_CAPABILITIES_INDEX_SQL)
        connection.execute(CREATE_REPO_ANALYSIS_SNAPSHOTS_TABLE_SQL)
        connection.execute(CREATE_REPO_ANALYSIS_SNAPSHOTS_INDEX_SQL)
        connection.execute(CREATE_REPO_ANALYSIS_CACHE_TABLE_SQL)
        connection.execute(CREATE_REPO_ANALYSIS_CACHE_INDEX_SQL)
        connection.execute(CREATE_CAPABILITY_REGISTRY_TABLE_SQL)
        connection.execute(CREATE_CAPABILITY_REGISTRY_INDEX_SQL)
        connection.execute(CREATE_CAPABILITY_APPROVALS_TABLE_SQL)
        connection.execute(CREATE_CAPABILITY_APPROVALS_INDEX_SQL)
        _migrate_repo_capabilities_table(connection)
        _migrate_repo_analysis_snapshots_table(connection)
        _migrate_repo_analysis_cache_table(connection)
        _migrate_capability_approvals_table(connection)
        connection.commit()


def _migrate_repo_capabilities_table(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(repo_capabilities)").fetchall()
    }
    if not columns or {"snapshot_date", "period"}.issubset(columns):
        return

    connection.execute("ALTER TABLE repo_capabilities RENAME TO repo_capabilities_legacy")
    connection.execute(CREATE_REPO_CAPABILITIES_TABLE_SQL)
    connection.execute(CREATE_REPO_CAPABILITIES_INDEX_SQL)
    connection.execute(
        """
        INSERT INTO repo_capabilities (
            snapshot_date,
            period,
            repo_full_name,
            capability_id,
            confidence,
            reason,
            summary,
            needs_review,
            created_at
        )
        SELECT
            COALESCE(substr(created_at, 1, 10), date('now')) AS snapshot_date,
            'daily' AS period,
            repo_full_name,
            capability_id,
            confidence,
            reason,
            summary,
            needs_review,
            created_at
        FROM repo_capabilities_legacy
        """
    )
    connection.execute("DROP TABLE repo_capabilities_legacy")


def _migrate_repo_analysis_snapshots_table(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(repo_analysis_snapshots)").fetchall()
    }
    if columns and "analysis_source" not in columns:
        connection.execute(
            "ALTER TABLE repo_analysis_snapshots ADD COLUMN analysis_source TEXT NOT NULL DEFAULT 'fresh'"
        )


def _migrate_repo_analysis_cache_table(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(repo_analysis_cache)").fetchall()
    }
    if columns and "discovered_skill_packages" not in columns:
        connection.execute(
            "ALTER TABLE repo_analysis_cache ADD COLUMN discovered_skill_packages TEXT NOT NULL DEFAULT '[]'"
        )


def _migrate_capability_approvals_table(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(capability_approvals)").fetchall()
    }
    if not columns:
        return
    if "action" in columns and "resulting_status" in columns:
        return

    connection.execute("ALTER TABLE capability_approvals RENAME TO capability_approvals_legacy")
    connection.execute(CREATE_CAPABILITY_APPROVALS_TABLE_SQL)
    legacy_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(capability_approvals_legacy)").fetchall()
    }
    if "status" in legacy_columns:
        connection.execute(
            """
            INSERT INTO capability_approvals (
                capability_id,
                action,
                resulting_status,
                reviewer,
                note,
                snapshot_date,
                decided_at
            )
            SELECT
                capability_id,
                CASE status
                    WHEN 'active' THEN 'activate'
                    WHEN 'rejected' THEN 'reject'
                    WHEN 'deprecated' THEN 'ignore'
                    ELSE status
                END AS action,
                status AS resulting_status,
                reviewer,
                note,
                snapshot_date,
                decided_at
            FROM capability_approvals_legacy
            """
        )
    connection.execute("DROP TABLE capability_approvals_legacy")
