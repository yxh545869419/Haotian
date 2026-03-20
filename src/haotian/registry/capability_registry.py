"""Read/write interfaces for the capability registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Iterable

from haotian.db.schema import get_connection, initialize_schema


class CapabilityStatus(StrEnum):
    """Lifecycle states for capability registry entries."""

    ACTIVE = "active"
    PENDING_REVIEW = "pending_review"
    WATCHLIST = "watchlist"
    POC = "poc"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"


class CapabilityApprovalAction(StrEnum):
    """Supported approval actions from the operations workflow."""

    IGNORE = "ignore"
    WATCHLIST = "watchlist"
    POC = "poc"
    ACTIVATE = "activate"
    REJECT = "reject"

    @property
    def resulting_status(self) -> CapabilityStatus:
        return {
            CapabilityApprovalAction.IGNORE: CapabilityStatus.DEPRECATED,
            CapabilityApprovalAction.WATCHLIST: CapabilityStatus.WATCHLIST,
            CapabilityApprovalAction.POC: CapabilityStatus.POC,
            CapabilityApprovalAction.ACTIVATE: CapabilityStatus.ACTIVE,
            CapabilityApprovalAction.REJECT: CapabilityStatus.REJECTED,
        }[self]


@dataclass(frozen=True, slots=True)
class CapabilityRegistryRecord:
    """Persistent registry row."""

    capability_id: str
    canonical_name: str
    status: CapabilityStatus
    summary: str
    first_seen_at: str
    last_seen_at: str
    last_score: float
    mention_count: int
    consecutive_appearances: int
    source_repo_full_name: str | None = None
    updated_at: str | None = None
    created_at: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilityApproval:
    """Review decision for a capability."""

    capability_id: str
    action: CapabilityApprovalAction
    resulting_status: CapabilityStatus
    reviewer: str | None = None
    note: str | None = None
    decided_at: str | None = None
    snapshot_date: str | None = None


class CapabilityRegistryRepository:
    """SQLite-backed capability registry storage."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    def get_capability(self, capability_id: str) -> CapabilityRegistryRecord | None:
        initialize_schema(self.database_url)
        with get_connection(self.database_url) as connection:
            row = connection.execute(
                "SELECT * FROM capability_registry WHERE capability_id = ?",
                (capability_id,),
            ).fetchone()
        return self._to_record(row) if row else None

    def list_capabilities(self, *, statuses: Iterable[CapabilityStatus] | None = None) -> list[CapabilityRegistryRecord]:
        initialize_schema(self.database_url)
        sql = "SELECT * FROM capability_registry"
        params: list[str] = []
        if statuses:
            values = [status.value for status in statuses]
            sql += f" WHERE status IN ({','.join('?' for _ in values)})"
            params.extend(values)
        sql += " ORDER BY last_seen_at DESC, capability_id ASC"
        with get_connection(self.database_url) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._to_record(row) for row in rows]

    def upsert_capability(self, record: CapabilityRegistryRecord) -> None:
        initialize_schema(self.database_url)
        now = _utc_now()
        with get_connection(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO capability_registry (
                    capability_id,
                    canonical_name,
                    status,
                    summary,
                    first_seen_at,
                    last_seen_at,
                    last_score,
                    mention_count,
                    consecutive_appearances,
                    source_repo_full_name,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capability_id)
                DO UPDATE SET
                    canonical_name = excluded.canonical_name,
                    status = excluded.status,
                    summary = excluded.summary,
                    first_seen_at = excluded.first_seen_at,
                    last_seen_at = excluded.last_seen_at,
                    last_score = excluded.last_score,
                    mention_count = excluded.mention_count,
                    consecutive_appearances = excluded.consecutive_appearances,
                    source_repo_full_name = excluded.source_repo_full_name,
                    updated_at = excluded.updated_at
                """,
                (
                    record.capability_id,
                    record.canonical_name,
                    record.status.value,
                    record.summary,
                    record.first_seen_at,
                    record.last_seen_at,
                    record.last_score,
                    record.mention_count,
                    record.consecutive_appearances,
                    record.source_repo_full_name,
                    record.created_at or now,
                    record.updated_at or now,
                ),
            )
            connection.commit()

    def add_approval(self, approval: CapabilityApproval) -> None:
        initialize_schema(self.database_url)
        with get_connection(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO capability_approvals (
                    capability_id,
                    action,
                    resulting_status,
                    reviewer,
                    note,
                    decided_at,
                    snapshot_date
                ) VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), ?)
                """,
                (
                    approval.capability_id,
                    approval.action.value,
                    approval.resulting_status.value,
                    approval.reviewer,
                    approval.note,
                    approval.decided_at,
                    approval.snapshot_date,
                ),
            )
            connection.commit()

    def list_approvals(self, capability_id: str) -> list[CapabilityApproval]:
        initialize_schema(self.database_url)
        with get_connection(self.database_url) as connection:
            rows = connection.execute(
                "SELECT * FROM capability_approvals WHERE capability_id = ? ORDER BY decided_at DESC, id DESC",
                (capability_id,),
            ).fetchall()
        return [
            CapabilityApproval(
                capability_id=row["capability_id"],
                action=CapabilityApprovalAction(row["action"]),
                resulting_status=CapabilityStatus(row["resulting_status"]),
                reviewer=row["reviewer"],
                note=row["note"],
                decided_at=row["decided_at"],
                snapshot_date=row["snapshot_date"],
            )
            for row in rows
        ]

    @staticmethod
    def _to_record(row: object) -> CapabilityRegistryRecord:
        return CapabilityRegistryRecord(
            capability_id=row["capability_id"],
            canonical_name=row["canonical_name"],
            status=CapabilityStatus(row["status"]),
            summary=row["summary"],
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
            last_score=float(row["last_score"]),
            mention_count=int(row["mention_count"]),
            consecutive_appearances=int(row["consecutive_appearances"]),
            source_repo_full_name=row["source_repo_full_name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
