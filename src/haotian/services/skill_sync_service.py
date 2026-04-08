"""Deterministic sync of discovered third-party skills into Haotian-managed wrappers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import os
import re
import shutil
import stat
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
    source_package_root: Path | None = None
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
    capability_ids: tuple[str, ...] = ()
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
            "capability_ids": list(self.capability_ids),
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
    """Align existing skills or install audited full skill packages for new ones."""

    def __init__(
        self,
        *,
        managed_root: Path | str | None = None,
        inventory_service: CodexSkillInventoryService | None = None,
        audit_service: SkillAuditService | object | None = None,
    ) -> None:
        settings = get_settings()
        resolved_managed_root = managed_root if managed_root is not None else settings.codex_managed_skill_root
        self.managed_root = Path(resolved_managed_root) if resolved_managed_root is not None else None
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
            if matched_record.managed and self._is_wrapper_only_install(matched_record.skill_dir):
                if self.managed_root is None or self.audit_service is None:
                    return self._action(
                        candidate,
                        "blocked_audit_failure",
                        slug=install_slug,
                        matched_installed_slug=matched_record.slug,
                        matched_installed_path=str(matched_record.skill_dir),
                        reason="Skill sync install configuration is incomplete.",
                    )
                if candidate.source_package_root is None:
                    return self._action(
                        candidate,
                        "blocked_audit_failure",
                        slug=install_slug,
                        matched_installed_slug=matched_record.slug,
                        matched_installed_path=str(matched_record.skill_dir),
                        reason="Candidate does not expose a source package root for full-package installation.",
                    )
                return self._install_new(
                    candidate=candidate,
                    install_slug=matched_record.slug,
                    target_dir_override=matched_record.skill_dir,
                )
            if self._is_trusted_builtin_record(matched_record):
                removed_redundant = self._remove_redundant_managed_matches(
                    candidate=candidate,
                    matched_record=matched_record,
                    inventory_records=tuple(inventory_records.values()),
                )
                reason = "A trusted built-in installed skill already satisfies this candidate."
                if removed_redundant:
                    reason += f" Removed {removed_redundant} redundant managed duplicate(s)."
                return self._action(
                    candidate,
                    "aligned_existing",
                    slug=install_slug,
                    matched_installed_slug=matched_record.slug,
                    matched_installed_path=str(matched_record.skill_dir),
                    audit_status="trusted",
                    audit_verdict="TRUSTED",
                    reason=reason,
                )
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
            removed_redundant = 0
            if not matched_record.managed:
                removed_redundant = self._remove_redundant_managed_matches(
                    candidate=candidate,
                    matched_record=matched_record,
                    inventory_records=tuple(inventory_records.values()),
                )
            reason = "A unique installed skill already satisfies this candidate."
            if removed_redundant:
                reason += f" Removed {removed_redundant} redundant managed duplicate(s)."
            return self._action(
                candidate,
                "aligned_existing",
                slug=install_slug,
                matched_installed_slug=matched_record.slug,
                matched_installed_path=str(matched_record.skill_dir),
                audit_status=str(getattr(audit_result, "status", "")),
                audit_verdict=str(getattr(audit_result, "overall_verdict", "")),
                reason=reason,
            )

        if self.managed_root is None or self.audit_service is None:
            return self._action(
                candidate,
                "blocked_audit_failure",
                slug=install_slug,
                reason="Skill sync install configuration is incomplete.",
            )
        if candidate.source_package_root is None:
            return self._action(
                candidate,
                "blocked_audit_failure",
                slug=install_slug,
                reason="Candidate does not expose a source package root for full-package installation.",
            )

        return self._install_new(candidate=candidate, install_slug=install_slug)

    def _install_new(
        self,
        *,
        candidate: SkillSyncCandidate,
        install_slug: str,
        target_dir_override: Path | None = None,
    ) -> SkillSyncAction:
        assert self.managed_root is not None
        assert self.audit_service is not None
        assert candidate.source_package_root is not None

        target_dir = target_dir_override or (self.managed_root / install_slug)
        staging_dir = self.managed_root.parent / f".haotian-stage-{install_slug}"
        if not self._paths_are_safe(target_dir=target_dir, staging_dir=staging_dir):
            return self._action(
                candidate,
                "blocked_audit_failure",
                slug=install_slug,
                reason="Managed install path escapes the allowed root or uses a symlinked alias.",
            )
        if target_dir.exists() and not self._is_wrapper_only_install(target_dir):
            return self._action(
                candidate,
                "blocked_audit_failure",
                slug=install_slug,
                reason=f"Managed target already exists: {target_dir}",
            )

        try:
            self.managed_root.mkdir(parents=True, exist_ok=True)
            source_root = Path(candidate.source_package_root).resolve(strict=True)
            if not source_root.is_dir():
                return self._action(
                    candidate,
                    "blocked_audit_failure",
                    slug=install_slug,
                    reason=f"Source package root is not a directory: {source_root}",
                )
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=False)
            staging_dir.mkdir(parents=True, exist_ok=False)
            self._copy_package_contents(source_root, staging_dir)
            self._write_managed_metadata(staging_dir, candidate)

            audit_result = self.audit_service.audit(staging_dir)
            if not audit_result.is_installable():
                shutil.rmtree(staging_dir, ignore_errors=True)
                return self._action(
                    candidate,
                    "blocked_audit_failure",
                    slug=install_slug,
                    audit_status=str(getattr(audit_result, "status", "")),
                    audit_verdict=str(getattr(audit_result, "overall_verdict", "")),
                    reason="The staged full package did not pass audit.",
                )

            self._replace_directory(staging_dir=staging_dir, target_dir=target_dir)
            return self._action(
                candidate,
                "installed_new",
                slug=install_slug,
                installed_path=str(target_dir.resolve(strict=False)),
                audit_status=str(getattr(audit_result, "status", "")),
                audit_verdict=str(getattr(audit_result, "overall_verdict", "")),
                reason="Installed a new audited full skill package.",
            )
        except Exception as exc:  # noqa: BLE001
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            return self._action(
                candidate,
                "rolled_back_install_failure",
                slug=install_slug,
                reason=f"Managed full-package install failed and was rolled back: {exc}",
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
                    1 if record.managed else 0,
                    record.root_index,
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
            score = self._similarity_score(candidate, candidate_similarity_tokens, record)
            if score >= 0.72:
                scored.append((score, record))
        if not scored:
            return "none", None

        scored.sort(
            key=lambda item: (
                -item[0],
                1 if item[1].managed else 0,
                item[1].root_index,
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

    def _remove_redundant_managed_matches(
        self,
        *,
        candidate: SkillSyncCandidate,
        matched_record: InstalledSkillRecord,
        inventory_records: tuple[InstalledSkillRecord, ...],
    ) -> int:
        if self.managed_root is None:
            return 0
        candidate_tokens = self._candidate_exact_tokens(candidate)
        removed = 0
        for record in inventory_records:
            if not record.managed or record.skill_dir == matched_record.skill_dir:
                continue
            if not self._record_can_match_candidate(candidate, record):
                continue
            if self._exact_match_rank(candidate_tokens, record) is None:
                continue
            if not self._managed_record_is_removable(record):
                continue
            try:
                shutil.rmtree(record.skill_dir, ignore_errors=False)
                removed += 1
            except OSError:
                continue
        return removed

    def _managed_record_is_removable(self, record: InstalledSkillRecord) -> bool:
        if self.managed_root is None:
            return False
        try:
            managed_root = self.managed_root.resolve(strict=False)
            record_dir = record.skill_dir.resolve(strict=False)
        except OSError:
            return False
        try:
            record_dir.relative_to(managed_root)
        except ValueError:
            return False
        return record_dir != managed_root and not self._is_alias_path(record.skill_dir)

    @staticmethod
    def _is_trusted_builtin_record(record: InstalledSkillRecord) -> bool:
        if record.managed:
            return False
        return any(part.casefold() == ".system" for part in record.skill_dir.parts)

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
        if record.managed_wrapper_slug and SkillSyncService._is_valid_metadata_slug(record.managed_wrapper_slug):
            tokens.add(SkillSyncService._normalized_token(record.managed_wrapper_slug))
        for alias in record.aliases:
            if SkillSyncService._is_valid_metadata_slug(alias):
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
        if record.managed_wrapper_slug is not None and not SkillSyncService._is_valid_metadata_slug(record.managed_wrapper_slug):
            return False
        if any(not SkillSyncService._is_valid_metadata_slug(alias) for alias in record.aliases):
            return False
        record_repo = SkillSyncService._canonical_repo_identity(record.managed_source_repo_full_name)
        candidate_repo = SkillSyncService._canonical_repo_identity(candidate.source_repo_full_name)
        if record_repo is None or candidate_repo is None or record_repo != candidate_repo:
            return False
        record_root = SkillSyncService._canonical_relative_root(record.managed_relative_root)
        candidate_root = SkillSyncService._canonical_relative_root(candidate.relative_root)
        if record_root is None or candidate_root is None or record_root != candidate_root:
            return False
        return True

    @staticmethod
    def _candidate_exact_tokens(candidate: SkillSyncCandidate) -> set[str]:
        tokens = {
            token
            for token in (
                SkillSyncService._normalized_token(candidate.slug),
                SkillSyncService._normalized_token(candidate.display_name),
            )
            if token
        }
        tokens.update(SkillSyncService._semantic_alias_tokens(candidate.slug, candidate.display_name))
        return tokens

    @staticmethod
    def _semantic_alias_tokens(*values: str) -> set[str]:
        """Map common equivalent skill names to installed canonical skill slugs."""
        name_tokens = SkillSyncService._expanded_token_set(*values)
        if "skill" in name_tokens or "skills" in name_tokens:
            if {"write", "writing", "create", "creator", "build"} & name_tokens:
                return {"skill-creator"}
        return set()

    @staticmethod
    def _candidate_similarity_tokens(candidate: SkillSyncCandidate) -> set[str]:
        return SkillSyncService._expanded_token_set(
            candidate.description,
            *candidate.matched_keywords,
            *candidate.architecture_signals,
        )

    @staticmethod
    def _candidate_name_tokens(candidate: SkillSyncCandidate) -> set[str]:
        return SkillSyncService._expanded_token_set(candidate.slug, candidate.display_name)

    @staticmethod
    def _record_similarity_name_tokens(record: InstalledSkillRecord) -> set[str]:
        return SkillSyncService._expanded_token_set(
            record.slug,
            record.display_name,
            *record.aliases,
            record.managed_wrapper_slug or "",
        )

    @staticmethod
    def _record_similarity_tokens(record: InstalledSkillRecord) -> set[str]:
        return SkillSyncService._expanded_token_set(record.description)

    @staticmethod
    def _similarity_score(
        candidate: SkillSyncCandidate,
        candidate_evidence_tokens: set[str],
        record: InstalledSkillRecord,
    ) -> float:
        name_score = SkillSyncService._token_set_jaccard(
            SkillSyncService._candidate_name_tokens(candidate),
            SkillSyncService._record_similarity_name_tokens(record),
        )
        description_score = SkillSyncService._token_set_jaccard(
            SkillSyncService._expanded_token_set(candidate.description),
            SkillSyncService._record_similarity_tokens(record),
        )
        evidence_score = SkillSyncService._token_set_jaccard(
            candidate_evidence_tokens,
            SkillSyncService._record_similarity_name_tokens(record) | SkillSyncService._record_similarity_tokens(record),
        )
        return (0.6 * name_score) + (0.25 * description_score) + (0.15 * evidence_score)

    @staticmethod
    def _expanded_token_set(*values: str) -> set[str]:
        tokens: set[str] = set()
        for value in values:
            normalized = SkillSyncService._normalized_token(value)
            if not normalized:
                continue
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
    def _is_valid_metadata_slug(value: str) -> bool:
        normalized = value.strip()
        if not normalized:
            return False
        pure = PurePosixPath(normalized.replace("\\", "/"))
        return not pure.is_absolute() and len(pure.parts) == 1 and all(part not in {"", ".", ".."} for part in pure.parts)

    @staticmethod
    def _is_integrable(candidate: SkillSyncCandidate) -> bool:
        return (
            "SKILL.md" in candidate.files
            and SkillSyncService._is_safe_relative_root(candidate.relative_root)
            and (SkillSyncService._has_support_files(candidate.files) or candidate.source_package_root is not None)
        )

    @staticmethod
    def _has_support_files(files: tuple[str, ...]) -> bool:
        normalized_files = {item.strip().replace("\\", "/").casefold() for item in files}
        if any(path not in {"skill.md", ".gitignore"} for path in normalized_files):
            return True
        return any(
            path == "agents.md"
            or path == "codex.md"
            or path == "readme.md"
            or path == "settings.json"
            or path.endswith("/agents.md")
            or path.endswith("/codex.md")
            or path.endswith("/readme.md")
            or path.endswith("/settings.json")
            or path.endswith(".yaml")
            or path.endswith(".yml")
            or path.startswith("scripts/")
            or path.startswith("references/")
            or path.startswith("examples/")
            for path in normalized_files
        )

    @staticmethod
    def _has_runtime_evidence(candidate: SkillSyncCandidate) -> bool:
        runtime_signals = {
            "codex-skill-package",
            "skill-ecosystem",
            "plugin-ecosystem",
            "capability-wrapper",
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
        managed_root = self.managed_root
        if self._has_alias_component(managed_root.parent) or self._has_alias_component(managed_root):
            return False
        resolved_managed_root = managed_root.resolve(strict=False)
        if target_dir.resolve(strict=False).parent != resolved_managed_root:
            return False
        if staging_dir.resolve(strict=False).parent != resolved_managed_root.parent:
            return False
        return not self._is_alias_path(staging_dir) and not self._is_alias_path(target_dir)

    @staticmethod
    def _has_alias_component(path: Path) -> bool:
        for candidate in (path, *path.parents):
            if candidate.exists() and SkillSyncService._is_alias_path(candidate):
                return True
        return False

    @staticmethod
    def _is_alias_path(path: Path) -> bool:
        if path.is_symlink():
            return True

        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction):
            try:
                return bool(is_junction())
            except OSError:
                return False

        if os.name == "nt":
            try:
                return bool(os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            except OSError:
                return False

        return False

    @staticmethod
    def _is_wrapper_only_install(skill_dir: Path) -> bool:
        if not skill_dir.exists() or not skill_dir.is_dir():
            return False
        file_names = {
            path.name.casefold()
            for path in skill_dir.iterdir()
            if path.is_file()
        }
        if not file_names <= {"skill.md", "haotian-wrapper.json"}:
            return False
        metadata = SkillSyncService._read_managed_metadata(skill_dir)
        if metadata.get("install_type") == "full-package":
            return False
        if metadata.get("files") == ["SKILL.md"] and metadata.get("source_repo_full_name"):
            return False
        return True

    @staticmethod
    def _read_managed_metadata(skill_dir: Path) -> dict[str, object]:
        metadata_path = skill_dir / "haotian-wrapper.json"
        if not metadata_path.exists():
            return {}
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _write_managed_metadata(staging_dir: Path, candidate: SkillSyncCandidate) -> None:
        metadata = {
            "schema_version": 1,
            "managed_by": "haotian",
            "install_type": "full-package",
            "slug": candidate.slug,
            "display_name": candidate.display_name.strip() or candidate.slug,
            "source_repo_full_name": candidate.source_repo_full_name,
            "relative_root": candidate.relative_root,
            "files": list(candidate.files),
            "capability_ids": list(candidate.capability_ids),
        }
        (staging_dir / "haotian-wrapper.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def _copy_package_contents(cls, source_root: Path, staging_dir: Path) -> None:
        for current, dirs, files in os.walk(source_root, topdown=True, followlinks=False):
            current_path = Path(current)
            dirs[:] = [name for name in dirs if not cls._should_skip_source_path(source_root, current_path / name)]
            for name in files:
                source_path = current_path / name
                if cls._should_skip_source_path(source_root, source_path):
                    continue
                relative = source_path.relative_to(source_root)
                target_path = staging_dir / relative
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)

    @staticmethod
    def _should_skip_source_path(source_root: Path, path: Path) -> bool:
        relative = path.relative_to(source_root)
        parts = tuple(part.casefold() for part in relative.parts)
        if not parts:
            return False
        if any(part in {".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".venv", "venv", "env", "build", "dist", "site-packages", "node_modules", "vendor", "vendors", "third_party"} for part in parts):
            return True
        if any(part.startswith(".env") for part in parts):
            return True
        name = relative.name.casefold()
        if name in {".ds_store", "thumbs.db", "desktop.ini", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "pipfile.lock"}:
            return True
        if name.endswith((".pyc", ".pyo", ".pyd", ".swp", ".swo", ".tmp", ".bak", ".orig", ".rej")):
            return True
        if name.endswith(".lock"):
            return True
        if any(part.startswith(".") and part not in {".github"} for part in parts[:-1]):
            return True
        return False

    def _replace_directory(self, *, staging_dir: Path, target_dir: Path) -> None:
        backup_dir: Path | None = None
        try:
            if target_dir.exists():
                backup_dir = target_dir.with_name(f".haotian-backup-{target_dir.name}")
                if backup_dir.exists():
                    shutil.rmtree(backup_dir, ignore_errors=False)
                target_dir.rename(backup_dir)
            staging_dir.rename(target_dir)
        except Exception:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            if backup_dir is not None and backup_dir.exists() and not target_dir.exists():
                backup_dir.rename(target_dir)
            raise
        finally:
            if backup_dir is not None and backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)

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
                f"{f'Purpose: {candidate.description.strip()}\\n\\n' if candidate.description.strip() else ''}"
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
            capability_ids=candidate.capability_ids,
            matched_installed_slug=matched_installed_slug,
            matched_installed_path=matched_installed_path,
            installed_path=installed_path,
            audit_status=audit_status,
            audit_verdict=audit_verdict,
            reason=reason,
        )
