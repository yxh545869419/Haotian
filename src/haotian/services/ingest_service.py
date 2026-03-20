"""Persistence services for collected source data."""

from __future__ import annotations

from typing import Iterable

from haotian.collectors.github_trending import TrendingRepo
from haotian.db.schema import get_connection, initialize_schema


class IngestService:
    """Persist collected records into the local sqlite database."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    def ingest_trending_repos(self, repositories: Iterable[TrendingRepo]) -> int:
        """Insert or update trending repositories idempotently for a day/period/repo tuple."""

        initialize_schema(self.database_url)
        payload = [repo.to_record() for repo in repositories]
        if not payload:
            return 0

        with get_connection(self.database_url) as connection:
            connection.executemany(
                """
                INSERT INTO trending_repos (
                    snapshot_date,
                    period,
                    rank,
                    repo_full_name,
                    repo_url,
                    description,
                    language,
                    stars,
                    forks
                ) VALUES (
                    :snapshot_date,
                    :period,
                    :rank,
                    :repo_full_name,
                    :repo_url,
                    :description,
                    :language,
                    :stars,
                    :forks
                )
                ON CONFLICT(snapshot_date, period, repo_full_name)
                DO UPDATE SET
                    rank = excluded.rank,
                    repo_url = excluded.repo_url,
                    description = excluded.description,
                    language = excluded.language,
                    stars = excluded.stars,
                    forks = excluded.forks
                """,
                payload,
            )
            connection.commit()
        return len(payload)
