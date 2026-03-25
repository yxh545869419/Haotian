from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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
    relative_root: str = ".",
    files: tuple[str, ...] = ("SKILL.md",),
) -> SkillSyncCandidate:
    return SkillSyncCandidate(
        slug=slug,
        display_name=display_name or slug,
        source_repo_full_name="acme/skill-repo",
        repo_url="https://github.com/acme/skill-repo",
        relative_root=relative_root,
        files=files,
        capability_ids=("browser_automation",),
    )


def _installed(root: Path, slug: str, *, display_name: str | None = None, managed: bool = False) -> InstalledSkillRecord:
    skill_dir = root / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"# {display_name or slug}\n", encoding="utf-8")
    return InstalledSkillRecord(
        slug=slug,
        source_root=root.resolve(),
        skill_dir=skill_dir.resolve(),
        canonical_path=skill_dir.resolve(),
        display_name=display_name or slug,
        relative_path=slug,
        root_index=0,
        managed=managed,
    )


def test_skill_sync_aligns_existing_skill_without_rewriting_it(tmp_path) -> None:
    managed_root = tmp_path / "managed"
    audit_service = FakeAuditService(FakeAuditResult(status="clean", overall_verdict="CLEAN", installable=True))
    existing = _installed(managed_root, "browser-bot", managed=True)
    service = SkillSyncService(managed_root=managed_root, audit_service=audit_service)

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("browser-bot", display_name="Browser Bot")],
        inventory={"browser-bot": existing},
    )

    assert result.actions[0].action == "aligned_existing"
    assert result.actions[0].matched_installed_slug == "browser-bot"
    assert audit_service.calls == []
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

    installed_root = managed_root / "agent-designer"
    assert result.actions[0].action == "installed_new"
    assert installed_root.joinpath("SKILL.md").exists()
    assert installed_root.joinpath("haotian-wrapper.json").exists()
    assert len(audit_service.calls) == 1
    assert audit_service.calls[0].name.startswith(".haotian-stage-agent-designer")
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
        "browser-helper": _installed(shared_root, "browser-helper", display_name="Browser Helper"),
        "browser helper": _installed(shared_root, "browser helper", display_name="Browser Helper"),
    }

    result = service.sync(
        report_date=date(2026, 3, 25),
        candidates=[_candidate("browser helper", display_name="Browser Helper")],
        inventory=inventory,
    )

    assert result.actions[0].action == "blocked_ambiguous_match"
    assert audit_service.calls == []


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
