"""Repository capability classification interfaces."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from haotian.analyzers.capability_normalizer import CapabilityMatch, CapabilityNormalizer

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "capability_classification.md"


@dataclass(slots=True)
class RepoMetadata:
    """Minimal repository metadata used for capability classification."""

    repo_full_name: str
    description: str | None = None
    readme: str | None = None
    topics: list[str] = field(default_factory=list)
    language: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ClassifiedCapability:
    """Structured capability returned by the classifier."""

    capability_id: str
    name: str
    confidence: float
    reason: str
    summary: str
    source_label: str | None
    original_text: str | None
    needs_review: bool

    @classmethod
    def from_match(cls, match: CapabilityMatch) -> "ClassifiedCapability":
        return cls(
            capability_id=match.capability_id,
            name=match.canonical_name,
            confidence=match.confidence,
            reason=match.reason,
            summary=match.summary,
            source_label=match.source_label,
            original_text=match.original_text,
            needs_review=match.needs_review,
        )


@dataclass(slots=True)
class CapabilityClassificationResult:
    """Container for a repository's normalized capabilities."""

    repo_full_name: str
    capabilities: list[ClassifiedCapability]
    needs_human_confirmation: bool
    prompt: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_full_name": self.repo_full_name,
            "needs_human_confirmation": self.needs_human_confirmation,
            "prompt": self.prompt,
            "capabilities": [asdict(capability) for capability in self.capabilities],
        }


class CapabilityClassifier:
    """Classify repository metadata into a structured capability list."""

    def __init__(self, normalizer: CapabilityNormalizer | None = None) -> None:
        self.normalizer = normalizer or CapabilityNormalizer()

    def classify(self, metadata: RepoMetadata) -> CapabilityClassificationResult:
        """Extract candidate capability phrases and normalize them into taxonomy entries."""

        prompt = self.load_prompt()
        candidates = self._collect_candidates(metadata)
        normalized = self.normalizer.normalize_many(candidates)
        capabilities = [ClassifiedCapability.from_match(match) for match in normalized]
        return CapabilityClassificationResult(
            repo_full_name=metadata.repo_full_name,
            capabilities=capabilities,
            needs_human_confirmation=any(capability.needs_review for capability in capabilities),
            prompt=prompt,
        )

    @staticmethod
    def load_prompt() -> str:
        return PROMPT_PATH.read_text(encoding="utf-8")

    @staticmethod
    def _collect_candidates(metadata: RepoMetadata) -> list[tuple[str, str | None]]:
        candidates: list[tuple[str, str | None]] = []
        if metadata.description:
            candidates.append((metadata.description, "description"))
        if metadata.readme:
            candidates.append((metadata.readme, "readme"))
        candidates.extend((topic, "topic") for topic in metadata.topics)
        candidates.extend((tag, "tag") for tag in metadata.tags)
        if metadata.language:
            candidates.append((metadata.language, "language"))
        return candidates
