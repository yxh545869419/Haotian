"""OpenAI Codex-backed capability classification helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(slots=True)
class LLMNormalizedCapability:
    capability_id: str
    confidence: float
    reason: str
    summary: str
    needs_review: bool
    source_label: str = "llm"
    original_text: str | None = None


class OpenAICodexCapabilityClient:
    """Small wrapper around the OpenAI Responses API for taxonomy normalization."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-5-mini",
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def normalize_capabilities(self, metadata: Any, prompt: str) -> list[LLMNormalizedCapability]:
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                prompt
                                + "\nReturn strict JSON only using the documented output schema."
                                + " Do not emit markdown fences or commentary."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": self._render_metadata(metadata),
                        }
                    ],
                },
            ],
        }
        request = Request(
            url=f"{self.base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"OpenAI API request failed with status {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"OpenAI API request failed: {exc.reason}") from exc

        text = self._extract_text(data)
        if not text:
            return []
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise RuntimeError("OpenAI API returned non-list capability payload.")
        results: list[LLMNormalizedCapability] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            capability_id = str(item.get("capability_id", "")).strip()
            if not capability_id:
                continue
            confidence = float(item.get("confidence", 0.0))
            results.append(
                LLMNormalizedCapability(
                    capability_id=capability_id,
                    confidence=max(0.0, min(confidence, 1.0)),
                    reason=str(item.get("reason", "")).strip() or "LLM selected taxonomy capability.",
                    summary=str(item.get("summary", "")).strip() or capability_id.replace("_", " "),
                    needs_review=bool(item.get("needs_review", confidence < 0.6)),
                    source_label="llm",
                    original_text=str(item.get("original_text", "")).strip() or None,
                )
            )
        return results


    def respond(self, *, system_prompt: str, user_prompt: str, context: str = "") -> str:
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"Context:\n{context}\n\nQuestion:\n{user_prompt}",
                        }
                    ],
                },
            ],
        }
        request = Request(
            url=f"{self.base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"OpenAI API request failed with status {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"OpenAI API request failed: {exc.reason}") from exc
        text = self._extract_text(data).strip()
        if not text:
            raise RuntimeError("OpenAI API returned an empty chat response.")
        return text

    @staticmethod
    def _extract_text(data: dict[str, object]) -> str:
        output = data.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for entry in content:
                    if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                        return entry["text"]
        output_text = data.get("output_text")
        if isinstance(output_text, str):
            return output_text
        return ""

    @staticmethod
    def _render_metadata(metadata: Any) -> str:
        return json.dumps(
            {
                "repo_full_name": getattr(metadata, "repo_full_name", None),
                "description": getattr(metadata, "description", None),
                "readme": getattr(metadata, "readme", None),
                "topics": getattr(metadata, "topics", None),
                "language": getattr(metadata, "language", None),
                "tags": getattr(metadata, "tags", None),
            },
            ensure_ascii=False,
        )
