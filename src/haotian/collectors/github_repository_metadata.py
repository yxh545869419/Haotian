"""GitHub repository metadata fetch helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class RepositoryMetadataPayload:
    readme: str | None = None
    topics: tuple[str, ...] = ()
    pushed_at: str | None = None


class GithubRepositoryMetadataFetcher:
    """Fetch supplemental repository metadata used during capability classification."""

    api_base_url = "https://api.github.com"

    @lru_cache(maxsize=256)
    def fetch(self, repo_full_name: str) -> RepositoryMetadataPayload:
        repo_payload = self._fetch_repo_payload(repo_full_name)
        return RepositoryMetadataPayload(
            readme=self._fetch_readme(repo_full_name),
            topics=self._extract_topics(repo_payload),
            pushed_at=self._extract_pushed_at(repo_payload),
        )

    def _fetch_readme(self, repo_full_name: str) -> str | None:
        request = Request(
            f"{self.api_base_url}/repos/{repo_full_name}/readme",
            headers={
                "Accept": "application/vnd.github.raw+json",
                "User-Agent": "HaotianBot/0.1",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                return response.read().decode("utf-8", errors="ignore")
        except (HTTPError, URLError):
            return None

    def _fetch_repo_payload(self, repo_full_name: str) -> dict[str, object]:
        request = Request(
            f"{self.api_base_url}/repos/{repo_full_name}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "HaotianBot/0.1",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    @staticmethod
    def _extract_topics(payload: dict[str, object]) -> tuple[str, ...]:
        topics = payload.get("topics", [])
        if not isinstance(topics, list):
            return ()
        return tuple(str(item) for item in topics if isinstance(item, str))

    @staticmethod
    def _extract_pushed_at(payload: dict[str, object]) -> str | None:
        pushed_at = payload.get("pushed_at")
        if not isinstance(pushed_at, str) or not pushed_at.strip():
            return None
        return pushed_at.strip()
