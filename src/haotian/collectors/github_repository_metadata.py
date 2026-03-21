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


class GithubRepositoryMetadataFetcher:
    """Fetch supplemental repository metadata used during capability classification."""

    api_base_url = "https://api.github.com"

    @lru_cache(maxsize=256)
    def fetch(self, repo_full_name: str) -> RepositoryMetadataPayload:
        return RepositoryMetadataPayload(
            readme=self._fetch_readme(repo_full_name),
            topics=self._fetch_topics(repo_full_name),
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

    def _fetch_topics(self, repo_full_name: str) -> tuple[str, ...]:
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
            return ()
        topics = payload.get("topics", [])
        if not isinstance(topics, list):
            return ()
        return tuple(str(item) for item in topics if isinstance(item, str))
