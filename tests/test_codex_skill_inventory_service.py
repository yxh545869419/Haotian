from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

from haotian.services.codex_skill_inventory_service import CodexSkillInventoryService


def _write_skill(
    root: Path,
    slug: str,
    *,
    description: str = "",
    managed_wrapper: dict[str, object] | None = None,
) -> Path:
    skill_dir = root / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"# {slug}\n\n{description}", encoding="utf-8")
    if managed_wrapper is not None:
        (skill_dir / "haotian-wrapper.json").write_text(
            json.dumps(managed_wrapper, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
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


def test_codex_skill_inventory_preserves_explicit_root_order(tmp_path) -> None:
    managed = tmp_path / "managed"
    shared = tmp_path / "shared"
    _write_skill(managed, "seo-audit", description="Managed copy")
    shared_skill = _write_skill(shared, "seo-audit", description="Shared copy")
    helper_skill = _write_skill(managed, "browser-helper", description="Managed helper")

    inventory = CodexSkillInventoryService((shared, managed), managed_root=managed).scan()

    assert list(inventory) == ["seo-audit", "browser-helper"]
    assert inventory["seo-audit"].source_root == shared.resolve()
    assert inventory["seo-audit"].skill_dir == shared_skill.resolve()
    assert inventory["seo-audit"].managed is False
    assert inventory["browser-helper"].source_root == managed.resolve()
    assert inventory["browser-helper"].skill_dir == helper_skill.resolve()
    assert inventory["browser-helper"].managed is True


def test_codex_skill_inventory_uses_canonical_paths_and_skips_missing_roots(tmp_path) -> None:
    root = tmp_path / "roots" / ".." / "roots"
    skill_dir = _write_skill(root, "agent-designer", description="Nested skill")

    inventory = CodexSkillInventoryService((root, tmp_path / "missing")).scan()

    assert list(inventory) == ["agent-designer"]
    assert inventory["agent-designer"].source_root == (tmp_path / "roots").resolve()
    assert inventory["agent-designer"].skill_dir == skill_dir.resolve()
    assert inventory["agent-designer"].canonical_path == skill_dir.resolve()


def test_codex_skill_inventory_uses_configured_managed_root_when_roots_omitted(
    monkeypatch, tmp_path
) -> None:
    managed = tmp_path / "managed"
    shared = tmp_path / "shared"
    managed_skill = _write_skill(managed, "seo-audit", description="Managed copy")
    _write_skill(shared, "seo-audit", description="Shared copy")
    helper_skill = _write_skill(shared, "browser-helper", description="Shared helper")

    fake_settings = SimpleNamespace(
        codex_skill_roots=(shared,),
        codex_managed_skill_root=managed,
    )
    monkeypatch.setattr(
        "haotian.services.codex_skill_inventory_service.get_settings",
        lambda: fake_settings,
    )

    inventory = CodexSkillInventoryService().scan()

    assert list(inventory) == ["seo-audit", "browser-helper"]
    assert inventory["seo-audit"].source_root == managed.resolve()
    assert inventory["seo-audit"].skill_dir == managed_skill.resolve()
    assert inventory["seo-audit"].managed is True
    assert inventory["browser-helper"].source_root == shared.resolve()
    assert inventory["browser-helper"].skill_dir == helper_skill.resolve()
    assert inventory["browser-helper"].managed is False


def test_codex_skill_inventory_stops_at_first_skill_boundary(tmp_path) -> None:
    root = tmp_path / "skills"
    parent = _write_skill(root, "parent-skill", description="Parent skill")
    nested = _write_skill(parent, "nested-skill", description="Nested skill")

    inventory = CodexSkillInventoryService((root,)).scan()

    assert list(inventory) == ["parent-skill"]
    assert inventory["parent-skill"].skill_dir == parent.resolve()
    assert nested.resolve() not in {record.skill_dir for record in inventory.values()}


def test_codex_skill_inventory_reads_managed_wrapper_metadata(tmp_path) -> None:
    managed = tmp_path / "managed"
    _write_skill(
        managed,
        "acme-browser-bot",
        description="Managed wrapper",
        managed_wrapper={
            "schema_version": 1,
            "managed_by": "haotian",
            "slug": "browser-bot",
            "display_name": "Browser Bot",
            "source_repo_full_name": "acme/browser-bot",
            "relative_root": ".",
        },
    )

    inventory = CodexSkillInventoryService((managed,), managed_root=managed).scan()

    assert inventory["acme-browser-bot"].managed is True
    assert inventory["acme-browser-bot"].managed_wrapper_slug == "browser-bot"
    assert inventory["acme-browser-bot"].managed_source_repo_full_name == "acme/browser-bot"
    assert inventory["acme-browser-bot"].managed_relative_root == "."


def test_codex_skill_inventory_ignores_invalid_managed_wrapper_slug(tmp_path) -> None:
    managed = tmp_path / "managed"
    _write_skill(
        managed,
        "acme-browser-bot",
        description="Managed wrapper",
        managed_wrapper={
            "schema_version": 1,
            "managed_by": "haotian",
            "slug": "../browser-bot",
            "display_name": "Browser Bot",
            "source_repo_full_name": "acme/browser-bot",
            "relative_root": ".",
        },
    )

    inventory = CodexSkillInventoryService((managed,), managed_root=managed).scan()

    assert inventory["acme-browser-bot"].managed_wrapper_slug is None
    assert inventory["acme-browser-bot"].aliases == ()
