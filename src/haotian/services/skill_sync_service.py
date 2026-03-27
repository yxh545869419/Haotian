"""Deterministic sync of discovered third-party skills into Haotian-managed wrappers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Literal

from haotian.config import get_settings
from haotian.services.codex_skill_inventory_service import CodexSkillInventoryService, InstalledSkillRecord
from haotian.services.skill_audit_service import SkillAuditService

SKILL_SYNC_ACTIONS = (
    "aligned_existing",
    "installed_new",
    "discarded_non_integrable",
    "blocked_audit_failure",
    "blocked_ambiguous_match",
    "rolled_back_install_failure",
)

SkillSyncActionType = Literal[
    "aligned_existing",
    "installed_new",
    "discarded_non_integrable",
    "blocked_audit_failure",
    "blocked_ambiguous_match",
    "rolled_back_install_failure",
]


@dataclass(frozen=True, slots=True)
class SkillSyncCandidate:
    """Stable metadata for one discovered skill package candidate."""

    slug: str
    display_name: str
    source_repo_full_name: str
    repo_url: str
    relative_root: str
    files: tuple[str, ...]
    description: str = ""
    matched_keywords: tuple[str, ...] = ()
    architecture_signals: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillSyncAction:
    """One deterministic sync decision for a candidate."""

    action: SkillSyncActionType
    slug: str
    display_name: str
    source_repo_full_name: str
    repo_url: str
    relative_root: str
    files: tuple[str, ...]
    matched_installed_slug: str | None = None
    matched_installed_path: str | None = None
    installed_path: str | None = None
    audit_status: str | None = None
    audit_verdict: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "slug": self.slug,
            "display_name": self.display_name,
            "source_repo_full_name": self.source_repo_full_name,
            "repo_url": self.repo_url,
            "relative_root": self.relative_root,
            "files": list(self.files),
            "matched_installed_slug": self.matched_installed_slug,
            "matched_installed_path": self.matched_installed_path,
            "installed_path": self.installed_path,
            "audit_status": self.audit_status,
            "audit_verdict": self.audit_verdict,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SkillSyncResult:
    """Serializable sync summary for one finalized report date."""

    report_date: date
    summary: dict[str, object]
    actions: tuple[SkillSyncAction, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "report_date": self.report_date.isoformat(),
            "summary": dict(self.summary),
            "actions": [action.to_dict() for action in self.actions],
        }


class SkillSyncService:
    """Align existing skills or install audited managed wrappers for new ones."""

    def __init__(
        self,
        *,
        managed_root: Path | str | None = None,
        inventory_service: CodexSkillInventoryService | None = None,
        audit_service: SkillAuditService | object | None = None,
    ) -> None:
        settings = get_settings()
        resolved_managed_root = managed_root if managed_root is not None else settings.codex_managed_skill_root
        self.managed_root = Path(resolved_managed_root).resolve(strict=False) if resolved_managed_root is not None else None
        self.inventory_service = inventory_service or CodexSkillInventoryService(managed_root=self.managed_root)
        if audit_service is None and settings.skill_audit_script is not None:
            audit_service = SkillAuditService(script_path=settings.skill_audit_script)
        self.audit_service = audit_service

    def sync(
        self,
        *,
        report_date: date,
        candidates: list[SkillSyncCandidate] | tuple[SkillSyncCandidate, ...],
        inventory: dict[str, InstalledSkillRecord] | None = None,
    ) -> SkillSyncResult:
        ordered_candidates = tuple(
            sorted(
                candidates,
                key=lambda item: (
                    self._normalized_token(item.slug),
                    self._normalized_token(item.source_repo_full_name),
                    self._normalized_token(item.relative_root),
                ),
            )
        )
        inventory_records = dict(inventory) if inventory is not None else self.inventory_service.scan()
        duplicate_slug_groups = self._duplicate_slug_groups(ordered_candidates)

        actions: list[SkillSyncAction] = []
        for candidate in ordered_candidates:
            action = self._sync_candidate(
                candidate=candidate,
                inventory_records=inventory_records,
                duplicate_slug_groups=duplicate_slug_groups,
            )
            actions.append(action)
            if action.action == "installed_new" and action.installed_path is not None and self.managed_root is not None:
                installed_path = Path(action.installed_path).resolve(strict=False)
                inventory_records[action.slug] = InstalledSkillRecord(
                    slug=action.slug,
                    source_root=self.managed_root,
                    skill_dir=installed_path,
                    canonical_path=installed_path,
                    display_name=action.display_name,
                    description=candidate.description,
                    relative_path=action.slug,
                    root_index=0,
                    managed=True,
                    aliases=(candidate.slug,) if candidate.slug != action.slug else (),
                    managed_source_repo_full_name=action.source_repo_full_name,
                    managed_wrapper_slug=candidate.slug,
                    managed_relative_root=candidate.relative_root,
                )

        return SkillSyncResult(
            report_date=report_date,
            summary=self._build_summary(ordered_candidates, actions),
            actions=tuple(actions),
        )

    def _sync_candidate(
        self,
        *,
        candidate: SkillSyncCandidate,
        inventory_records: dict[str, InstalledSkillRecord],
        duplicate_slug_groups: dict[str, list[SkillSyncCandidate]],
    ) -> SkillSyncAction:
        try:
            install_slug = self._install_slug(candidate)
        except ValueError as exc:
            return self._action(candidate, "blocked_audit_failure", reason=str(exc))

        if len(duplicate_slug_groups.get(install_slug, ())) > 1:
            return self._action(
                candidate,
                "blocked_ambiguous_match",
                slug=install_slug,
                reason=f"Multiple candidates collapse to the same managed slug '{install_slug}'.",
            )

        if not self._is_integrable(candidate):
            return self._action(
                candidate,
                "discarded_non_integrable",
                slug=install_slug,
                reason="Candidate does not satisfy the minimum Codex skill packaging and runtime-evidence requirements.",
            )

        match_state, matched_record = self._match_candidate(candidate, tuple(inventory_records.values()))
        if match_state == "ambiguous":
            return self._action(
                candidate,
                "blocked_ambiguous_match",
                slug=install_slug,
                reason="Matched multiple installed skills with the same deterministic score.",
            )
        if matched_record is not None:
            if self.audit_service is None:
                return self._action(
                    candidate,
                    "blocked_audit_failure",
                    slug=install_slug,
                    matched_installed_slug=matched_record.slug,
                    matched_installed_path=str(matched_record.skill_dir),
                    reason="Skill sync cannot align an existing skill without an audit service.",
                )
            audit_result = self.audit_service.audit(matched_record.skill_dir)
            if not audit_result.is_installable():
                return self._action(
                    candidate,
                    "blocked_audit_failure",
                    slug=install_slug,
                    matched_installed_slug=matched_record.slug,
                    matched_installed_path=str(matched_record.skill_dir),
                    audit_status=str(getattr(audit_result, "status", "")),
                    audit_verdict=str(getattr(audit_result, "overall_verdict", "")),
                    reason="The matched installed skill did not pass audit.",
                )
            return self._action(
                candidate,
                "aligned_existing",
                slug=install_slug,
                matched_installed_slug=matched_record.slug,
                matched_installed_path=str(matched_record.skill_dir),
                audit_status=str(getattr(audit_result, "status", "")),
                audit_verdict=str(getattr(audit_result, "overall_verdict", "")),
                reason="A unique installed skill already satisfies this candidate.",
            )

        if self.managed_root is None or self.audit_service is None:
            return self._action(
                candidate,
                "blocked_audit_failure",
                slug=install_slug,
                reason="Skill sync install configuration is incomplete.",
            )

        return self._install_new(candidate=candidate, install_slug=install_slug)

    def _install_new(self, *, candidate: SkillSyncCandidate, install_slug: str) -> SkillSyncAction:
        assert self.managed_root is not None
        assert self.audit_service is not None

        target_dir = self.managed_root / install_slug
        staging_dir = self.managed_root.parent / f".haotian-stage-{install_slug}"
        if not self._paths_are_safe(target_dir=target_dir, staging_dir=staging_dir):
            return self._action(
                candidate,
                "blocked_audit_failure",
                slug=install_slug,
                reason="Managed install path escapes the allowed root or uses a symlinked alias.",
            )
        if target_dir.exists():
            return self._action(
                candidate,
                "blocked_audit_failure",
                slug=install_slug,
                reason=f"Managed target already exists: {target_dir}",
            )

        try:
            self.managed_root.mkdir(parents=True, exist_ok=True)
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=False)
            staging_dir.mkdir(parents=True, exist_ok=False)
            for relative_path, content in self._wrapper_files(candidate).items():
                target = staging_dir / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

            audit_result = self.audit_service.audit(staging_dir)
            if not audit_result.is_installable():
                shutil.rmtree(staging_dir, ignore_errors=True)
                return self._action(
                    candidate,
                    "blocked_audit_failure",
                    slug=install_slug,
                    audit_status=str(getattr(audit_result, "status", "")),
                    audit_verdict=str(getattr(audit_result, "overall_verdict", "")),
                    reason="The managed wrapper did not pass audit.",
                )

            staging_dir.replace(target_dir)
            return self._action(
                candidate,
                "installed_new",
                slug=install_slug,
                installed_path=str(target_dir.resolve(strict=False)),
                audit_status=str(getattr(audit_result, "status", "")),
                audit_verdict=str(getattr(audit_result, "overall_verdict", "")),
                reason="Installed a new audited managed wrapper.",
            )
        except Exception as exc:  # noqa: BLE001
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            return self._action(
                candidate,
                "rolled_back_install_failure",
                slug=install_slug,
                reason=f"Managed wrapper install failed and was rolled back: {exc}",
            )

    def _match_candidate(
        self,
        candidate: SkillSyncCandidate,
        inventory_records: tuple[InstalledSkillRecord, ...],
    ) -> tuple[str, InstalledSkillRecord | None]:
        candidate_tokens = self._candidate_exact_tokens(candidate)
        exact_matches: list[tuple[int, int, int, str, str, InstalledSkillRecord]] = []
        for record in inventory_records:
            if not self._record_can_match_candidate(candidate, record):
                continue
            rank = self._exact_match_rank(candidate_tokens, record)
            if rank is None:
                continue
            exact_matches.append(
                (
                    rank,
                    record.root_index,
                    0 if record.managed else 1,
                    record.slug.casefold(),
                    record.display_name.casefold(),
                    record,
                )
            )
        if exact_matches:
            exact_matches.sort()
            return "matched", exact_matches[0][-1]

        candidate_similarity_tokens = self._candidate_similarity_tokens(candidate)
        scored: list[tuple[float, InstalledSkillRecord]] = []
        for record in inventory_records:
            if not self._record_can_match_candidate(candidate, record):
                continue
            record_tokens = self._record_similarity_tokens(record)
            if not record_tokens:
                continue
            score = self._token_set_jaccard(candidate_similarity_tokens, record_tokens)
            if score >= 0.72:
                scored.append((score, record))
        if not scored:
            return "none", None

        scored.sort(
            key=lambda item: (
                -item[0],
                item[1].root_index,
                0 if item[1].managed else 1,
                item[1].slug.casefold(),
                item[1].display_name.casefold(),
            )
        )
        return "matched", scored[0][1]

    @staticmethod
    def _exact_match_rank(candidate_tokens: set[str], record: InstalledSkillRecord) -> int | None:
        if candidate_tokens & SkillSyncService._record_canonical_tokens(record):
            return 0
        if candidate_tokens & SkillSyncService._record_alias_tokens(record):
            return 1
        return None

    @staticmethod
    def _record_canonical_tokens(record: InstalledSkillRecord) -> set[str]:
        return {
            token
            for token in (
                SkillSyncService._normalized_token(record.slug),
                SkillSyncService._normalized_token(record.display_name),
            )
            if token
        }

    @staticmethod
    def _record_alias_tokens(record: InstalledSkillRecord) -> set[str]:
        tokens = set()
        if record.managed_wrapper_slug:
            tokens.add(SkillSyncService._normalized_token(record.managed_wrapper_slug))
        for alias in record.aliases:
            tokens.add(SkillSyncService._normalized_token(alias))
        return {token for token in tokens if token}

    @staticmethod
    def _record_exact_tokens(record: InstalledSkillRecord) -> set[str]:
        return SkillSyncService._record_canonical_tokens(record) | SkillSyncService._record_alias_tokens(record)

    @staticmethod
    def _record_can_match_candidate(
        candidate: SkillSyncCandidate,
        record: InstalledSkillRecord,
    ) -> bool:
        if not record.managed:
            return True
        record_repo = SkillSyncService._canonical_repo_identity(record.managed_source_repo_full_name)
        candidate_repo = SkillSyncService._canonical_repo_identity(candidate.source_repo_full_name)
        if record_repo is not None and record_repo != candidate_repo:
            return False
        record_root = SkillSyncService._canonical_relative_root(record.managed_relative_root)
        candidate_root = SkillSyncService._canonical_relative_root(candidate.relative_root)
        if record_root is not None and record_root != candidate_root:
            return False
        return True

    @staticmethod
    def _candidate_exact_tokens(candidate: SkillSyncCandidate) -> set[str]:
        return {
            token
            for token in (
                SkillSyncService._normalized_token(candidate.slug),
                SkillSyncService._normalized_token(candidate.display_name),
            )
            if token
        }

    @staticmethod
    def _candidate_similarity_tokens(candidate: SkillSyncCandidate) -> set[str]:
        return SkillSyncService._expanded_token_set(
            candidate.description,
            *candidate.matched_keywords,
            *candidate.architecture_signals,
        )

    @staticmethod
    def _record_similarity_tokens(record: InstalledSkillRecord) -> set[str]:
        return SkillSyncService._expanded_token_set(record.description)

    @staticmethod
    def _expanded_token_set(*values: str) -> set[str]:
        tokens: set[str] = set()
        for value in values:
            normalized = SkillSyncService._normalized_token(value)
            if not normalized:
                continue
            tokens.add(normalized)
            tokens.update(part for part in normalized.split("-") if part)
        return tokens

    @staticmethod
    def _token_set_jaccard(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        union = left | right
        if not union:
            return 0.0
        return len(left & right) / len(union)

    @staticmethod
    def _canonical_repo_identity(value: str | None) -> tuple[str, str] | None:
        if value is None:
            return None
        normalized = value.strip().replace("\\", "/")
        parts = [part.strip().casefold() for part in normalized.split("/")]
        if len(parts) != 2 or any(not part for part in parts):
            return None
        return parts[0], parts[1]

    @staticmethod
    def _canonical_relative_root(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip() or "."
        if normalized == ".":
            return "."
        pure = PurePosixPath(normalized.replace("\\", "/"))
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            return None
        return pure.as_posix()

    @staticmethod
    def _is_integrable(candidate: SkillSyncCandidate) -> bool:
        return (
            "SKILL.md" in candidate.files
            and SkillSyncService._is_safe_relative_root(candidate.relative_root)
            and SkillSyncService._has_support_files(candidate.files)
            and SkillSyncService._has_runtime_evidence(candidate)
        )

    @staticmethod
    def _has_support_files(files: tuple[str, ...]) -> bool:
        normalized_files = {item.strip().replace("\\", "/").casefold() for item in files}
        return any(
            path == "agents.md"
            or path == "codex.md"
            or path.endswith("/agents.md")
            or path.endswith("/codex.md")
            or path.startswith("scripts/")
            or path.startswith("references/")
            for path in normalized_files
        )

    @staticmethod
    def _has_runtime_evidence(candidate: SkillSyncCandidate) -> bool:
        runtime_signals = {
            "codex-skill-package",
            "skill-ecosystem",
            "plugin-ecosystem",
        }
        return any(signal.strip().casefold() in runtime_signals for signal in candidate.architecture_signals)

    @staticmethod
    def _is_safe_relative_root(relative_root: str) -> bool:
        normalized = relative_root.strip() or "."
        if normalized == ".":
            return True
        pure = PurePosixPath(normalized.replace("\\", "/"))
        return not pure.is_absolute() and all(part not in {"", ".", ".."} for part in pure.parts)

    @staticmethod
    def _install_slug(candidate: SkillSyncCandidate) -> str:
        normalized = candidate.slug.strip()
        if not normalized:
            raise ValueError("Candidate slug is empty.")
        pure = PurePosixPath(normalized.replace("\\", "/"))
        if pure.is_absolute() or len(pure.parts) != 1 or any(part in {"", ".", ".."} for part in pure.parts):
            raise ValueError(f"Candidate slug '{candidate.slug}' escapes the managed root.")
        repo_token = SkillSyncService._normalized_token(candidate.source_repo_full_name.replace("/", "-"))
        if not repo_token:
            raise ValueError(f"Candidate repo '{candidate.source_repo_full_name}' does not normalize to a usable directory name.")
        candidate_token = SkillSyncService._normalized_token(normalized)
        parts = [repo_token]
        if candidate_token and not repo_token.endswith(candidate_token):
            parts.append(candidate_token)
        digest = hashlib.sha1(
            "\0".join(
                (
                    candidate.source_repo_full_name.strip(),
                    candidate.slug.strip(),
                    candidate.relative_root.strip() or ".",
                )
            ).encode("utf-8")
        ).hexdigest()[:10]
        install_slug = "-".join(part for part in (*[part for part in parts if part], digest) if part)
        if not install_slug:
            raise ValueError(f"Candidate slug '{candidate.slug}' does not normalize to a usable directory name.")
        return install_slug

    @staticmethod
    def _normalized_token(value: str) -> str:
        lowered = value.strip().lower()
        collapsed = re.sub(r"[^a-z0-9]+", "-", lowered)
        return collapsed.strip("-")

    @staticmethod
    def _duplicate_slug_groups(candidates: tuple[SkillSyncCandidate, ...]) -> dict[str, list[SkillSyncCandidate]]:
        grouped: dict[str, list[SkillSyncCandidate]] = defaultdict(list)
        for candidate in candidates:
            try:
                grouped[SkillSyncService._install_slug(candidate)].append(candidate)
            except ValueError:
                continue
        return grouped

    def _paths_are_safe(self, *, target_dir: Path, staging_dir: Path) -> bool:
        if self.managed_root is None:
            return False
        managed_root = self.managed_root.resolve(strict=False)
        if self._has_symlink_component(managed_root.parent) or self._has_symlink_component(managed_root):
            return False
        if target_dir.resolve(strict=False).parent != managed_root:
            return False
        if staging_dir.resolve(strict=False).parent != managed_root.parent:
            return False
        return not (staging_dir.exists() and staging_dir.is_symlink()) and not (target_dir.exists() and target_dir.is_symlink())

    @staticmethod
    def _has_symlink_component(path: Path) -> bool:
        current = path
        while True:
            if current.exists() and current.is_symlink():
                return True
            if current.parent == current:
                return False
            current = current.parent

    @staticmethod
    def _wrapper_files(candidate: SkillSyncCandidate) -> dict[str, str]:
        title = candidate.display_name.strip() or candidate.slug
        metadata = {
            "schema_version": 1,
            "managed_by": "haotian",
            "slug": candidate.slug,
            "display_name": title,
            "source_repo_full_name": candidate.source_repo_full_name,
            "relative_root": candidate.relative_root,
            "files": list(candidate.files),
            "capability_ids": list(candidate.capability_ids),
        }
        return {
            "SKILL.md": (
                f"# {title}\n\n"
                "Managed wrapper generated by Haotian.\n\n"
                f"- Source repository: `{candidate.source_repo_full_name}`\n"
                f"- Source package root: `{candidate.relative_root}`\n"
                f"- Declared files: {', '.join(f'`{item}`' for item in candidate.files)}\n"
            ),
            "haotian-wrapper.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        }

    @staticmethod
    def _default_summary(*, config_ready: bool, candidate_count: int, action_count: int) -> dict[str, object]:
        summary: dict[str, object] = {
            "config_ready": config_ready,
            "candidate_count": candidate_count,
            "action_count": action_count,
        }
        for action in SKILL_SYNC_ACTIONS:
            summary[action] = 0
        return summary

    def _build_summary(
        self,
        candidates: tuple[SkillSyncCandidate, ...],
        actions: list[SkillSyncAction],
    ) -> dict[str, object]:
        summary = self._default_summary(
            config_ready=self.managed_root is not None and self.audit_service is not None,
            candidate_count=len(candidates),
            action_count=len(actions),
        )
        for action in actions:
            summary[action.action] = int(summary.get(action.action, 0)) + 1
        return summary

    @staticmethod
    def _action(
        candidate: SkillSyncCandidate,
        action: SkillSyncActionType,
        *,
        slug: str | None = None,
        matched_installed_slug: str | None = None,
        matched_installed_path: str | None = None,
        installed_path: str | None = None,
        audit_status: str | None = None,
        audit_verdict: str | None = None,
        reason: str = "",
    ) -> SkillSyncAction:
        return SkillSyncAction(
            action=action,
            slug=slug or candidate.slug,
            display_name=candidate.display_name,
            source_repo_full_name=candidate.source_repo_full_name,
            repo_url=candidate.repo_url,
            relative_root=candidate.relative_root,
            files=candidate.files,
            matched_installed_slug=matched_installed_slug,
            matched_installed_path=matched_installed_path,
            installed_path=installed_path,
            audit_status=audit_status,
            audit_verdict=audit_verdict,
            reason=reason,
        )
