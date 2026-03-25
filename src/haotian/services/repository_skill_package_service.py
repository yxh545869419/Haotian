"""Deterministic discovery of installable skill packages inside a repository."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DiscoveredSkillPackage:
    skill_name: str
    package_root: Path
    relative_root: str
    files: tuple[str, ...]

    def to_serialized_payload(self) -> dict[str, object]:
        return {
            "skill_name": self.skill_name,
            "relative_root": self.relative_root,
            "files": list(self.files),
        }

    @classmethod
    def from_serialized_payload(cls, payload: dict[str, object]) -> "DiscoveredSkillPackage":
        relative_root = str(payload.get("relative_root", "")).strip()
        package_root = Path(".") if relative_root == "." else Path(relative_root)
        files_raw = payload.get("files", ())
        files = tuple(
            str(item).strip()
            for item in files_raw
            if item is not None and str(item).strip()
        )
        return cls(
            skill_name=str(payload.get("skill_name", "")).strip(),
            package_root=package_root,
            relative_root=relative_root,
            files=files,
        )


class RepositorySkillPackageService:
    """Find skill package manifests and inventory their local file sets."""

    def discover(self, repo_root: Path | str) -> tuple[DiscoveredSkillPackage, ...]:
        root = Path(repo_root)
        try:
            root = root.resolve(strict=True)
        except FileNotFoundError:
            return ()

        if not root.is_dir():
            return ()

        manifests = sorted(
            (path for path in root.rglob("SKILL.md") if path.is_file()),
            key=lambda path: self._sort_key(root, path),
        )
        package_roots = tuple(manifest.parent for manifest in manifests)
        packages = [
            DiscoveredSkillPackage(
                skill_name=self._skill_name(root, manifest.parent),
                package_root=manifest.parent,
                relative_root=self._relative_root(root, manifest.parent),
                files=self._inventory_files(manifest.parent, package_roots),
            )
            for manifest in manifests
        ]
        return tuple(packages)

    @staticmethod
    def _skill_name(root: Path, package_root: Path) -> str:
        if package_root == root:
            return root.name
        return package_root.name

    @staticmethod
    def _relative_root(root: Path, package_root: Path) -> str:
        if package_root == root:
            return "."
        return package_root.relative_to(root).as_posix()

    @staticmethod
    def _inventory_files(package_root: Path, package_roots: tuple[Path, ...]) -> tuple[str, ...]:
        files = sorted(
            path.relative_to(package_root).as_posix()
            for path in package_root.rglob("*")
            if path.is_file() and not RepositorySkillPackageService._is_nested_package_file(package_root, path, package_roots)
        )
        return tuple(files)

    @staticmethod
    def _is_nested_package_file(package_root: Path, path: Path, package_roots: tuple[Path, ...]) -> bool:
        if path.parent == package_root:
            return False
        return any(other_root != package_root and other_root in path.parents for other_root in package_roots)

    def _sort_key(self, root: Path, manifest: Path) -> tuple[int, str, str]:
        relative_root = self._relative_root(root, manifest.parent)
        skill_name = self._skill_name(root, manifest.parent)
        return (0 if relative_root == "." else 1, relative_root.casefold(), skill_name.casefold())
