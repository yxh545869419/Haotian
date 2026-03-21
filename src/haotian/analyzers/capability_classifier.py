"""Repository capability classification interfaces."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any

from haotian.analyzers.capability_normalizer import CapabilityMatch, CapabilityNormalizer
from haotian.config import get_settings
from haotian.llm.openai_codex import LLMNormalizedCapability, OpenAICodexCapabilityClient

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
    llm_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_full_name": self.repo_full_name,
            "needs_human_confirmation": self.needs_human_confirmation,
            "prompt": self.prompt,
            "llm_status": self.llm_status,
            "capabilities": [asdict(capability) for capability in self.capabilities],
        }


class CapabilityClassifier:
    """Classify repository metadata into a structured capability list."""

    def __init__(
        self,
        normalizer: CapabilityNormalizer | None = None,
        llm_client: OpenAICodexCapabilityClient | None = None,
    ) -> None:
        self.normalizer = normalizer or CapabilityNormalizer()
        self.llm_disabled_reason = ""
        self.llm_client = llm_client or self._build_llm_client()
        if llm_client is not None:
            self.llm_disabled_reason = ""
        elif self.llm_client is None:
            self.llm_disabled_reason = self._determine_llm_disabled_reason()

    def classify(self, metadata: RepoMetadata) -> CapabilityClassificationResult:
        """Normalize repository metadata into the approved taxonomy."""

        prompt = self.load_prompt()
        capabilities = self._classify_with_llm(metadata, prompt)
        if not capabilities:
            candidates = self._collect_candidates(metadata)
            normalized = self.normalizer.normalize_many(candidates)
            capabilities = [ClassifiedCapability.from_match(match) for match in normalized]
        return CapabilityClassificationResult(
            repo_full_name=metadata.repo_full_name,
            capabilities=capabilities,
            needs_human_confirmation=any(capability.needs_review for capability in capabilities),
            prompt=prompt,
            llm_status=llm_status,
        )

    def _classify_with_llm(self, metadata: RepoMetadata, prompt: str) -> tuple[list[ClassifiedCapability], str]:
        if self.llm_client is None:
            return [], self.llm_disabled_reason or "LLM disabled."
        try:
            llm_results = self.llm_client.normalize_capabilities(metadata, prompt)
        except Exception as exc:
            return [], f"LLM unavailable: {exc}"

        capabilities: list[ClassifiedCapability] = []
        for item in llm_results:
            capability = self._build_llm_capability(item)
            if capability is not None:
                capabilities.append(capability)
        deduped: dict[str, ClassifiedCapability] = {}
        for capability in capabilities:
            previous = deduped.get(capability.capability_id)
            if previous is None or capability.confidence > previous.confidence:
                deduped[capability.capability_id] = capability
        return sorted(deduped.values(), key=lambda item: (-item.confidence, item.capability_id)), "LLM enabled."

    def _build_llm_capability(self, item: LLMNormalizedCapability) -> ClassifiedCapability | None:
        normalized_id = self._normalize_capability_id(item.capability_id, item.original_text, item.summary)
        if not normalized_id:
            return None
        metadata = self.normalizer.taxonomy.get(normalized_id)
        capability_name = str(metadata["name"]) if metadata is not None else self._humanize_capability_name(normalized_id, item.summary)
        return ClassifiedCapability(
            capability_id=normalized_id,
            name=capability_name,
            confidence=round(item.confidence, 2),
            reason=item.reason,
            summary=item.summary,
            source_label=item.source_label,
            original_text=item.original_text,
            needs_review=item.needs_review,
        )

    def _classify_with_llm(self, metadata: RepoMetadata, prompt: str) -> list[ClassifiedCapability]:
        if self.llm_client is None:
            return []
        try:
            llm_results = self.llm_client.normalize_capabilities(metadata, prompt)
        except Exception:
            return []

        capabilities: list[ClassifiedCapability] = []
        for item in llm_results:
            capability = self._build_llm_capability(item)
            if capability is not None:
                capabilities.append(capability)
        deduped: dict[str, ClassifiedCapability] = {}
        for capability in capabilities:
            previous = deduped.get(capability.capability_id)
            if previous is None or capability.confidence > previous.confidence:
                deduped[capability.capability_id] = capability
        return sorted(deduped.values(), key=lambda item: (-item.confidence, item.capability_id))

    def _build_llm_capability(self, item: LLMNormalizedCapability) -> ClassifiedCapability | None:
        metadata = self.normalizer.taxonomy.get(item.capability_id)
        if metadata is None:
            return None
        return ClassifiedCapability(
            capability_id=item.capability_id,
            name=str(metadata["name"]),
            confidence=round(item.confidence, 2),
            reason=item.reason,
            summary=item.summary,
            source_label=item.source_label,
            original_text=item.original_text,
            needs_review=item.needs_review,
        )

    @staticmethod
    def load_prompt() -> str:
        return PROMPT_PATH.read_text(encoding="utf-8")

    @staticmethod
    def _collect_candidates(metadata: RepoMetadata) -> list[tuple[str, str | None]]:
        candidates: list[tuple[str, str | None]] = []
        candidates.extend((value, "repo_name") for value in CapabilityClassifier._chunk_text(metadata.repo_full_name.replace("/", " ")))
        if metadata.description:
            candidates.extend((value, "description") for value in CapabilityClassifier._chunk_text(metadata.description))
        if metadata.readme:
            candidates.extend((value, "readme") for value in CapabilityClassifier._chunk_text(metadata.readme))
        candidates.extend((topic, "topic") for topic in metadata.topics)
        candidates.extend((tag, "tag") for tag in metadata.tags)
        if metadata.language:
            candidates.append((metadata.language, "language"))
        deduped: list[tuple[str, str | None]] = []
        seen: set[tuple[str, str | None]] = set()
        for item in candidates:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    @staticmethod
    def _build_llm_client() -> OpenAICodexCapabilityClient | None:
        settings = get_settings()
        if settings.llm_provider != "openai" or not settings.openai_api_key:
            return None
        return OpenAICodexCapabilityClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
        )

    @staticmethod
    def _determine_llm_disabled_reason() -> str:
        settings = get_settings()
        if settings.llm_provider != "openai":
            return f"LLM disabled: unsupported provider '{settings.llm_provider}'."
        if not settings.openai_api_key:
            return "LLM disabled: OpenAIAPI/OPENAIAPI secret is not configured."
        return "LLM disabled: client initialization failed."

    @staticmethod
    def _chunk_text(text: str) -> list[str]:
        stripped = text.strip()
        if not stripped:
            return []
        normalized = re.sub(r"\r\n?", "\n", stripped)
        parts = re.split(r"[\n•\-*]+|(?<=[.!?])\s+", normalized)
        cleaned: list[str] = []
        for part in parts:
            candidate = re.sub(r"\s+", " ", part).strip(" #`>*")
            if len(candidate) < 3:
                continue
            cleaned.append(candidate[:240])
        return cleaned

    @staticmethod
    def _normalize_capability_id(capability_id: str, original_text: str | None, summary: str) -> str:
        raw = capability_id or original_text or summary
        normalized = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
        return normalized

    @staticmethod
    def _humanize_capability_name(capability_id: str, summary: str) -> str:
        prefix = summary.split(":", 1)[0].strip()
        if prefix and len(prefix.split()) <= 6:
            return prefix
        return capability_id.replace("_", " ").title()
