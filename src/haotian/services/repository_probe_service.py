"""Layered repository probing for deterministic deep-analysis evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from haotian.config import get_settings


@dataclass(frozen=True, slots=True)
class EvidenceSnippet:
    path: str
    excerpt: str
    why_it_matters: str


@dataclass(frozen=True, slots=True)
class RepositoryProbeResult:
    analysis_depth: str
    fallback_used: bool
    root_files: tuple[str, ...]
    matched_files: tuple[str, ...]
    matched_keywords: tuple[str, ...]
    architecture_signals: tuple[str, ...]
    probe_summary: str
    evidence_snippets: tuple[EvidenceSnippet, ...]
    analysis_limits: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ProbeMatch:
    path: Path
    relative_path: str
    keywords: tuple[str, ...]
    signal_group: str
    sort_rank: tuple[int, int, str]


class RepositoryProbeService:
    """Probe a repository with bounded, layered file selection."""

    _FIRST_PASS_PATTERNS: tuple[tuple[str, str], ...] = (
        ("skill*", "skill"),
        ("README*", "readme"),
        ("*.md", "markdown"),
        ("package.json", "package.json"),
        ("pyproject.toml", "pyproject.toml"),
        ("requirements.txt", "requirements.txt"),
        ("Dockerfile", "dockerfile"),
    )
    _SECOND_PASS_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("docs", ("docs/**/*.md", "*.md")),
        ("agents", ("agents/**/*.md", "*.md")),
        ("skills", ("skills/**/*.md", "skill*", "*.md")),
        ("prompts", ("prompts/**/*.md", "*.md")),
        ("entrypoint", ("main*", "app*", "server*", "cli*")),
        ("orchestration", ("agent*", "workflow*", "orchestr*", "tool*", "browser*", "rag*", "retriev*", "codegen*")),
    )

    def __init__(
        self,
        *,
        max_files: int | None = None,
        max_file_bytes: int | None = None,
        max_evidence_snippets: int | None = None,
    ) -> None:
        settings = get_settings()
        self.max_files = max_files or settings.max_repo_probe_files
        self.max_file_bytes = max_file_bytes or settings.max_repo_probe_file_bytes
        self.max_evidence_snippets = max_evidence_snippets or settings.max_evidence_snippets

    def probe(self, repository_root: Path | str) -> RepositoryProbeResult:
        root = Path(repository_root)
        try:
            root = root.resolve(strict=True)
        except FileNotFoundError:
            return self._fallback_result("repository root not found")

        if not root.is_dir():
            return self._fallback_result("repository root is not a directory")

        root_files = tuple(sorted(child.name for child in root.iterdir() if child.is_file()))
        recursive_files = tuple(sorted(path for path in root.rglob("*") if path.is_file()))
        matches = self._collect_matches(root, recursive_files)

        analysis_limits: list[str] = []
        selected = matches[: self.max_files]
        if len(matches) > len(selected):
            analysis_limits.append(
                f"file budget reached: kept {len(selected)} of {len(matches)} matched files (max_files={self.max_files})"
            )

        matched_keywords = self._ordered_keywords(selected)
        architecture_signals = self._derive_signals(selected, matched_keywords)
        snippets, snippet_limits = self._build_evidence_snippets(selected)
        analysis_limits.extend(snippet_limits)

        if not selected:
            analysis_limits.append("no deep signals matched")

        probe_summary = self._render_summary(root_files, selected, architecture_signals, analysis_limits)
        return RepositoryProbeResult(
            analysis_depth="layered",
            fallback_used=False,
            root_files=root_files,
            matched_files=tuple(match.relative_path for match in selected),
            matched_keywords=matched_keywords,
            architecture_signals=architecture_signals,
            probe_summary=probe_summary,
            evidence_snippets=snippets[: self.max_evidence_snippets],
            analysis_limits=tuple(dict.fromkeys(analysis_limits)),
        )

    def _collect_matches(self, root: Path, recursive_files: tuple[Path, ...]) -> list[_ProbeMatch]:
        matches: list[_ProbeMatch] = []
        seen_paths: set[str] = set()

        for child in sorted((path for path in root.iterdir() if path.is_file()), key=lambda path: path.name.lower()):
            keywords = self._first_pass_keywords(child.name)
            if not keywords:
                continue
            relative_path = child.relative_to(root).as_posix()
            matches.append(_ProbeMatch(child, relative_path, tuple(keywords), "root", self._first_pass_rank(child.name)))
            seen_paths.add(relative_path)

        for path in recursive_files:
            relative_path = path.relative_to(root).as_posix()
            if relative_path in seen_paths:
                continue
            keywords, group = self._second_pass_keywords(path, root)
            if not keywords:
                continue
            matches.append(_ProbeMatch(path, relative_path, tuple(keywords), group, self._second_pass_rank(group, relative_path)))
            seen_paths.add(relative_path)

        return sorted(matches, key=lambda match: match.sort_rank)

    def _first_pass_keywords(self, file_name: str) -> list[str]:
        keywords: list[str] = []
        lower_name = file_name.lower()
        if lower_name.startswith("skill"):
            keywords.append("skill*")
        if lower_name.startswith("readme"):
            keywords.append("README*")
        if lower_name.endswith(".md"):
            keywords.append("*.md")
        if file_name == "package.json":
            keywords.append("package.json")
        if file_name == "pyproject.toml":
            keywords.append("pyproject.toml")
        if file_name == "requirements.txt":
            keywords.append("requirements.txt")
        if file_name == "Dockerfile":
            keywords.append("Dockerfile")
        return keywords

    def _second_pass_keywords(self, path: Path, root: Path) -> tuple[list[str], str]:
        relative = path.relative_to(root)
        parts = relative.parts
        lower_parts = tuple(part.lower() for part in parts)
        file_name = path.name.lower()
        keywords: list[str] = []
        group = ""

        if len(lower_parts) >= 2 and lower_parts[0] == "docs" and file_name.endswith(".md"):
            keywords.extend(["docs/**/*.md", "*.md"])
            group = "docs"
        elif len(lower_parts) >= 2 and lower_parts[0] == "agents" and file_name.endswith(".md"):
            keywords.extend(["agents/**/*.md", "*.md"])
            group = "agents"
        elif len(lower_parts) >= 2 and lower_parts[0] == "skills" and file_name.endswith(".md"):
            keywords.extend(["skills/**/*.md", "skill*", "*.md"])
            group = "skills"
        elif len(lower_parts) >= 2 and lower_parts[0] == "prompts" and file_name.endswith(".md"):
            keywords.extend(["prompts/**/*.md", "*.md"])
            group = "prompts"

        if file_name.startswith("skill"):
            keywords.append("skill*")
            group = group or "skills"

        entrypoint_hits = self._match_entrypoint_keywords(file_name)
        orchestration_hits = self._match_orchestration_keywords(file_name)
        if entrypoint_hits:
            keywords.extend(entrypoint_hits)
            group = group or "entrypoint"
        if orchestration_hits:
            keywords.extend(orchestration_hits)
            group = group or "orchestration"

        if not keywords and file_name.endswith(".md"):
            keywords.append("*.md")
            group = group or "markdown"

        return self._dedupe_list(keywords), group or "markdown"

    def _first_pass_rank(self, file_name: str) -> tuple[int, int, str]:
        lower_name = file_name.lower()
        if lower_name.startswith("skill"):
            return (0, 0, file_name.lower())
        if lower_name.startswith("readme"):
            return (0, 1, file_name.lower())
        if lower_name.endswith(".md"):
            return (2, 0, file_name.lower())
        if file_name == "package.json":
            return (0, 3, file_name.lower())
        if file_name == "pyproject.toml":
            return (0, 4, file_name.lower())
        if file_name == "requirements.txt":
            return (0, 5, file_name.lower())
        if file_name == "Dockerfile":
            return (0, 6, file_name.lower())
        return (0, 99, file_name.lower())

    def _second_pass_rank(self, group: str, relative_path: str) -> tuple[int, int, str]:
        group_order = {
            "entrypoint": 0,
            "orchestration": 1,
            "docs": 2,
            "agents": 3,
            "skills": 4,
            "prompts": 5,
            "markdown": 6,
        }
        return (1, group_order.get(group, 99), relative_path)

    def _match_entrypoint_keywords(self, file_name: str) -> list[str]:
        keywords: list[str] = []
        if file_name.startswith("main"):
            keywords.append("main*")
        if file_name.startswith("app"):
            keywords.append("app*")
        if file_name.startswith("server"):
            keywords.append("server*")
        if file_name.startswith("cli"):
            keywords.append("cli*")
        return keywords

    def _match_orchestration_keywords(self, file_name: str) -> list[str]:
        keywords: list[str] = []
        if file_name.startswith("agent"):
            keywords.append("agent*")
        if file_name.startswith("workflow"):
            keywords.append("workflow*")
        if file_name.startswith("orchestr"):
            keywords.append("orchestr*")
        if file_name.startswith("tool"):
            keywords.append("tool*")
        if file_name.startswith("browser"):
            keywords.append("browser*")
        if file_name.startswith("rag"):
            keywords.append("rag*")
        if file_name.startswith("retriev"):
            keywords.append("retriev*")
        if file_name.startswith("codegen"):
            keywords.append("codegen*")
        return keywords

    def _ordered_keywords(self, matches: list[_ProbeMatch]) -> tuple[str, ...]:
        keywords: list[str] = []
        seen: set[str] = set()
        for match in matches:
            for keyword in match.keywords:
                if keyword in seen:
                    continue
                seen.add(keyword)
                keywords.append(keyword)
        return tuple(keywords)

    def _derive_signals(self, matches: list[_ProbeMatch], keywords: tuple[str, ...]) -> tuple[str, ...]:
        keyword_set = set(keywords)
        matched_paths = [match.relative_path.lower() for match in matches]
        signals: list[str] = []

        if keyword_set.intersection({"README*", "*.md", "docs/**/*.md", "agents/**/*.md", "skills/**/*.md", "prompts/**/*.md", "skill*"}):
            signals.append("documentation-first")
        if keyword_set.intersection({"skill*", "skills/**/*.md"}):
            signals.append("skill-centric")
        if keyword_set.intersection({"main*", "app*", "server*", "cli*", "package.json", "pyproject.toml", "requirements.txt", "Dockerfile"}):
            signals.append("entrypoint-driven")
        if keyword_set.intersection({"agent*", "workflow*", "orchestr*"}):
            signals.append("workflow-orchestration")
        if keyword_set.intersection({"browser*"}):
            signals.append("browser-automation")
        if keyword_set.intersection({"rag*", "retriev*"}):
            signals.append("retrieval")
        if keyword_set.intersection({"codegen*"}):
            signals.append("code-generation")
        if any(path.startswith("agents/") for path in matched_paths) and "workflow-orchestration" not in signals:
            signals.append("agent-centric")

        return tuple(dict.fromkeys(signals))

    def _build_evidence_snippets(self, matches: list[_ProbeMatch]) -> tuple[tuple[EvidenceSnippet, ...], list[str]]:
        snippets: list[EvidenceSnippet] = []
        limits: list[str] = []
        for match in matches[: self.max_evidence_snippets]:
            excerpt, truncated = self._read_excerpt(match.path)
            if truncated:
                limits.append(f"truncated excerpt for {match.relative_path} at {self.max_file_bytes} bytes")
            snippets.append(
                EvidenceSnippet(
                    path=match.relative_path,
                    excerpt=excerpt,
                    why_it_matters=self._why_it_matters(match),
                )
            )
        if len(matches) > len(snippets):
            limits.append(
                f"evidence snippet budget reached: kept {len(snippets)} of {len(matches)} selected files (max_evidence_snippets={self.max_evidence_snippets})"
            )
        return tuple(snippets), limits

    def _read_excerpt(self, path: Path) -> tuple[str, bool]:
        with path.open("rb") as handle:
            raw = handle.read(self.max_file_bytes + 1)
        truncated = len(raw) > self.max_file_bytes
        raw = raw[: self.max_file_bytes]
        text = raw.decode("utf-8", errors="replace")
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            normalized = path.name
        if truncated:
            return normalized[: max(0, self.max_file_bytes - 3)].rstrip() + "...", True
        return normalized, False

    def _why_it_matters(self, match: _ProbeMatch) -> str:
        if "skill*" in match.keywords:
            return "Shows the repository is organized around a skill contract."
        if "docs/**/*.md" in match.keywords or "agents/**/*.md" in match.keywords or "skills/**/*.md" in match.keywords or "prompts/**/*.md" in match.keywords:
            return "Documents operating guidance that often explains the real repository boundaries."
        if "main*" in match.keywords or "app*" in match.keywords or "server*" in match.keywords or "cli*" in match.keywords:
            return "Likely an executable entrypoint for the project."
        if "workflow*" in match.keywords or "agent*" in match.keywords or "orchestr*" in match.keywords:
            return "Shows orchestration or lifecycle control for the repository."
        if "browser*" in match.keywords:
            return "Suggests browser automation behavior."
        if "retriev*" in match.keywords or "rag*" in match.keywords:
            return "Suggests retrieval or RAG-style behavior."
        if "codegen*" in match.keywords:
            return "Suggests code generation behavior."
        if "pyproject.toml" in match.keywords:
            return "Declares packaging, dependencies, and likely runtime shape."
        if "README*" in match.keywords:
            return "Usually the clearest project overview for the repository."
        return "Provides bounded evidence for a prioritized repository signal."

    def _render_summary(
        self,
        root_files: tuple[str, ...],
        selected: list[_ProbeMatch],
        architecture_signals: tuple[str, ...],
        analysis_limits: list[str],
    ) -> str:
        if not selected:
            return f"No deep signals discovered; root files inspected: {', '.join(root_files) if root_files else 'none'}."
        signal_text = ", ".join(architecture_signals) if architecture_signals else "no named architecture signals"
        limit_text = f" Limits: {'; '.join(analysis_limits)}." if analysis_limits else ""
        return f"Layered probe selected {len(selected)} files across {signal_text}.{limit_text}"

    def _fallback_result(self, reason: str) -> RepositoryProbeResult:
        return RepositoryProbeResult(
            analysis_depth="fallback",
            fallback_used=True,
            root_files=(),
            matched_files=(),
            matched_keywords=(),
            architecture_signals=(),
            probe_summary=f"Fallback analysis used because {reason}.",
            evidence_snippets=(),
            analysis_limits=(reason,),
        )

    @staticmethod
    def _dedupe_list(values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped
