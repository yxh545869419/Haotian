from __future__ import annotations

from pathlib import Path

from haotian.services.codex_skill_inventory_service import CodexSkillInventoryService


def _write_skill(root: Path, slug: str, *, description: str = "") -> Path:
    skill_dir = root / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"# {slug}\n\n{description}", encoding="utf-8")
    return skill_dir


def test_codex_skill_inventory_scans_roots_in_precedence_order(tmp_path) -> None:
    managed = tmp_path / "managed"
    shared = tmp_path / "shared"
    managed_skill = _write_skill(managed, "seo-audit", description="Managed copy")
    _write_skill(shared, "seo-audit", description="Shared copy")
    browser_skill = _write_skill(shared, "browser-helper", description="Shared helper")

    inventory = CodexSkillInventoryService((managed, shared)).scan()

    assert list(inventory) == ["seo-audit", "browser-helper"]
    assert inventory["seo-audit"].source_root == managed.resolve()
    assert inventory["seo-audit"].skill_dir == managed_skill.resolve()
    assert inventory["seo-audit"].canonical_path == managed_skill.resolve()
    assert inventory["seo-audit"].display_name == "seo-audit"
    assert inventory["browser-helper"].source_root == shared.resolve()
    assert inventory["browser-helper"].skill_dir == browser_skill.resolve()


def test_codex_skill_inventory_uses_canonical_paths_and_skips_missing_roots(tmp_path) -> None:
    root = tmp_path / "roots" / ".." / "roots"
    skill_dir = _write_skill(root, "agent-designer", description="Nested skill")

    inventory = CodexSkillInventoryService((root, tmp_path / "missing")).scan()

    assert list(inventory) == ["agent-designer"]
    assert inventory["agent-designer"].source_root == (tmp_path / "roots").resolve()
    assert inventory["agent-designer"].skill_dir == skill_dir.resolve()
    assert inventory["agent-designer"].canonical_path == skill_dir.resolve()
