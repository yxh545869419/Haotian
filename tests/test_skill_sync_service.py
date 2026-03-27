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
    description: str = "Codex skill package for browser automation workflows.",
    matched_keywords: tuple[str, ...] = ("SKILL.md", "AGENTS.md"),
    architecture_signals: tuple[str, ...] = ("codex-skill-package",),
) -> SkillSyncCandidate:
    return SkillSyncCandidate(
        slug=slug,
        display_name=display_name or slug,
        source_repo_full_name=source_repo_full_name,
        repo_url=repo_url,
        relative_root=relative_root,
        files=files,
        description=description,
        matched_keywords=matched_keywords,
        architecture_signals=architecture_signals,
        capability_ids=("browser_automation",),
    )


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
) -> InstalledSkillRecord:
    skill_dir = root / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"# {display_name or slug}\n", encoding="utf-8")
    if managed and source_repo_full_name:
        (skill_dir / "haotian-wrapper.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "managed_by": "haotian",
                    "slug": wrapper_slug or slug,
                    "display_name": display_name or slug,
                    "source_repo_full_name": source_repo_full_name,
                    "relative_root": relative_root,
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
    )


def test_skill_sync_aligns_existing_skill_without_rewriting_it(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    existing = _installed(
        managed_root,
        "browser-bot",
        managed=True,
        source_repo_full_name="acme/skill-repo",
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

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("agent-designer", display_name="Agent Designer", relative_root="skills/agent-designer")],
        inventory={},
    )

    assert result.actions[0].action == "installed_new"
    installed_root = Path(result.actions[0].installed_path or "")
    assert installed_root.joinpath("SKILL.md").exists()
    assert installed_root.joinpath("haotian-wrapper.json").exists()
    assert len(audit_service.calls) == 1
    assert audit_service.calls[0].name.startswith(f".haotian-stage-{result.actions[0].slug}")
    assert list(managed_root.parent.glob(".haotian-stage-*")) == []
    assert result.summary["installed_new"] == 1


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


def test_skill_sync_accepts_manifest_with_readme_and_settings_as_supporting_evidence(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate(
                "a11y-audit",
                files=("README.md", "SKILL.md", "settings.json"),
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

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("research-briefs")],
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

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate("browser-bot", source_repo_full_name="acme/browser-bot"),
            _candidate("browser-bot", source_repo_full_name="contoso/browser-bot"),
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

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate("browser-bot", source_repo_full_name="acme/browser-bot"),
            _candidate("bot", source_repo_full_name="acme-browser/bot"),
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


def test_skill_sync_does_not_align_unmanaged_fuzzy_match(tmp_path) -> None:
    shared_root = tmp_path / "shared"
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("browser-bot", display_name="Browser Bot", source_repo_full_name="acme/browser-bot")],
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

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("browser-bot", display_name="Browser Bot", source_repo_full_name="acme-browser/bot")],
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

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[
            _candidate(
                "browser-bot",
                display_name="Browser Bot",
                source_repo_full_name="acme/browser-bot",
                relative_root="skills-browser/bot",
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

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("browser-bot", display_name="Browser Bot", source_repo_full_name="other/repo")],
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

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("browser-bot", display_name="Browser Bot", source_repo_full_name="other/repo")],
        inventory=inventory,
    )

    assert result.actions[0].action == "installed_new"
    assert result.actions[0].matched_installed_slug is None
    assert Path(result.actions[0].installed_path or "").joinpath("SKILL.md").exists()


def test_skill_sync_rejects_path_escape_before_install(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("../escape-skill")],
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

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("browser-bot", display_name="Browser Bot")],
        inventory={},
    )

    assert result.actions[0].action == "blocked_audit_failure"
    assert "alias" in result.actions[0].reason.casefold()
    assert audit_service.calls == []
    assert not any(managed_target.iterdir())
