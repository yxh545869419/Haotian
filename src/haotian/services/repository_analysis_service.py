"""Compose cloning, probing, fallback, and cleanup into one repository analysis step."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from haotian.services.repository_probe_service import EvidenceSnippet
from haotian.services.repository_probe_service import RepositoryProbeResult
from haotian.services.repository_probe_service import RepositoryProbeService
from haotian.services.repository_workspace_service import ClonedWorkspace
from haotian.services.repository_workspace_service import RepositoryWorkspaceService
from haotian.services.repository_skill_package_service import DiscoveredSkillPackage
from haotian.services.repository_skill_package_service import RepositorySkillPackageService


@dataclass(frozen=True, slots=True)
class RepositoryAnalysisResult:
    repo_full_name: str
    repo_url: str
    analysis_depth: str
    clone_strategy: str
    clone_started: bool
    analysis_completed: bool
    cleanup_attempted: bool
    cleanup_required: bool
    cleanup_completed: bool
    fallback_used: bool
    root_files: tuple[str, ...]
    matched_files: tuple[str, ...]
    matched_keywords: tuple[str, ...]
    architecture_signals: tuple[str, ...]
    probe_summary: str
    evidence_snippets: tuple[EvidenceSnippet, ...]
    analysis_limits: tuple[str, ...]
    discovered_skill_packages: tuple[DiscoveredSkillPackage, ...] = ()
    analysis_source: str = "fresh"

    def to_classification_input_fields(self) -> dict[str, object]:
        return {
            "analysis_source": self.analysis_source,
            "analysis_depth": self.analysis_depth,
            "clone_strategy": self.clone_strategy,
            "clone_started": self.clone_started,
            "analysis_completed": self.analysis_completed,
            "cleanup_attempted": self.cleanup_attempted,
            "cleanup_required": self.cleanup_required,
            "cleanup_completed": self.cleanup_completed,
            "fallback_used": self.fallback_used,
            "root_files": list(self.root_files),
            "matched_files": list(self.matched_files),
            "matched_keywords": list(self.matched_keywords),
            "architecture_signals": list(self.architecture_signals),
            "probe_summary": self.probe_summary,
            "evidence_snippets": [
                {
                    "path": snippet.path,
                    "excerpt": snippet.excerpt,
                    "why_it_matters": snippet.why_it_matters,
                }
                for snippet in self.evidence_snippets
            ],
            "analysis_limits": list(self.analysis_limits),
            "discovered_skill_packages": [
                package.to_serialized_payload()
                for package in self.discovered_skill_packages
            ],
        }

    def to_snapshot_row(self, snapshot_date: str) -> dict[str, object]:
        return {
            "snapshot_date": snapshot_date,
            "repo_full_name": self.repo_full_name,
            "repo_url": self.repo_url,
            "analysis_source": self.analysis_source,
            "analysis_depth": self.analysis_depth,
            "clone_strategy": self.clone_strategy,
            "clone_started": int(self.clone_started),
            "analysis_completed": int(self.analysis_completed),
            "cleanup_attempted": int(self.cleanup_attempted),
            "cleanup_required": int(self.cleanup_required),
            "cleanup_completed": int(self.cleanup_completed),
            "fallback_used": int(self.fallback_used),
            "root_files": [*self.root_files],
            "matched_files": [*self.matched_files],
            "matched_keywords": [*self.matched_keywords],
            "architecture_signals": [*self.architecture_signals],
            "probe_summary": self.probe_summary,
            "evidence_snippets": [
                {
                    "path": snippet.path,
                    "excerpt": snippet.excerpt,
                    "why_it_matters": snippet.why_it_matters,
                }
                for snippet in self.evidence_snippets
            ],
            "analysis_limits": [*self.analysis_limits],
            "discovered_skill_packages": [
                package.to_serialized_payload()
                for package in self.discovered_skill_packages
            ],
        }


class RepositoryAnalysisService:
    """Clone a repository, probe it, and return bounded evidence."""

    def __init__(
        self,
        *,
        run_label: str,
        base_dir: Path | str | None = None,
        workspace_service: RepositoryWorkspaceService | None = None,
        probe_service: RepositoryProbeService | None = None,
    ) -> None:
        self.run_label = run_label
        self.workspace_service = workspace_service or RepositoryWorkspaceService(run_label=run_label, base_dir=base_dir)
        self.probe_service = probe_service or RepositoryProbeService()
        self.skill_package_service = RepositorySkillPackageService()

    def analyze_repository(
        self,
        *,
        repo_full_name: str,
        repo_url: str,
        allow_deep_analysis: bool = True,
    ) -> RepositoryAnalysisResult:
        if not allow_deep_analysis:
            return self._build_budget_fallback(repo_full_name=repo_full_name, repo_url=repo_url)

        workspace: ClonedWorkspace | None = None
        clone_target: Path | None = None
        clone_started = False
        cleanup_required = False
        cleanup_attempted = False
        cleanup_completed = False
        analysis_completed = False
        probe_result: RepositoryProbeResult | None = None
        discovered_skill_packages: tuple[DiscoveredSkillPackage, ...] = ()
        analysis_limits: list[str] = []
        failure_reason = ""

        try:
            clone_target = self.workspace_service.workspace_path(repo_full_name)
            workspace = self.workspace_service.clone_repo(repo_full_name=repo_full_name, repo_url=repo_url)
            clone_started = True
            cleanup_required = True
            self._remove_git_metadata(workspace.path)
            discovered_skill_packages = self.skill_package_service.discover(workspace.path)
            probe_result = self.probe_service.probe(workspace.path)
            analysis_completed = True
        except Exception as exc:  # noqa: BLE001
            failure_reason = str(exc)
            analysis_limits.append(self._failure_limit_message(exc))
            if clone_target is not None and clone_target.exists():
                cleanup_required = True
                workspace = ClonedWorkspace(repo_full_name=repo_full_name, path=clone_target)
        finally:
            if cleanup_required and workspace is not None:
                cleanup_attempted = True
                try:
                    self.workspace_service.cleanup_repo(workspace)
                    cleanup_completed = True
                except Exception as exc:  # noqa: BLE001
                    cleanup_completed = False
                    analysis_limits.append(f"cleanup warning: {exc}")

        if probe_result is not None and not failure_reason:
            return self._build_success_result(
                repo_full_name=repo_full_name,
                repo_url=repo_url,
                probe_result=probe_result,
                clone_started=clone_started,
                analysis_completed=analysis_completed,
                cleanup_attempted=cleanup_attempted,
                cleanup_required=cleanup_required,
                cleanup_completed=cleanup_completed,
                analysis_limits=analysis_limits,
                discovered_skill_packages=discovered_skill_packages,
            )

        return self._build_fallback_from_failure(
            repo_full_name=repo_full_name,
            repo_url=repo_url,
            reason=failure_reason or "analysis fallback",
            clone_started=clone_started,
            cleanup_attempted=cleanup_attempted,
            cleanup_required=cleanup_required,
            cleanup_completed=cleanup_completed,
            analysis_completed=analysis_completed,
            analysis_limits=analysis_limits,
            discovered_skill_packages=discovered_skill_packages,
        )

    def _build_success_result(
        self,
        *,
        repo_full_name: str,
        repo_url: str,
        probe_result: RepositoryProbeResult,
        clone_started: bool,
        analysis_completed: bool,
        cleanup_attempted: bool,
        cleanup_required: bool,
        cleanup_completed: bool,
        analysis_limits: list[str],
        discovered_skill_packages: tuple[DiscoveredSkillPackage, ...],
    ) -> RepositoryAnalysisResult:
        combined_limits = [*probe_result.analysis_limits, *analysis_limits]
        return RepositoryAnalysisResult(
            repo_full_name=repo_full_name,
            repo_url=repo_url,
            analysis_depth=probe_result.analysis_depth,
            clone_strategy="shallow-clone",
            clone_started=clone_started,
            analysis_completed=analysis_completed,
            cleanup_attempted=cleanup_attempted,
            cleanup_required=cleanup_required,
            cleanup_completed=cleanup_completed,
            fallback_used=probe_result.fallback_used,
            root_files=probe_result.root_files,
            matched_files=probe_result.matched_files,
            matched_keywords=probe_result.matched_keywords,
            architecture_signals=probe_result.architecture_signals,
            probe_summary=probe_result.probe_summary,
            evidence_snippets=probe_result.evidence_snippets,
            analysis_limits=tuple(dict.fromkeys(combined_limits)),
            discovered_skill_packages=discovered_skill_packages,
            analysis_source="fresh",
        )

    def _build_budget_fallback(
        self,
        *,
        repo_full_name: str,
        repo_url: str,
        discovered_skill_packages: tuple[DiscoveredSkillPackage, ...] = (),
    ) -> RepositoryAnalysisResult:
        return RepositoryAnalysisResult(
            repo_full_name=repo_full_name,
            repo_url=repo_url,
            analysis_depth="fallback",
            clone_strategy="skipped-by-budget",
            clone_started=False,
            analysis_completed=False,
            cleanup_attempted=False,
            cleanup_required=False,
            cleanup_completed=False,
            fallback_used=True,
            root_files=(),
            matched_files=(),
            matched_keywords=(),
            architecture_signals=(),
            probe_summary="Deep analysis skipped because the repository budget was exhausted.",
            evidence_snippets=(),
            analysis_limits=("skipped due to deep-analysis budget",),
            discovered_skill_packages=discovered_skill_packages,
            analysis_source="fallback",
        )

    def _build_fallback_from_failure(
        self,
        *,
        repo_full_name: str,
        repo_url: str,
        reason: str,
        clone_started: bool,
        cleanup_attempted: bool,
        cleanup_required: bool,
        cleanup_completed: bool,
        analysis_completed: bool,
        analysis_limits: list[str],
        discovered_skill_packages: tuple[DiscoveredSkillPackage, ...],
    ) -> RepositoryAnalysisResult:
        combined_limits = [reason, *analysis_limits]
        clone_strategy = "clone-failed" if not clone_started else "probe-failed"
        return RepositoryAnalysisResult(
            repo_full_name=repo_full_name,
            repo_url=repo_url,
            analysis_depth="fallback",
            clone_strategy=clone_strategy,
            clone_started=clone_started,
            analysis_completed=analysis_completed,
            cleanup_attempted=cleanup_attempted,
            cleanup_required=cleanup_required,
            cleanup_completed=cleanup_completed,
            fallback_used=True,
            root_files=(),
            matched_files=(),
            matched_keywords=(),
            architecture_signals=(),
            probe_summary=f"Fallback analysis used because {reason}.",
            evidence_snippets=(),
            analysis_limits=tuple(dict.fromkeys(combined_limits)),
            discovered_skill_packages=discovered_skill_packages,
            analysis_source="fallback",
        )

    @staticmethod
    def _failure_limit_message(exc: Exception) -> str:
        return f"analysis fallback: {exc}"

    @staticmethod
    def _remove_git_metadata(workspace_path: Path) -> None:
        git_dir = workspace_path / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir, ignore_errors=True)
