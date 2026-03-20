from haotian.analyzers.capability_normalizer import CapabilityNormalizer


def test_normalize_maps_known_synonyms_to_browser_automation() -> None:
    normalizer = CapabilityNormalizer()

    match = normalizer.normalize("web agent")

    assert match is not None
    assert match.capability_id == "browser_automation"
    assert match.confidence >= 0.9
    assert match.needs_review is False


def test_normalize_maps_scraping_to_data_extraction() -> None:
    normalizer = CapabilityNormalizer()

    match = normalizer.normalize("web scraping")

    assert match is not None
    assert match.capability_id == "data_extraction"


def test_normalize_uses_heuristics_and_flags_low_confidence_results() -> None:
    normalizer = CapabilityNormalizer()

    match = normalizer.normalize("tool for browser workflows")

    assert match is not None
    assert match.capability_id == "browser_automation"
    assert match.needs_review is True
    assert match.confidence < 0.6


def test_normalize_many_deduplicates_by_capability_id() -> None:
    normalizer = CapabilityNormalizer()

    matches = normalizer.normalize_many(["web agent", "browser automation", "codegen"])

    assert [match.capability_id for match in matches] == [
        "browser_automation",
        "code_generation",
    ]
