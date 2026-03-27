from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path

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
    managed: bool = False,
    source_repo_full_name: str | None = None,
    relative_root: str = ".",
    wrapper_slug: str | None = None,
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
        description="Installed local skill.",
        relative_path=slug,
        root_index=0,
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


def test_skill_sync_blocks_ambiguous_match(tmp_path) -> None:
    shared_root = tmp_path / "shared"
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)

    inventory = {
        "browser-helper": _installed(
            shared_root,
            "browser-helper",
            display_name="Browser Helper",
            managed=True,
            source_repo_full_name="acme/skill-repo",
        ),
        "browser helper": _installed(
            shared_root,
            "browser helper",
            display_name="Browser Helper",
            managed=True,
            source_repo_full_name="acme/skill-repo",
        ),
    }

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("browser helper", display_name="Browser Helper")],
        inventory=inventory,
    )

    assert result.actions[0].action == "blocked_ambiguous_match"
    assert audit_service.calls == []


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
