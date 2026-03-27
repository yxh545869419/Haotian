"""Temporary repository workspace management."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import stat
import shutil
import subprocess
import time

from haotian.config import get_settings


@dataclass(frozen=True, slots=True)
class ClonedWorkspace:
    repo_full_name: str
    path: Path


class RepositoryWorkspaceService:
    """Clone and clean up temporary repository workspaces scoped to a run label."""

    _cleanup_retry_delays = (0.05, 0.1, 0.2)

    def __init__(self, run_label: str, base_dir: Path | str | None = None) -> None:
        self.run_label = self._validate_run_label(run_label)
        self.base_dir = self._resolve_base_dir(base_dir)
        self.workspace_root = self.base_dir / self.run_label
        self._ensure_within_base_dir(self.workspace_root)

    def workspace_path(self, repo_full_name: str) -> Path:
        repo_path = self._validate_repo_full_name(repo_full_name)
        target = self.workspace_root / repo_path
        self._ensure_within_workspace_root(target)
        return target

    def clone_repo(self, *, repo_full_name: str, repo_url: str) -> ClonedWorkspace:
        target = self.workspace_path(repo_full_name)
        self._remove_stale_workspace(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", repo_url, str(target)], check=True)
        return ClonedWorkspace(repo_full_name=repo_full_name, path=target)

    def cleanup_repo(self, workspace: ClonedWorkspace) -> None:
        expected_path = self.workspace_path(workspace.repo_full_name)
        if workspace.path.resolve(strict=False) != expected_path.resolve(strict=False):
            raise ValueError("workspace path must match repo_full_name")
        self._ensure_within_workspace_root(expected_path)
        self._remove_directory_tree(expected_path)
        self._prune_empty_workspace_ancestors(expected_path.parent)

    @staticmethod
    def _remove_readonly(func, path, exc_info) -> None:
        del exc_info
        os.chmod(path, stat.S_IWRITE)
        func(path)

    def _remove_stale_workspace(self, target: Path) -> None:
        self._ensure_within_workspace_root(target)
        if not target.exists() and not target.is_symlink():
            return
        if target.is_dir() and not target.is_symlink():
            self._remove_directory_tree(target)
            return

        try:
            target.unlink()
        except PermissionError:
            os.chmod(target, stat.S_IWRITE)
            target.unlink()

    def _remove_directory_tree(self, target: Path) -> None:
        for attempt in range(len(self._cleanup_retry_delays) + 1):
            try:
                shutil.rmtree(target, ignore_errors=False, onerror=self._remove_readonly)
                return
            except FileNotFoundError:
                return
            except OSError:
                if attempt >= len(self._cleanup_retry_delays) or not target.exists():
                    raise
                time.sleep(self._cleanup_retry_delays[attempt])

    def _prune_empty_workspace_ancestors(self, start: Path) -> None:
        current = start
        while current != self.base_dir:
            if not current.exists():
                current = current.parent
                continue
            if any(current.iterdir()):
                break
            current.rmdir()
            current = current.parent

    def _ensure_within_workspace_root(self, path: Path) -> None:
        workspace_root = self._resolved_workspace_root()
        resolved_path = path.resolve(strict=False)
        if resolved_path == workspace_root or workspace_root in resolved_path.parents:
            self._ensure_no_alias_path(path)
            self._ensure_no_symlink_ancestors(path)
            return
        raise ValueError("workspace path must remain within workspace_root")

    def _ensure_within_base_dir(self, path: Path) -> None:
        base_dir = self.base_dir.resolve(strict=False)
        resolved_path = path.resolve(strict=False)
        if resolved_path == base_dir or base_dir not in resolved_path.parents:
            raise ValueError("workspace path must remain within base_dir")

    def _resolved_workspace_root(self) -> Path:
        if self._is_alias_path(self.workspace_root):
            raise ValueError("workspace_root must not be a symlink or junction")
        self._ensure_within_base_dir(self.workspace_root)
        return self.workspace_root.resolve(strict=False)

    def _ensure_no_symlink_ancestors(self, path: Path) -> None:
        relative_path = path.relative_to(self.workspace_root)
        current = self.workspace_root
        for part in relative_path.parts[:-1]:
            current = current / part
            if self._is_alias_path(current):
                raise ValueError("workspace path must not traverse aliasing workspace_root ancestors")

    def _ensure_no_alias_path(self, path: Path) -> None:
        if self._is_alias_path(path):
            raise ValueError("workspace path must not be an alias path")

    @staticmethod
    def _resolve_base_dir(base_dir: Path | str | None) -> Path:
        if base_dir is None:
            base_dir = get_settings().tmp_repo_dir
        return Path(base_dir).resolve(strict=False)

    @staticmethod
    def _is_alias_path(path: Path) -> bool:
        if path.is_symlink():
            return True

        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction):
            try:
                return bool(is_junction())
            except OSError:
                return False

        if os.name == "nt":
            try:
                return bool(os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            except OSError:
                return False

        return False

    @staticmethod
    def _validate_repo_full_name(repo_full_name: str) -> Path:
        if not repo_full_name:
            raise ValueError("repo_full_name must identify a cloned repository directory")
        if repo_full_name in {".", ""}:
            raise ValueError("repo_full_name must identify a cloned repository directory")
        if repo_full_name.startswith("/") or repo_full_name.startswith("\\"):
            raise ValueError("repo_full_name must be in owner/repo form")
        if "\\" in repo_full_name:
            raise ValueError("repo_full_name must be in owner/repo form")

        repo_parts = repo_full_name.split("/")
        if len(repo_parts) != 2 or any(not part or part in {".", ".."} for part in repo_parts):
            raise ValueError("repo_full_name must be in owner/repo form")
        return Path(*repo_parts)

    @staticmethod
    def _validate_run_label(run_label: str) -> Path:
        if not run_label:
            raise ValueError("run_label must identify a workspace scope")
        if run_label in {".", ""}:
            raise ValueError("run_label must identify a workspace scope")
        if run_label.startswith("/") or run_label.startswith("\\"):
            raise ValueError("run_label must be a single path segment")
        if "\\" in run_label:
            raise ValueError("run_label must be a single path segment")

        scope_parts = run_label.split("/")
        if len(scope_parts) != 1 or any(not part or part in {".", ".."} for part in scope_parts):
            raise ValueError("run_label must be a single path segment")
        return Path(run_label)
