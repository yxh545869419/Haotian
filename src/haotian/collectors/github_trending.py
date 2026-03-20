"""GitHub Trending collector."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

BASE_URL = "https://github.com"
TRENDING_PATH = "/trending"
RAW_HTML_DIR = Path("data/raw/trending")
SUPPORTED_PERIODS = {"daily", "weekly", "monthly"}


@dataclass(slots=True)
class TrendingRepo:
    """Structured representation of one GitHub Trending repository."""

    snapshot_date: str
    period: str
    rank: int
    repo_full_name: str
    repo_url: str
    description: str | None
    language: str | None
    stars: int | None
    forks: int | None

    def to_record(self) -> dict[str, object]:
        """Return a dict representation suitable for persistence."""

        return asdict(self)


class GithubTrendingCollector:
    """Fetch and parse GitHub Trending repositories."""

    def __init__(self, raw_html_dir: Path = RAW_HTML_DIR) -> None:
        self.raw_html_dir = raw_html_dir

    def build_trending_url(self, period: Literal["daily", "weekly", "monthly"]) -> str:
        """Build the GitHub Trending URL for a given period."""

        if period not in SUPPORTED_PERIODS:
            raise ValueError(f"Unsupported period: {period}")
        if period == "daily":
            return urljoin(BASE_URL, TRENDING_PATH)
        query = urlencode({"since": period})
        return f"{urljoin(BASE_URL, TRENDING_PATH)}?{query}"

    def fetch_trending(self, period: Literal["daily", "weekly", "monthly"]) -> list[TrendingRepo]:
        """Fetch trending HTML, persist it locally, and parse repository records."""

        url = self.build_trending_url(period)
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; HaotianBot/0.1; +https://github.com)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urlopen(request) as response:
            html = response.read().decode("utf-8")

        snapshot_date = datetime.now(UTC).date().isoformat()
        self.save_raw_html(html=html, period=period, snapshot_date=snapshot_date)
        return self.parse_trending_html(html=html, period=period, snapshot_date=snapshot_date)

    def save_raw_html(self, html: str, period: str, snapshot_date: str) -> Path:
        """Persist raw HTML for selector debugging and future audits."""

        self.raw_html_dir.mkdir(parents=True, exist_ok=True)
        destination = self.raw_html_dir / f"github_trending_{snapshot_date}_{period}.html"
        destination.write_text(html, encoding="utf-8")
        return destination

    def parse_trending_html(self, html: str, period: str, snapshot_date: str | None = None) -> list[TrendingRepo]:
        """Parse GitHub Trending HTML into normalized repo records."""

        if period not in SUPPORTED_PERIODS:
            raise ValueError(f"Unsupported period: {period}")
        resolved_date = snapshot_date or date.today().isoformat()
        soup = BeautifulSoup(html, "html.parser")
        repositories: list[TrendingRepo] = []

        for rank, article in enumerate(soup.select("article.Box-row"), start=1):
            title_link = article.select_one("h2 a")
            if title_link is None:
                continue

            repo_path = (title_link.get("href") or "").strip()
            repo_full_name = " ".join(title_link.get_text(" ", strip=True).split()).replace(" / ", "/")
            description_node = article.select_one("p")
            language_node = article.select_one('[itemprop="programmingLanguage"]')
            star_link = article.select_one('a[href$="/stargazers"]')
            fork_link = article.select_one('a[href$="/forks"]')

            repositories.append(
                TrendingRepo(
                    snapshot_date=resolved_date,
                    period=period,
                    rank=rank,
                    repo_full_name=repo_full_name,
                    repo_url=urljoin(BASE_URL, repo_path),
                    description=self._clean_text(description_node.get_text(" ", strip=True)) if description_node else None,
                    language=self._clean_text(language_node.get_text(" ", strip=True)) if language_node else None,
                    stars=self._parse_count(star_link.get_text(" ", strip=True)) if star_link else None,
                    forks=self._parse_count(fork_link.get_text(" ", strip=True)) if fork_link else None,
                )
            )

        return repositories

    @staticmethod
    def _clean_text(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    @staticmethod
    def _parse_count(value: str | None) -> int | None:
        if not value:
            return None
        normalized = value.strip().lower().replace(",", "")
        multiplier = 1
        if normalized.endswith("k"):
            multiplier = 1000
            normalized = normalized[:-1]
        elif normalized.endswith("m"):
            multiplier = 1_000_000
            normalized = normalized[:-1]
        try:
            return int(float(normalized) * multiplier)
        except ValueError:
            return None
