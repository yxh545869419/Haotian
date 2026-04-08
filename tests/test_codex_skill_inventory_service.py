from __future__ import annotations

import json
import os
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest

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


def test_codex_skill_inventory_reads_frontmatter_name_and_description(tmp_path) -> None:
    root = tmp_path / "skills"
    skill_dir = root / "verification-before-completion"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: verification-before-completion\n"
        "description: Verify before claiming completion.\n"
        "---\n\n"
        "# Verification Before Completion\n",
        encoding="utf-8",
    )

    inventory = CodexSkillInventoryService((root,)).scan()

    assert inventory["verification-before-completion"].display_name == "verification-before-completion"
    assert inventory["verification-before-completion"].description == "Verify before claiming completion."


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


def test_codex_skill_inventory_skips_alias_children_without_descending(tmp_path, monkeypatch) -> None:
    root = tmp_path / "skills"
    group_dir = root / "collections"
    direct_skill = _write_skill(group_dir, "direct-skill", description="Direct skill")
    alias_child = group_dir / "alias-child"
    alias_nested = _write_skill(alias_child, "nested-skill", description="Nested alias skill")

    monkeypatch.setattr(
        CodexSkillInventoryService,
        "_is_alias_path",
        lambda path: path == alias_child,
    )

    inventory = CodexSkillInventoryService((root,)).scan()

    assert list(inventory) == ["direct-skill"]
    assert inventory["direct-skill"].skill_dir == direct_skill.resolve()
    assert alias_child.resolve() not in {record.skill_dir for record in inventory.values()}
    assert alias_nested.resolve() not in {record.skill_dir for record in inventory.values()}


def test_codex_skill_inventory_skips_windows_junction_children(tmp_path) -> None:
    if os.name != "nt" or not hasattr(Path("x"), "is_junction"):
        pytest.skip("Windows junctions are not available")

    root = tmp_path / "skills"
    group_dir = root / "collections"
    direct_skill = _write_skill(group_dir, "direct-skill", description="Direct skill")

    junction_target = tmp_path / "junction-target"
    junction_skill = _write_skill(junction_target, "junction-skill", description="Junction skill")
    junction_path = group_dir / "junction-child"
    junction_path.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction_path), str(junction_target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not junction_path.is_junction():
        pytest.skip("Windows junction creation is not supported in this environment")

    inventory = CodexSkillInventoryService((root,)).scan()

    assert list(inventory) == ["direct-skill"]
    assert inventory["direct-skill"].skill_dir == direct_skill.resolve()
    assert junction_path.resolve(strict=False) not in {record.skill_dir for record in inventory.values()}
    assert junction_skill.resolve() not in {record.skill_dir for record in inventory.values()}


def test_codex_skill_inventory_skips_windows_reparse_points_without_is_junction(tmp_path, monkeypatch) -> None:
    path_type = type(Path("x"))
    if os.name != "nt" or not hasattr(path_type, "is_junction"):
        pytest.skip("Path.is_junction fallback path is only relevant on Windows")

    root = tmp_path / "skills"
    group_dir = root / "collections"
    direct_skill = _write_skill(group_dir, "direct-skill", description="Direct skill")

    junction_target = tmp_path / "junction-target"
    junction_skill = _write_skill(junction_target, "junction-skill", description="Junction skill")
    junction_path = group_dir / "junction-child"
    junction_path.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction_path), str(junction_target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not junction_path.is_junction():
        pytest.skip("Windows junction creation is not supported in this environment")

    monkeypatch.setattr(path_type, "is_junction", None, raising=False)

    inventory = CodexSkillInventoryService((root,)).scan()

    assert list(inventory) == ["direct-skill"]
    assert inventory["direct-skill"].skill_dir == direct_skill.resolve()
    assert junction_path.resolve(strict=False) not in {record.skill_dir for record in inventory.values()}
    assert junction_skill.resolve() not in {record.skill_dir for record in inventory.values()}


def test_codex_skill_inventory_skips_windows_junction_roots(tmp_path) -> None:
    if os.name != "nt" or not hasattr(Path("x"), "is_junction"):
        pytest.skip("Windows junctions are not available")

    junction_target = tmp_path / "junction-target"
    target_skill = _write_skill(junction_target, "external-skill", description="External skill")
    junction_root = tmp_path / "junction-root"

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction_root), str(junction_target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not junction_root.is_junction():
        pytest.skip("Windows junction creation is not supported in this environment")

    inventory = CodexSkillInventoryService((junction_root,)).scan()

    assert inventory == {}
    assert target_skill.resolve() not in {record.skill_dir for record in inventory.values()}


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
