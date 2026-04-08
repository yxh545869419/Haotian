from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path
import subprocess

import pytest

from haotian.services.codex_skill_inventory_service import InstalledSkillRecord
from haotian.services.skill_sync_service import SkillSyncCandidate, SkillSyncService


@dataclass
class FakeAuditResult:
    status: str
    overall_verdict: str
    installable: bool

    def is_installable(self) -> bool:
        return self.installable


class FakeAuditService:
    def __init__(self, result: FakeAuditResult) -> None:
        self.result = result
        self.calls: list[Path] = []

    def audit(self, target: Path | str) -> FakeAuditResult:
        self.calls.append(Path(target))
        return self.result


def _candidate(
    slug: str,
    *,
    display_name: str | None = None,
    source_repo_full_name: str = "acme/skill-repo",
    repo_url: str = "https://github.com/acme/skill-repo",
    relative_root: str = ".",
    files: tuple[str, ...] = ("SKILL.md", "AGENTS.md"),
    source_package_root: Path | None = None,
    description: str = "Codex skill package for browser automation workflows.",
    matched_keywords: tuple[str, ...] = ("SKILL.md", "AGENTS.md"),
    architecture_signals: tuple[str, ...] = ("codex-skill-package",),
    install_scope: str = "skill",
) -> SkillSyncCandidate:
    return SkillSyncCandidate(
        slug=slug,
        display_name=display_name or slug,
        source_repo_full_name=source_repo_full_name,
        repo_url=repo_url,
        relative_root=relative_root,
        files=files,
        source_package_root=source_package_root,
        description=description,
        matched_keywords=matched_keywords,
        architecture_signals=architecture_signals,
        capability_ids=("browser_automation",),
        install_scope=install_scope,
    )


def _source_package_root(tmp_path: Path, slug: str) -> Path:
    root = tmp_path / "source" / slug
    (root / "references").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "nested" / "docs").mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(f"# {slug}\n\nPrimary instructions.\n", encoding="utf-8")
    (root / "README.md").write_text("Package README.\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("Agent notes.\n", encoding="utf-8")
    (root / "codex.md").write_text("Codex notes.\n", encoding="utf-8")
    (root / "settings.json").write_text("{\"ok\": true}\n", encoding="utf-8")
    (root / "references" / "guide.md").write_text("Reference guide.\n", encoding="utf-8")
    (root / "scripts" / "run.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "nested" / "docs" / "more.md").write_text("Nested docs.\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (root / "__pycache__").mkdir(parents=True, exist_ok=True)
    (root / "__pycache__" / "bad.pyc").write_bytes(b"0")
    (root / "vendor").mkdir(parents=True, exist_ok=True)
    (root / "vendor" / "dependency.py").write_text("print('vendor')\n", encoding="utf-8")
    (root / "package-lock.json").write_text("{}\n", encoding="utf-8")
    return root


def _installed(
    root: Path,
    slug: str,
    *,
    display_name: str | None = None,
    description: str = "Installed local skill.",
    managed: bool = False,
    source_repo_full_name: str | None = None,
    relative_root: str = ".",
    wrapper_slug: str | None = None,
    root_index: int = 0,
    full_package: bool = False,
    install_scope: str = "skill",
) -> InstalledSkillRecord:
    skill_dir = root / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"# {display_name or slug}\n", encoding="utf-8")
    if managed and source_repo_full_name:
        if full_package:
            (skill_dir / "README.md").write_text("Package README.\n", encoding="utf-8")
            (skill_dir / "AGENTS.md").write_text("Agent notes.\n", encoding="utf-8")
            (skill_dir / "references").mkdir(parents=True, exist_ok=True)
            (skill_dir / "references" / "guide.md").write_text("Reference guide.\n", encoding="utf-8")
        (skill_dir / "haotian-wrapper.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "managed_by": "haotian",
                    "slug": wrapper_slug or slug,
                    "display_name": display_name or slug,
                    "source_repo_full_name": source_repo_full_name,
                    "relative_root": relative_root,
                    "install_scope": install_scope,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return InstalledSkillRecord(
        slug=slug,
        source_root=root.resolve(),
        skill_dir=skill_dir.resolve(),
        canonical_path=skill_dir.resolve(),
        display_name=display_name or slug,
        description=description,
        relative_path=slug,
        root_index=root_index,
        managed=managed,
        aliases=((wrapper_slug or slug),) if managed and (wrapper_slug or slug) != slug else (),
        managed_source_repo_full_name=source_repo_full_name if managed else None,
        managed_wrapper_slug=(wrapper_slug or slug) if managed else None,
        managed_relative_root=relative_root if managed else None,
        managed_install_scope=install_scope if managed else None,
    )


def test_skill_sync_aligns_existing_skill_without_rewriting_it(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    existing = _installed(
        managed_root,
        "browser-bot",
        managed=True,
        source_repo_full_name="acme/skill-repo",
        full_package=True,
    )
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("browser-bot", display_name="Browser Bot")],
        inventory={"browser-bot": existing},
    )

    assert result.actions[0].action == "aligned_existing"
    assert result.actions[0].matched_installed_slug == "browser-bot"
    assert audit_service.calls == [existing.skill_dir]
    assert result.summary["aligned_existing"] == 1


def test_skill_sync_installs_new_audit_safe_skill_atomically(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    source_root = _source_package_root(tmp_path, "agent-designer")

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate(
                "agent-designer",
                display_name="Agent Designer",
                relative_root="skills/agent-designer",
                source_package_root=source_root,
                files=("SKILL.md", "README.md", "AGENTS.md", "codex.md", "settings.json", "references/guide.md", "scripts/run.py"),
            )
        ],
        inventory={},
    )

    assert result.actions[0].action == "installed_new"
    installed_root = Path(result.actions[0].installed_path or "")
    assert installed_root.joinpath("SKILL.md").exists()
    assert installed_root.joinpath("haotian-wrapper.json").exists()
    assert installed_root.joinpath("README.md").exists()
    assert installed_root.joinpath("AGENTS.md").exists()
    assert installed_root.joinpath("references", "guide.md").exists()
    assert installed_root.joinpath("scripts", "run.py").exists()
    assert not installed_root.joinpath(".env").exists()
    assert not installed_root.joinpath("package-lock.json").exists()
    assert not installed_root.joinpath("vendor").exists()
    assert len(audit_service.calls) == 1
    assert audit_service.calls[0].name.startswith(f".haotian-stage-{result.actions[0].slug}")
    assert list(managed_root.parent.glob(".haotian-stage-*")) == []
    assert result.summary["installed_new"] == 1


def test_skill_sync_installs_collection_repo_with_canonical_slug_and_prunes_split_duplicate(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    collection_root = tmp_path / "collections"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, collection_root=collection_root, audit_service=audit_service)
    old_split = _installed(
        managed_root,
        "affaan-m-everything-claude-code-agent-eval-8cc1f6560e",
        display_name="agent-eval",
        managed=True,
        source_repo_full_name="affaan-m/everything-claude-code",
        relative_root="skills/agent-eval",
        wrapper_slug="agent-eval",
        full_package=True,
    )
    candidates = []
    for index in range(8):
        slug = "agent-eval" if index == 0 else f"skill-{index}"
        candidates.append(
            _candidate(
                slug,
                display_name=slug,
                source_repo_full_name="affaan-m/everything-claude-code",
                relative_root=f"skills/{slug}",
                source_package_root=_source_package_root(tmp_path, slug),
            )
        )

    result = service.sync(report_date=date(2026, 4, 8), candidates=candidates, inventory={old_split.slug: old_split})
    actions = {action.display_name: action for action in result.actions}
    agent_eval = actions["agent-eval"]

    assert agent_eval.action == "installed_new"
    assert agent_eval.slug == "agent-eval"
    assert "legacy split managed duplicate" in agent_eval.reason
    assert not old_split.skill_dir.exists()
    assert Path(agent_eval.installed_path or "").name == "agent-eval"
    assert (collection_root / "affaan-m-everything-claude-code" / "skills" / "agent-eval" / "SKILL.md").exists()
    metadata = json.loads(Path(agent_eval.installed_path or "", "haotian-wrapper.json").read_text(encoding="utf-8"))
    assert metadata["install_scope"] == "collection"


def test_skill_sync_allows_cross_collection_slug_dedupe(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    collection_root = tmp_path / "collections"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, collection_root=collection_root, audit_service=audit_service)
    candidates = []
    for repo in ("alpha/skills", "bravo/skills"):
        for index in range(8):
            slug = "tdd" if index == 0 else f"{repo.split('/')[0]}-{index}"
            candidates.append(
                _candidate(
                    slug,
                    display_name=slug,
                    source_repo_full_name=repo,
                    relative_root=f"skills/{slug}",
                    source_package_root=_source_package_root(tmp_path, f"{repo.replace('/', '-')}-{slug}"),
                )
            )

    result = service.sync(report_date=date(2026, 4, 8), candidates=candidates, inventory={})
    tdd_actions = [action for action in result.actions if action.display_name == "tdd"]

    assert [action.action for action in tdd_actions] == ["installed_new", "aligned_existing"]
    assert tdd_actions[0].slug == "tdd"
    assert tdd_actions[1].matched_installed_slug == "tdd"


def test_skill_sync_refuses_wrapper_only_candidate_without_source_package_root(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("wrapper-only", display_name="Wrapper Only")],
        inventory={},
    )

    assert result.actions[0].action == "blocked_audit_failure"
    assert "source package root" in result.actions[0].reason.casefold()
    assert audit_service.calls == []


def test_skill_sync_replaces_legacy_wrapper_only_install_with_full_package(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    legacy = _installed(
        managed_root,
        "browser-bot",
        display_name="Browser Bot",
        managed=True,
        source_repo_full_name="acme/browser-bot",
        wrapper_slug="browser-bot",
    )
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    source_root = _source_package_root(tmp_path, "browser-bot")

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate(
                "browser-bot",
                display_name="Browser Bot",
                source_repo_full_name="acme/browser-bot",
                source_package_root=source_root,
                files=("SKILL.md", "README.md", "AGENTS.md", "references/guide.md"),
            )
        ],
        inventory={"browser-bot": legacy},
    )

    installed_root = Path(result.actions[0].installed_path or "")
    assert result.actions[0].action == "installed_new"
    assert not service._is_wrapper_only_install(legacy.skill_dir)
    assert installed_root.joinpath("README.md").exists()
    assert installed_root.joinpath("references", "guide.md").exists()
    assert installed_root.joinpath("haotian-wrapper.json").exists()
    assert audit_service.calls and audit_service.calls[0].name.startswith(".haotian-stage-")


def test_skill_sync_rolls_back_when_directory_replace_fails(tmp_path, monkeypatch) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    source_root = _source_package_root(tmp_path, "agent-designer")

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002, ARG001
        raise RuntimeError("replace failed")

    monkeypatch.setattr(service, "_replace_directory", boom)

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate(
                "agent-designer",
                display_name="Agent Designer",
                relative_root="skills/agent-designer",
                source_package_root=source_root,
            )
        ],
        inventory={},
    )

    assert result.actions[0].action == "rolled_back_install_failure"
    assert list(managed_root.glob("agent-designer")) == []
    assert list(managed_root.parent.glob(".haotian-stage-*")) == []


def test_skill_sync_discards_non_integrable_candidate(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("docs-only", files=("README.md",))],
        inventory={},
    )

    assert result.actions[0].action == "discarded_non_integrable"
    assert audit_service.calls == []


def test_skill_sync_discards_lone_skill_manifest_without_support_files_or_runtime_signal(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate(
                "manifest-only",
                files=("SKILL.md",),
                matched_keywords=("SKILL.md",),
                architecture_signals=(),
            )
        ],
        inventory={},
    )

    assert result.actions[0].action == "discarded_non_integrable"
    assert audit_service.calls == []


def test_skill_sync_installs_lone_skill_manifest_when_full_source_package_exists(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    source_root = tmp_path / "source" / "manifest-only"
    source_root.mkdir(parents=True)
    source_root.joinpath("SKILL.md").write_text("# Manifest Only\n\nUseful instructions.\n", encoding="utf-8")

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate(
                "manifest-only",
                files=("SKILL.md",),
                source_package_root=source_root,
                relative_root="skills/manifest-only",
                matched_keywords=("SKILL.md",),
                architecture_signals=("codex-skill-package",),
            )
        ],
        inventory={},
    )

    assert result.actions[0].action == "installed_new"
    assert result.actions[0].installed_path is not None
    installed_path = Path(result.actions[0].installed_path)
    assert installed_path.joinpath("SKILL.md").exists()
    assert not service._is_wrapper_only_install(installed_path)
    assert len(audit_service.calls) == 1


def test_skill_sync_accepts_manifest_with_readme_and_settings_as_supporting_evidence(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    source_root = _source_package_root(tmp_path, "a11y-audit")

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate(
                "a11y-audit",
                files=("README.md", "SKILL.md", "settings.json"),
                source_package_root=source_root,
                matched_keywords=(),
                architecture_signals=(),
                relative_root="engineering-team/a11y-audit",
            )
        ],
        inventory={},
    )

    assert result.actions[0].action == "installed_new"
    assert len(audit_service.calls) == 1


def test_skill_sync_blocks_failed_audit(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="block", overall_verdict="BLOCK", installable=False))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    source_root = _source_package_root(tmp_path, "research-briefs")

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("research-briefs", source_package_root=source_root)],
        inventory={},
    )

    assert result.actions[0].action == "blocked_audit_failure"
    assert not (managed_root / "research-briefs").exists()
    assert len(audit_service.calls) == 1
    assert list(managed_root.parent.glob(".haotian-stage-*")) == []


def test_skill_sync_prefers_canonical_match_over_alias_match(tmp_path) -> None:
    shared_root = tmp_path / "shared"
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)

    inventory = {
        "browser-bot": _installed(
            shared_root,
            "browser-bot",
            display_name="Browser Bot",
            managed=False,
        ),
        "managed-wrapper": _installed(
            managed_root,
            "managed-wrapper",
            display_name="Managed Wrapper",
            managed=True,
            source_repo_full_name="acme/skill-repo",
            wrapper_slug="browser-bot",
        ),
    }

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("browser-bot", display_name="Browser Bot")],
        inventory=inventory,
    )

    assert result.actions[0].action == "aligned_existing"
    assert result.actions[0].matched_installed_slug == "browser-bot"
    assert audit_service.calls == [inventory["browser-bot"].skill_dir]


def test_skill_sync_installs_distinct_wrappers_for_same_skill_name_from_different_repos(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    acme_root = _source_package_root(tmp_path, "acme-browser-bot")
    contoso_root = _source_package_root(tmp_path, "contoso-browser-bot")

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate("browser-bot", source_repo_full_name="acme/browser-bot", source_package_root=acme_root),
            _candidate("browser-bot", source_repo_full_name="contoso/browser-bot", source_package_root=contoso_root),
        ],
        inventory={},
    )

    assert [action.action for action in result.actions] == ["installed_new", "installed_new"]
    assert len({action.slug for action in result.actions}) == 2
    assert result.actions[0].slug.startswith("acme-browser-bot")
    assert result.actions[1].slug.startswith("contoso-browser-bot")
    assert Path(result.actions[0].installed_path or "").joinpath("SKILL.md").exists()
    assert Path(result.actions[1].installed_path or "").joinpath("SKILL.md").exists()


def test_skill_sync_install_slug_is_collision_safe_for_similar_repo_names(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    acme_root = _source_package_root(tmp_path, "acme-browser-bot")
    bot_root = _source_package_root(tmp_path, "acme-browser-bot-alt")

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate("browser-bot", source_repo_full_name="acme/browser-bot", source_package_root=acme_root),
            _candidate("bot", source_repo_full_name="acme-browser/bot", source_package_root=bot_root),
        ],
        inventory={},
    )

    assert [action.action for action in result.actions] == ["installed_new", "installed_new"]
    assert len({action.slug for action in result.actions}) == 2
    assert all(action.slug.startswith("acme-browser-bot") for action in result.actions)
    assert all(Path(action.installed_path or "").joinpath("SKILL.md").exists() for action in result.actions)


def test_skill_sync_similarity_uses_root_precedence_tiebreaker(tmp_path) -> None:
    shared_root = tmp_path / "shared"
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)

    inventory = {
        "browser-helper-pro-v1": _installed(
            shared_root,
            "browser-helper-pro-v1",
            display_name="Browser Helper Pro V1",
            description="Codex skill package for browser automation workflows.",
            root_index=0,
        ),
        "browser-helper-pro-v2": _installed(
            shared_root,
            "browser-helper-pro-v2",
            display_name="Browser Helper Pro V2",
            description="Codex skill package for browser automation workflows.",
            root_index=1,
        ),
    }

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
                _candidate(
                    "browser-helper-pro",
                    display_name="Browser Helper Pro",
                    description="Codex skill package for browser automation workflows.",
                    matched_keywords=(),
                )
            ],
            inventory=inventory,
        )

    assert result.actions[0].action == "aligned_existing"
    assert result.actions[0].matched_installed_slug == "browser-helper-pro-v1"
    assert audit_service.calls == [inventory["browser-helper-pro-v1"].skill_dir]


def test_skill_sync_similarity_prefers_name_overlap_over_root_precedence(tmp_path) -> None:
    shared_root = tmp_path / "shared"
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)

    inventory = {
        "seo-audit": _installed(
            shared_root,
            "seo-audit",
            display_name="SEO Audit",
            description="Codex skill package for browser automation workflows.",
            root_index=0,
        ),
        "browser-helper-pro": _installed(
            shared_root,
            "browser-helper-pro-v2",
            display_name="Browser Helper Pro V2",
            description="Codex skill package for browser automation workflows.",
            root_index=1,
        ),
    }

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate(
                "browser-helper-pro",
                display_name="Browser Helper Pro",
                description="Codex skill package for browser automation workflows.",
                matched_keywords=(),
            )
        ],
        inventory=inventory,
    )

    assert result.actions[0].action == "aligned_existing"
    assert result.actions[0].matched_installed_slug == "browser-helper-pro-v2"
    assert audit_service.calls == [inventory["browser-helper-pro"].skill_dir]


def test_skill_sync_aligns_audited_unmanaged_exact_name_match(tmp_path) -> None:
    shared_root = tmp_path / "shared"
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    existing = _installed(shared_root, "browser-bot", display_name="Browser Bot", managed=False)

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("browser-bot", display_name="Browser Bot", source_repo_full_name="acme/browser-bot")],
        inventory={"browser-bot": existing},
    )

    assert result.actions[0].action == "aligned_existing"
    assert result.actions[0].matched_installed_slug == "browser-bot"
    assert audit_service.calls == [existing.skill_dir]


def test_skill_sync_prefers_skill_creator_for_write_a_skill_alias(tmp_path) -> None:
    shared_root = tmp_path / "shared" / ".system"
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    skill_creator = _installed(
        shared_root,
        "skill-creator",
        display_name="skill-creator",
        managed=False,
    )
    managed_write_a_skill = _installed(
        managed_root,
        "mattpocock-skills-write-a-skill-5ca242852c",
        display_name="write-a-skill",
        managed=True,
        source_repo_full_name="mattpocock/skills",
        relative_root="write-a-skill",
        wrapper_slug="write-a-skill",
        full_package=True,
    )

    result = service.sync(
        report_date=date(2026, 4, 8),
        candidates=[
            _candidate(
                "write-a-skill",
                display_name="write-a-skill",
                source_repo_full_name="mattpocock/skills",
                relative_root="write-a-skill",
                source_package_root=managed_write_a_skill.skill_dir,
                description="Create new agent skills with proper structure.",
            )
        ],
        inventory={
            "skill-creator": skill_creator,
            "mattpocock-skills-write-a-skill-5ca242852c": managed_write_a_skill,
        },
    )

    assert result.actions[0].action == "aligned_existing"
    assert result.actions[0].matched_installed_slug == "skill-creator"
    assert result.actions[0].audit_status == "trusted"
    assert "Removed 1 redundant managed duplicate" in result.actions[0].reason
    assert not managed_write_a_skill.skill_dir.exists()
    assert audit_service.calls == []


def test_skill_sync_does_not_merge_writer_memory_into_skill_creator(tmp_path) -> None:
    shared_root = tmp_path / "shared"
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    source_root = _source_package_root(tmp_path, "writer-memory")

    result = service.sync(
        report_date=date(2026, 4, 8),
        candidates=[
            _candidate(
                "writer-memory",
                display_name="writer-memory",
                source_repo_full_name="yeachan-heo/oh-my-claudecode",
                relative_root="writer-memory",
                source_package_root=source_root,
                description="Agentic memory system for writers.",
            )
        ],
        inventory={
            "skill-creator": _installed(
                shared_root,
                "skill-creator",
                display_name="skill-creator",
                managed=False,
            )
        },
    )

    assert result.actions[0].action == "installed_new"
    assert result.actions[0].matched_installed_slug is None


def test_skill_sync_does_not_align_unmanaged_fuzzy_match(tmp_path) -> None:
    shared_root = tmp_path / "shared"
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    source_root = _source_package_root(tmp_path, "browser-bot")

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate(
                "browser-bot",
                display_name="Browser Bot",
                source_repo_full_name="acme/browser-bot",
                source_package_root=source_root,
            )
        ],
        inventory={"browser-buddy": _installed(shared_root, "browser-buddy", display_name="Browser Buddy", managed=False)},
    )

    assert result.actions[0].action == "installed_new"
    assert result.actions[0].matched_installed_slug is None
    assert Path(result.actions[0].installed_path or "").joinpath("SKILL.md").exists()


def test_skill_sync_blocks_alignment_when_existing_local_skill_fails_audit(tmp_path) -> None:
    shared_root = tmp_path / "shared"
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="block", overall_verdict="BLOCK", installable=False))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    existing = _installed(shared_root, "browser-bot", display_name="Browser Bot", managed=False)

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("browser-bot", display_name="Browser Bot", source_repo_full_name="acme/browser-bot")],
        inventory={"browser-bot": existing},
    )

    assert result.actions[0].action == "blocked_audit_failure"
    assert result.actions[0].matched_installed_slug == "browser-bot"
    assert audit_service.calls == [existing.skill_dir]


def test_skill_sync_does_not_align_managed_wrapper_from_different_repo_identity(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    source_root = _source_package_root(tmp_path, "browser-bot")

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate(
                "browser-bot",
                display_name="Browser Bot",
                source_repo_full_name="acme-browser/bot",
                source_package_root=source_root,
            )
        ],
        inventory={
            "acme-browser-bot-existing": _installed(
                managed_root,
                "acme-browser-bot-existing",
                display_name="Browser Bot",
                managed=True,
                source_repo_full_name="acme/browser-bot",
                wrapper_slug="browser-bot",
            )
        },
    )

    assert result.actions[0].action == "installed_new"
    assert result.actions[0].matched_installed_slug is None
    assert Path(result.actions[0].installed_path or "").joinpath("SKILL.md").exists()


def test_skill_sync_does_not_align_managed_wrapper_from_different_relative_root(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    source_root = _source_package_root(tmp_path, "browser-bot")

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate(
                "browser-bot",
                display_name="Browser Bot",
                source_repo_full_name="acme/browser-bot",
                relative_root="skills-browser/bot",
                source_package_root=source_root,
            )
        ],
        inventory={
            "acme-browser-bot-existing": _installed(
                managed_root,
                "acme-browser-bot-existing",
                display_name="Browser Bot",
                managed=True,
                source_repo_full_name="acme/browser-bot",
                relative_root="skills/browser-bot",
                wrapper_slug="browser-bot",
            )
        },
    )

    assert result.actions[0].action == "installed_new"
    assert result.actions[0].matched_installed_slug is None
    assert Path(result.actions[0].installed_path or "").joinpath("SKILL.md").exists()


def test_skill_sync_does_not_align_managed_wrapper_with_missing_identity_metadata(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)

    inventory = {
        "managed-wrapper": InstalledSkillRecord(
            slug="managed-wrapper",
            source_root=managed_root.resolve(),
            skill_dir=(managed_root / "managed-wrapper"),
            canonical_path=(managed_root / "managed-wrapper"),
            display_name="Managed Wrapper",
            description="Codex skill package for browser automation workflows.",
            relative_path="managed-wrapper",
            root_index=0,
            managed=True,
            aliases=("browser-bot",),
            managed_source_repo_full_name=None,
            managed_wrapper_slug="browser-bot",
            managed_relative_root=None,
        )
    }
    inventory["managed-wrapper"].skill_dir.mkdir(parents=True, exist_ok=True)
    inventory["managed-wrapper"].skill_dir.joinpath("SKILL.md").write_text("# Managed Wrapper\n", encoding="utf-8")
    source_root = _source_package_root(tmp_path, "browser-bot")

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate(
                "browser-bot",
                display_name="Browser Bot",
                source_repo_full_name="other/repo",
                source_package_root=source_root,
            )
        ],
        inventory=inventory,
    )

    assert result.actions[0].action == "installed_new"
    assert result.actions[0].matched_installed_slug is None
    assert Path(result.actions[0].installed_path or "").joinpath("SKILL.md").exists()


def test_skill_sync_does_not_align_managed_wrapper_with_malformed_wrapper_slug(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)

    inventory = {
        "managed-wrapper": InstalledSkillRecord(
            slug="managed-wrapper",
            source_root=managed_root.resolve(),
            skill_dir=(managed_root / "managed-wrapper"),
            canonical_path=(managed_root / "managed-wrapper"),
            display_name="Managed Wrapper",
            description="Codex skill package for browser automation workflows.",
            relative_path="managed-wrapper",
            root_index=0,
            managed=True,
            aliases=("../browser-bot",),
            managed_source_repo_full_name="other/repo",
            managed_wrapper_slug="../browser-bot",
            managed_relative_root=".",
        )
    }
    inventory["managed-wrapper"].skill_dir.mkdir(parents=True, exist_ok=True)
    inventory["managed-wrapper"].skill_dir.joinpath("SKILL.md").write_text("# Managed Wrapper\n", encoding="utf-8")
    source_root = _source_package_root(tmp_path, "browser-bot")

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate(
                "browser-bot",
                display_name="Browser Bot",
                source_repo_full_name="other/repo",
                source_package_root=source_root,
            )
        ],
        inventory=inventory,
    )

    assert result.actions[0].action == "installed_new"
    assert result.actions[0].matched_installed_slug is None
    assert Path(result.actions[0].installed_path or "").joinpath("SKILL.md").exists()


def test_skill_sync_rejects_path_escape_before_install(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)
    source_root = _source_package_root(tmp_path, "escape-skill")

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("../escape-skill", source_package_root=source_root)],
        inventory={},
    )

    assert result.actions[0].action == "blocked_audit_failure"
    assert audit_service.calls == []


def test_skill_sync_blocks_junction_managed_root_before_install(tmp_path) -> None:
    if os.name != "nt" or not hasattr(Path("x"), "is_junction"):
        pytest.skip("Windows junctions are not available")

    managed_target = tmp_path / "managed-target"
    managed_target.mkdir(parents=True, exist_ok=True)
    junction_root = tmp_path / "managed-root-junction"

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction_root), str(managed_target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not junction_root.is_junction():
        pytest.skip("Windows junction creation is not supported in this environment")

    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=junction_root, audit_service=audit_service)
    source_root = _source_package_root(tmp_path, "browser-bot")

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("browser-bot", display_name="Browser Bot", source_package_root=source_root)],
        inventory={},
    )

    assert result.actions[0].action == "blocked_audit_failure"
    assert "alias" in result.actions[0].reason.casefold()
    assert audit_service.calls == []
    assert not any(managed_target.iterdir())
