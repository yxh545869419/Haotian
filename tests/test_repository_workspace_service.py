from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import haotian.services.repository_workspace_service as repository_workspace_module
from haotian.config import get_settings
from haotian.services.repository_workspace_service import ClonedWorkspace
from haotian.services.repository_workspace_service import RepositoryWorkspaceService


def init_local_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test User"], check=True)
    (path / "README.md").write_text("demo repo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "initial commit"], check=True)
    return path


def test_workspace_service_uses_settings_tmp_repo_dir_for_run_scope(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TMP_REPO_DIR", str(tmp_path / "configured-tmp-repos"))
    get_settings.cache_clear()
    try:
        service = RepositoryWorkspaceService(run_label="2026-03-24")

        assert service.base_dir == tmp_path / "configured-tmp-repos"
        assert service.workspace_root == tmp_path / "configured-tmp-repos" / "2026-03-24"
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("run_label", ["", ".", "../escape", "2026/03/24"])
def test_workspace_service_rejects_malformed_run_label(tmp_path, run_label) -> None:
    with pytest.raises(ValueError):
        RepositoryWorkspaceService(run_label=run_label, base_dir=tmp_path / "tmp-repos")


def test_workspace_path_rejects_escape_segments(tmp_path) -> None:
    service = RepositoryWorkspaceService(run_label="2026-03-24", base_dir=tmp_path / "tmp-repos")

    with pytest.raises(ValueError):
        service.workspace_path("../escape")


@pytest.mark.parametrize("repo_full_name", ["", ".", "acme", "acme/demo/extra"])
def test_workspace_path_rejects_malformed_repo_names(tmp_path, repo_full_name) -> None:
    service = RepositoryWorkspaceService(run_label="2026-03-24", base_dir=tmp_path / "tmp-repos")

    with pytest.raises(ValueError):
        service.workspace_path(repo_full_name)


def test_workspace_cleanup_rejects_paths_outside_base_dir(tmp_path) -> None:
    service = RepositoryWorkspaceService(run_label="2026-03-24", base_dir=tmp_path / "tmp-repos")
    outside_path = tmp_path / "escape"

    with pytest.raises(ValueError):
        service.cleanup_repo(ClonedWorkspace(repo_full_name="acme/demo", path=outside_path))


def test_workspace_cleanup_rejects_base_dir_itself(tmp_path) -> None:
    base_dir = tmp_path / "tmp-repos"
    service = RepositoryWorkspaceService(run_label="2026-03-24", base_dir=base_dir)

    with pytest.raises(ValueError):
        service.cleanup_repo(ClonedWorkspace(repo_full_name="acme/demo", path=base_dir))


def test_workspace_cleanup_rejects_in_base_namespace_directory(tmp_path) -> None:
    base_dir = tmp_path / "tmp-repos"
    service = RepositoryWorkspaceService(run_label="2026-03-24", base_dir=base_dir)
    namespace_dir = base_dir / "acme"

    with pytest.raises(ValueError):
        service.cleanup_repo(ClonedWorkspace(repo_full_name="acme/demo", path=namespace_dir))


@pytest.mark.parametrize("repo_full_name", ["acme", "acme/demo/extra"])
def test_workspace_cleanup_rejects_malformed_repo_names(tmp_path, repo_full_name) -> None:
    service = RepositoryWorkspaceService(run_label="2026-03-24", base_dir=tmp_path / "tmp-repos")
    path = tmp_path / "tmp-repos" / repo_full_name

    with pytest.raises(ValueError):
        service.cleanup_repo(ClonedWorkspace(repo_full_name=repo_full_name, path=path))


def test_workspace_cleanup_deletes_cloned_directory(tmp_path) -> None:
    source = init_local_git_repo(tmp_path / "source")
    service = RepositoryWorkspaceService(run_label="2026-03-24", base_dir=tmp_path / "tmp-repos")

    workspace = service.clone_repo(repo_full_name="acme/demo", repo_url=str(source))
    assert workspace.path.exists()

    service.cleanup_repo(workspace)

    assert not workspace.path.exists()


def test_workspace_cleanup_retries_transient_permission_error_then_succeeds(tmp_path, monkeypatch) -> None:
    source = init_local_git_repo(tmp_path / "source")
    service = RepositoryWorkspaceService(run_label="2026-03-24", base_dir=tmp_path / "tmp-repos")

    workspace = service.clone_repo(repo_full_name="acme/demo", repo_url=str(source))
    original_rmtree = repository_workspace_module.shutil.rmtree
    attempts: list[Path] = []
    sleeps: list[float] = []

    def flaky_rmtree(path, *args, **kwargs):  # noqa: ANN001, ANN002
        attempts.append(Path(path))
        if len(attempts) < 3:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(repository_workspace_module.shutil, "rmtree", flaky_rmtree)
    monkeypatch.setattr(repository_workspace_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    service.cleanup_repo(workspace)

    assert not workspace.path.exists()
    assert len(attempts) == 3
    assert sleeps


def test_clone_repo_retries_over_stale_workspace_without_cleanup(tmp_path) -> None:
    source = init_local_git_repo(tmp_path / "source")
    service = RepositoryWorkspaceService(run_label="2026-03-24", base_dir=tmp_path / "tmp-repos")

    first_workspace = service.clone_repo(repo_full_name="acme/demo", repo_url=str(source))
    second_workspace = service.clone_repo(repo_full_name="acme/demo", repo_url=str(source))

    assert second_workspace.path == first_workspace.path
    assert (second_workspace.path / "README.md").read_text(encoding="utf-8") == "demo repo\n"
    subprocess.run(["git", "-C", str(second_workspace.path), "rev-parse", "--is-inside-work-tree"], check=True)


def test_workspace_path_rejects_symlinked_owner_directory_across_runs(tmp_path) -> None:
    source = init_local_git_repo(tmp_path / "source")
    base_dir = tmp_path / "tmp-repos"
    current_run = RepositoryWorkspaceService(run_label="2026-03-24", base_dir=base_dir)
    other_run = RepositoryWorkspaceService(run_label="2026-03-25", base_dir=base_dir)

    other_workspace = other_run.clone_repo(repo_full_name="acme/demo", repo_url=str(source))
    symlink_path = current_run.workspace_root / "acme"
    symlink_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        os.symlink(other_workspace.path.parent, symlink_path, target_is_directory=True)
    except (AttributeError, NotImplementedError, OSError):
        pytest.skip("directory symlinks are not available")

    with pytest.raises(ValueError):
        current_run.workspace_path("acme/demo")


def test_cleanup_repo_uses_frozen_relative_base_dir_after_cwd_changes(tmp_path, monkeypatch) -> None:
    source = init_local_git_repo(tmp_path / "source")
    relative_base_dir = Path("tmp-repos")
    monkeypatch.chdir(tmp_path)
    service = RepositoryWorkspaceService(run_label="2026-03-24", base_dir=relative_base_dir)

    workspace = service.clone_repo(repo_full_name="acme/demo", repo_url=str(source))
    original_path = workspace.path
    assert original_path.exists()

    new_cwd = tmp_path / "other-cwd"
    new_cwd.mkdir()
    monkeypatch.chdir(new_cwd)

    service.cleanup_repo(workspace)

    assert not original_path.exists()


def test_workspace_service_uses_cached_relative_tmp_repo_dir_after_later_cwd_change(
    monkeypatch,
    tmp_path,
) -> None:
    first_cwd = tmp_path / "first-cwd"
    second_cwd = tmp_path / "second-cwd"
    first_cwd.mkdir()
    second_cwd.mkdir()
    monkeypatch.chdir(first_cwd)
    monkeypatch.setenv("TMP_REPO_DIR", "tmp-repos")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.tmp_repo_dir == (first_cwd / "tmp-repos").resolve()

        monkeypatch.chdir(second_cwd)
        service = RepositoryWorkspaceService(run_label="2026-03-24")

        assert service.base_dir == (first_cwd / "tmp-repos").resolve()
        assert service.workspace_root == (first_cwd / "tmp-repos" / "2026-03-24").resolve()
    finally:
        get_settings.cache_clear()


def test_clone_repo_rejects_same_run_symlink_aliasing(tmp_path) -> None:
    source = init_local_git_repo(tmp_path / "source")
    base_dir = tmp_path / "tmp-repos"
    service = RepositoryWorkspaceService(run_label="2026-03-24", base_dir=base_dir)

    aliased_owner_dir = service.workspace_root / "otherowner"
    aliased_owner_dir.mkdir(parents=True, exist_ok=True)

    symlink_path = service.workspace_root / "acme"
    symlink_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        os.symlink(aliased_owner_dir, symlink_path, target_is_directory=True)
    except (AttributeError, NotImplementedError, OSError):
        pytest.skip("directory symlinks are not available")

    with pytest.raises(ValueError):
        service.clone_repo(repo_full_name="acme/demo", repo_url=str(source))


def test_clone_repo_rejects_same_run_junction_aliasing(tmp_path) -> None:
    if os.name != "nt" or not hasattr(Path("x"), "is_junction"):
        pytest.skip("Windows junctions are not available")

    source = init_local_git_repo(tmp_path / "source")
    base_dir = tmp_path / "tmp-repos"
    service = RepositoryWorkspaceService(run_label="2026-03-24", base_dir=base_dir)

    target_dir = service.workspace_root / "otherowner" / "demo"
    target_dir.mkdir(parents=True, exist_ok=True)

    junction_path = service.workspace_root / "acme" / "demo"
    junction_path.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction_path), str(target_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not junction_path.is_junction():
        pytest.skip("Windows junction creation is not supported in this environment")

    with pytest.raises(ValueError):
        service.clone_repo(repo_full_name="acme/demo", repo_url=str(source))


def test_clone_repo_rejects_same_run_leaf_symlink_aliasing(tmp_path) -> None:
    source = init_local_git_repo(tmp_path / "source")
    base_dir = tmp_path / "tmp-repos"
    service = RepositoryWorkspaceService(run_label="2026-03-24", base_dir=base_dir)

    target_dir = service.workspace_root / "otherowner" / "demo"
    target_dir.mkdir(parents=True, exist_ok=True)

    leaf_alias = service.workspace_root / "acme" / "demo"
    leaf_alias.parent.mkdir(parents=True, exist_ok=True)

    try:
        os.symlink(target_dir, leaf_alias, target_is_directory=True)
    except (AttributeError, NotImplementedError, OSError):
        pytest.skip("directory symlinks are not available")

    with pytest.raises(ValueError):
        service.clone_repo(repo_full_name="acme/demo", repo_url=str(source))
