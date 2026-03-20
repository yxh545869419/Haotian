from haotian.registry.capability_registry import CapabilityRegistryRecord, CapabilityStatus
from haotian.services.diff_service import CapabilityObservation, DiffService


def make_record(
    capability_id: str,
    *,
    status: CapabilityStatus,
    last_seen_at: str = "2026-03-10T00:00:00Z",
    last_score: float = 0.65,
    consecutive_appearances: int = 1,
) -> CapabilityRegistryRecord:
    return CapabilityRegistryRecord(
        capability_id=capability_id,
        canonical_name="Browser automation",
        status=status,
        summary="Automates browser workflows.",
        first_seen_at="2026-03-01T00:00:00Z",
        last_seen_at=last_seen_at,
        last_score=last_score,
        mention_count=1,
        consecutive_appearances=consecutive_appearances,
        source_repo_full_name="acme/demo",
    )


def make_observation(
    capability_id: str = "browser_automation",
    *,
    score: float = 0.72,
    observed_at: str = "2026-03-20T00:00:00Z",
    consecutive_appearances: int = 1,
) -> CapabilityObservation:
    return CapabilityObservation(
        capability_id=capability_id,
        canonical_name="Browser automation",
        summary="Automates browser workflows.",
        score=score,
        observed_at=observed_at,
        consecutive_appearances=consecutive_appearances,
        source_repo_full_name="acme/demo",
    )


def test_diff_service_marks_missing_capability_as_new() -> None:
    service = DiffService()

    result = service.analyze(make_observation(), None)

    assert result.decision == "new"
    assert result.should_alert is True


def test_diff_service_marks_active_capability_as_covered() -> None:
    service = DiffService()
    existing = make_record("browser_automation", status=CapabilityStatus.ACTIVE)

    result = service.analyze(make_observation(), existing)

    assert result.decision == "covered"
    assert result.should_alert is False


def test_diff_service_suppresses_recently_rejected_capability_during_cooldown() -> None:
    service = DiffService(cooldown_days=14, re_alert_min_consecutive=3, re_alert_min_score=0.8)
    existing = make_record(
        "browser_automation",
        status=CapabilityStatus.REJECTED,
        last_seen_at="2026-03-15T00:00:00Z",
        last_score=0.7,
        consecutive_appearances=1,
    )

    result = service.analyze(
        make_observation(score=0.78, observed_at="2026-03-20T00:00:00Z", consecutive_appearances=2),
        existing,
    )

    assert result.decision == "covered"
    assert result.should_alert is False
