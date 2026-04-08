"""Build stable skill candidate records from staged repository analysis items."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from haotian.services.repository_skill_package_service import DiscoveredSkillPackage


@dataclass(frozen=True, slots=True)
class RepositorySkillCandidate:
    candidate_id: str
    slug: str
    display_name: str
    repo_full_name: str
    repo_url: str
    relative_root: str
    files: tuple[str, ...]
    source_package_root: str | None = None
    description: str = ""
    matched_keywords: tuple[str, ...] = ()
    architecture_signals: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "slug": self.slug,
            "display_name": self.display_name,
            "repo_full_name": self.repo_full_name,
            "repo_url": self.repo_url,
            "relative_root": self.relative_root,
            "files": list(self.files),
            "source_package_root": self.source_package_root,
            "description": self.description,
            "matched_keywords": list(self.matched_keywords),
            "architecture_signals": list(self.architecture_signals),
        }


class RepositorySkillCandidateService:
    """Derive stable skill candidate records from staged repository items."""

    def extract(self, items: list[dict[str, object]] | tuple[dict[str, object], ...]) -> list[RepositorySkillCandidate]:
        candidates: list[RepositorySkillCandidate] = []
        seen_ids: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            repo_full_name = str(item.get("repo_full_name", "")).strip()
            repo_url = str(item.get("repo_url", "")).strip()
            repo_description = str(item.get("description", "")).strip()
            matched_keywords = tuple(
                str(keyword).strip()
                for keyword in item.get("matched_keywords", ())
                if str(keyword).strip()
            )
            architecture_signals = tuple(
                str(signal).strip()
                for signal in item.get("architecture_signals", ())
                if str(signal).strip()
            )
            raw_packages = item.get("discovered_skill_packages", ())
            if not isinstance(raw_packages, list):
                continue
            for raw_package in raw_packages:
                if not isinstance(raw_package, dict):
                    continue
                package = DiscoveredSkillPackage.from_serialized_payload(raw_package)
                slug = self._normalized_slug(package.skill_name or package.relative_root or repo_full_name)
                if not slug or not repo_full_name:
                    continue
                candidate_id = self._candidate_id(repo_full_name=repo_full_name, relative_root=package.relative_root, slug=slug)
                if candidate_id in seen_ids:
                    continue
                seen_ids.add(candidate_id)
                candidates.append(
                    RepositorySkillCandidate(
                        candidate_id=candidate_id,
                        slug=slug,
                        display_name=package.skill_name or slug,
                        repo_full_name=repo_full_name,
                        repo_url=repo_url,
                        relative_root=package.relative_root or ".",
                        files=package.files,
                        source_package_root=str(package.package_root),
                        description=package.description or repo_description,
                        matched_keywords=matched_keywords,
                        architecture_signals=architecture_signals,
                    )
                )
        candidates.sort(key=lambda item: (item.slug.casefold(), item.repo_full_name.casefold(), item.relative_root.casefold()))
        return candidates

    @staticmethod
    def _normalized_slug(value: str) -> str:
        collapsed = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
        return collapsed.strip("-")

    @classmethod
    def _candidate_id(cls, *, repo_full_name: str, relative_root: str, slug: str) -> str:
        raw = f"{repo_full_name.strip().lower()}|{relative_root.strip().lower()}|{slug}"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return f"skillcand-{digest}"
