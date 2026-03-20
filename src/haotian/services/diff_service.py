"""Capability diff analysis with cooling-period aware re-alerting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from haotian.registry.capability_registry import CapabilityRegistryRecord, CapabilityStatus


@dataclass(frozen=True, slots=True)
class CapabilityObservation:
    """Incoming capability observation from trend analysis."""

    capability_id: str
    canonical_name: str
    summary: str
    score: float
    observed_at: str
    source_repo_full_name: str | None = None
    consecutive_appearances: int = 1


@dataclass(frozen=True, slots=True)
class DiffResult:
    """Diff outcome for a capability observation."""

    capability_id: str
    decision: str
    should_alert: bool
    reason: str


class DiffService:
    """Classify capability observations against the registry state."""

    def __init__(
        self,
        *,
        cooldown_days: int = 14,
        re_alert_min_consecutive: int = 3,
        re_alert_min_score: float = 0.8,
    ) -> None:
        self.cooldown_days = cooldown_days
        self.re_alert_min_consecutive = re_alert_min_consecutive
        self.re_alert_min_score = re_alert_min_score

    def analyze(self, observation: CapabilityObservation, existing: CapabilityRegistryRecord | None) -> DiffResult:
        if existing is None:
            return DiffResult(observation.capability_id, "new", True, "Capability not found in registry.")

        if existing.status in {CapabilityStatus.ACTIVE, CapabilityStatus.DEPRECATED}:
            return DiffResult(observation.capability_id, "covered", False, f"Capability already tracked as {existing.status.value}.")

        if existing.status is CapabilityStatus.REJECTED:
            return self._analyze_rejected(observation, existing)

        if self._is_meaningful_enhancement(observation, existing):
            return DiffResult(observation.capability_id, "enhancement", True, "Capability is already under review and shows stronger momentum.")

        return DiffResult(observation.capability_id, "covered", False, f"Capability already exists with status {existing.status.value}.")

    def _analyze_rejected(self, observation: CapabilityObservation, existing: CapabilityRegistryRecord) -> DiffResult:
        if not self._within_cooldown(observation.observed_at, existing.last_seen_at):
            return DiffResult(observation.capability_id, "re-alert", True, "Rejected capability has reappeared after the cooling period.")

        if (
            observation.consecutive_appearances >= self.re_alert_min_consecutive
            and observation.score >= self.re_alert_min_score
        ):
            return DiffResult(observation.capability_id, "re-alert", True, "Rejected capability keeps ranking repeatedly with a strong score during cooldown.")

        return DiffResult(observation.capability_id, "covered", False, "Recently rejected capability remains in cooldown and does not meet the re-alert threshold.")

    @staticmethod
    def _is_meaningful_enhancement(observation: CapabilityObservation, existing: CapabilityRegistryRecord) -> bool:
        return (
            observation.score > existing.last_score
            or observation.consecutive_appearances > existing.consecutive_appearances
        )

    def _within_cooldown(self, observed_at: str, last_seen_at: str) -> bool:
        observed = _parse_datetime(observed_at)
        previous = _parse_datetime(last_seen_at)
        return (observed - previous).days < self.cooldown_days


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
