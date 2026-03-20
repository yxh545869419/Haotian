"""Operator approval workflow for capability decisions."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from haotian.registry.capability_registry import (
    CapabilityApproval,
    CapabilityApprovalAction,
    CapabilityRegistryRecord,
    CapabilityRegistryRepository,
)


class ApprovalService:
    """Apply approval actions and persist both the audit log and registry status."""

    def __init__(self, repository: CapabilityRegistryRepository | None = None) -> None:
        self.repository = repository or CapabilityRegistryRepository()

    def apply_approval(
        self,
        *,
        capability_id: str,
        action: CapabilityApprovalAction | str,
        reviewer: str | None = None,
        note: str | None = None,
        snapshot_date: date | str | None = None,
    ) -> CapabilityRegistryRecord:
        approval_action = self._coerce_action(action)
        existing = self.repository.get_capability(capability_id)
        if existing is None:
            raise ValueError(f"Capability '{capability_id}' does not exist in the registry.")

        updated = replace(
            existing,
            status=approval_action.resulting_status,
            updated_at=None,
        )
        self.repository.upsert_capability(updated)
        self.repository.add_approval(
            CapabilityApproval(
                capability_id=capability_id,
                action=approval_action,
                resulting_status=approval_action.resulting_status,
                reviewer=reviewer,
                note=note,
                snapshot_date=self._normalize_snapshot_date(snapshot_date),
            )
        )
        refreshed = self.repository.get_capability(capability_id)
        if refreshed is None:
            raise RuntimeError(f"Capability '{capability_id}' could not be reloaded after approval.")
        return refreshed

    @staticmethod
    def _coerce_action(action: CapabilityApprovalAction | str) -> CapabilityApprovalAction:
        if isinstance(action, CapabilityApprovalAction):
            return action
        try:
            return CapabilityApprovalAction(action)
        except ValueError as exc:
            supported = ", ".join(item.value for item in CapabilityApprovalAction)
            raise ValueError(f"Unsupported approval action '{action}'. Supported actions: {supported}.") from exc

    @staticmethod
    def _normalize_snapshot_date(snapshot_date: date | str | None) -> str | None:
        if snapshot_date is None:
            return None
        if isinstance(snapshot_date, date):
            return snapshot_date.isoformat()
        return snapshot_date
