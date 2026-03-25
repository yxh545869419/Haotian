"""Deterministic inventory of locally installed Codex skill packages."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable
from pathlib import Path
import os

from haotian.config import get_settings


@dataclass(frozen=True, slots=True)
class InstalledSkillRecord:
    """Canonical metadata for one discovered local skill package."""

    slug: str
    source_root: Path
    skill_dir: Path
    canonical_path: Path
    display_name: str
    relative_path: str
    root_index: int
    managed: bool


class CodexSkillInventoryService:
    """Scan configured skill roots and return the first canonical record per slug."""

    def __init__(
        self,
        skill_roots: Iterable[Path | str] | None = None,
        *,
        managed_root: Path | str | None = None,
    ) -> None:
        settings = get_settings()
        if managed_root is None:
            managed_root = settings.codex_managed_skill_root
        if skill_roots is None:
            skill_roots = settings.codex_skill_roots
            ordered_roots: list[Path | str] = []
            if managed_root is not None:
                ordered_roots.append(managed_root)
            ordered_roots.extend(skill_roots)
        else:
            ordered_roots = list(skill_roots)

        self.skill_roots = tuple(Path(root) for root in ordered_roots)
        self.managed_root = Path(managed_root).resolve(strict=False) if managed_root is not None else None

    def scan(self) -> dict[str, InstalledSkillRecord]:
        inventory: dict[str, InstalledSkillRecord] = {}

        for root_index, root in enumerate(self.skill_roots):
            resolved_root = root.resolve(strict=False)
            if not resolved_root.exists() or not resolved_root.is_dir():
                continue

            managed = self.managed_root is not None and resolved_root == self.managed_root
            for skill_dir in self._discover_skill_dirs(resolved_root):
                slug = self._slug_for_skill_dir(skill_dir)
                if slug in inventory:
                    continue
                inventory[slug] = InstalledSkillRecord(
                    slug=slug,
                    source_root=resolved_root,
                    skill_dir=skill_dir.resolve(strict=False),
                    canonical_path=skill_dir.resolve(strict=False),
                    display_name=self._display_name(skill_dir, slug),
                    relative_path=self._relative_path(resolved_root, skill_dir),
                    root_index=root_index,
                    managed=managed,
                )

        return inventory

    @staticmethod
    def _discover_skill_dirs(root: Path) -> tuple[Path, ...]:
        candidates: list[Path] = []
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            dirs[:] = [name for name in dirs if not (current_path / name).is_symlink()]
            if "SKILL.md" in files:
                candidates.append(current_path)

        candidates.sort(key=lambda path: (0 if path == root else 1, path.relative_to(root).as_posix().casefold()))
        return tuple(candidates)

    @staticmethod
    def _slug_for_skill_dir(skill_dir: Path) -> str:
        return skill_dir.name.strip()

    @staticmethod
    def _relative_path(root: Path, skill_dir: Path) -> str:
        if skill_dir == root:
            return "."
        return skill_dir.relative_to(root).as_posix()

    @staticmethod
    def _display_name(skill_dir: Path, fallback_slug: str) -> str:
        manifest = skill_dir / "SKILL.md"
        try:
            content = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return fallback_slug

        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                candidate = stripped.lstrip("#").strip()
                if candidate:
                    return candidate
            if stripped:
                break
        return fallback_slug
