"""Capability taxonomy and normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

LOW_CONFIDENCE_THRESHOLD = 0.6

TAXONOMY: dict[str, dict[str, object]] = {
    "browser_automation": {
        "name": "Browser automation",
        "definition": "Automates browser actions such as navigation, clicking, extraction, and scripted workflows.",
        "synonyms": [
            "browser automation",
            "web automation",
            "web agent",
            "browser agent",
            "headless browser",
            "playwright automation",
            "selenium automation",
            "web browsing",
        ],
        "boundaries": "Use only when the repository directly controls a browser or web page workflow; exclude generic HTTP clients or API SDKs.",
    },
    "code_generation": {
        "name": "Code generation",
        "definition": "Produces source code, patches, or software implementation artifacts from natural language or other inputs.",
        "synonyms": [
            "code generation",
            "codegen",
            "coding agent",
            "ai coding",
            "software generation",
        ],
        "boundaries": "Exclude static analyzers or linters that only inspect code without generating substantial new code.",
    },
    "information_retrieval": {
        "name": "Information retrieval",
        "definition": "Searches, ranks, or retrieves relevant documents, snippets, or repository content for downstream use.",
        "synonyms": [
            "information retrieval",
            "search",
            "retrieval",
            "semantic search",
            "rag",
            "document retrieval",
        ],
        "boundaries": "Exclude end-user reporting tools unless retrieval is a core product behavior.",
    },
    "summarization": {
        "name": "Summarization",
        "definition": "Condenses documents, repositories, or conversations into shorter structured summaries.",
        "synonyms": [
            "summarization",
            "summary generation",
            "repo summary",
            "document summary",
        ],
        "boundaries": "Exclude general chat interfaces unless summarization is an explicit supported capability.",
    },
    "data_extraction": {
        "name": "Data extraction",
        "definition": "Extracts structured information from unstructured or semi-structured sources such as HTML, PDFs, or logs.",
        "synonyms": [
            "data extraction",
            "scraping",
            "web scraping",
            "structured extraction",
            "parsing",
        ],
        "boundaries": "Exclude analytics dashboards that only display already-structured data.",
    },
    "workflow_orchestration": {
        "name": "Workflow orchestration",
        "definition": "Coordinates multiple tasks, tools, or agents into repeatable execution flows.",
        "synonyms": [
            "workflow orchestration",
            "orchestration",
            "task orchestration",
            "agent workflow",
            "multi-step automation",
        ],
        "boundaries": "Exclude single-purpose utilities that do not manage multiple stages or tool invocations.",
    },
}


@dataclass(frozen=True, slots=True)
class CapabilityMatch:
    """Normalized capability match with confidence metadata."""

    capability_id: str
    canonical_name: str
    confidence: float
    reason: str
    summary: str
    needs_review: bool
    source_label: str | None = None
    original_text: str | None = None


class CapabilityNormalizer:
    """Normalize free-form capability text into canonical taxonomy IDs."""

    def __init__(
        self,
        taxonomy: dict[str, dict[str, object]] | None = None,
        low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
    ) -> None:
        self.taxonomy = taxonomy or TAXONOMY
        self.low_confidence_threshold = low_confidence_threshold
        self._synonym_lookup = self._build_synonym_lookup()

    def normalize(self, text: str, source_label: str | None = None) -> CapabilityMatch | None:
        """Map a single free-form capability expression to a taxonomy entry."""

        normalized_text = self._normalize_text(text)
        if not normalized_text:
            return None

        exact_match = self._synonym_lookup.get(normalized_text)
        if exact_match:
            return self._build_match(
                capability_id=exact_match,
                text=text,
                confidence=0.98,
                reason=f"Matched synonym '{normalized_text}' to taxonomy.",
                source_label=source_label,
            )

        tokens = set(normalized_text.split())
        best_capability_id: str | None = None
        best_score = 0.0
        for capability_id, metadata in self.taxonomy.items():
            variants = [capability_id.replace("_", " "), *metadata["synonyms"]]
            variant_scores = [self._token_overlap_score(tokens, set(self._normalize_text(variant).split())) for variant in variants]
            candidate_score = max(variant_scores, default=0.0)
            if candidate_score > best_score:
                best_capability_id = capability_id
                best_score = candidate_score

        if best_capability_id is None or best_score <= 0.0:
            return None

        confidence = min(0.45 + (best_score * 0.30), 0.85)
        return self._build_match(
            capability_id=best_capability_id,
            text=text,
            confidence=confidence,
            reason=f"Heuristic token overlap score {best_score:.2f} mapped to taxonomy.",
            source_label=source_label,
        )

    def normalize_many(self, entries: Iterable[tuple[str, str | None] | str]) -> list[CapabilityMatch]:
        """Normalize and deduplicate a collection of capability expressions."""

        deduped: dict[str, CapabilityMatch] = {}
        for entry in entries:
            if isinstance(entry, tuple):
                text, source_label = entry
            else:
                text, source_label = entry, None
            match = self.normalize(text, source_label=source_label)
            if match is None:
                continue
            previous = deduped.get(match.capability_id)
            if previous is None or match.confidence > previous.confidence:
                deduped[match.capability_id] = match
        return sorted(deduped.values(), key=lambda match: (-match.confidence, match.capability_id))

    def _build_synonym_lookup(self) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for capability_id, metadata in self.taxonomy.items():
            lookup[self._normalize_text(capability_id.replace("_", " "))] = capability_id
            lookup[self._normalize_text(metadata["name"])] = capability_id
            for synonym in metadata["synonyms"]:
                lookup[self._normalize_text(str(synonym))] = capability_id
        return lookup

    def _build_match(
        self,
        capability_id: str,
        text: str,
        confidence: float,
        reason: str,
        source_label: str | None,
    ) -> CapabilityMatch:
        metadata = self.taxonomy[capability_id]
        rounded_confidence = round(confidence, 2)
        return CapabilityMatch(
            capability_id=capability_id,
            canonical_name=str(metadata["name"]),
            confidence=rounded_confidence,
            reason=reason,
            summary=f"{metadata['name']}: {metadata['definition']}",
            needs_review=rounded_confidence < self.low_confidence_threshold,
            source_label=source_label,
            original_text=text,
        )

    @staticmethod
    def _token_overlap_score(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        intersection = left & right
        union = left | right
        return len(intersection) / len(union)

    @staticmethod
    def _normalize_text(value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
        return re.sub(r"\s+", " ", cleaned)
