"""Read/write helpers for staged Codex classification artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from haotian.analyzers.capability_normalizer import CapabilityNormalizer

SKILL_SYNC_ACTIONS = (
    "aligned_existing",
    "installed_new",
    "discarded_non_integrable",
    "blocked_audit_failure",
    "blocked_ambiguous_match",
    "rolled_back_install_failure",
)


@dataclass(frozen=True, slots=True)
class ClassifiedCapabilityRecord:
    """One capability classification produced by Codex."""

    capability_id: str
    confidence: float
    reason: str
    summary: str
    needs_review: bool
    source_label: str = "codex"


@dataclass(frozen=True, slots=True)
class RepoClassificationRecord:
    """Classified capabilities for a single repository."""

    repo_full_name: str
    capabilities: tuple[ClassifiedCapabilityRecord, ...]


@dataclass(frozen=True, slots=True)
class SkillMergeDecisionRecord:
    """Landing-stage Codex decision for one staged skill candidate."""

    candidate_id: str
    decision: str
    canonical_name: str
    merge_target: str | None
    accepted: bool
    reason: str


class ClassificationArtifactService:
    """Manage staged input/output artifacts for the Codex classification step."""

    def __init__(
        self,
        *,
        base_dir: Path | str = Path("data/runs"),
        taxonomy_path: str = "docs/capability-taxonomy.md",
        normalizer: CapabilityNormalizer | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.taxonomy_path = taxonomy_path
        self.normalizer = normalizer or CapabilityNormalizer()

    def run_dir(self, report_date: str) -> Path:
        target = self.base_dir / report_date
        target.mkdir(parents=True, exist_ok=True)
        return target

    def classification_input_path(self, report_date: str) -> Path:
        return self.run_dir(report_date) / "classification-input.json"

    def classification_output_path(self, report_date: str) -> Path:
        return self.run_dir(report_date) / "classification-output.json"

    def run_summary_path(self, report_date: str) -> Path:
        return self.run_dir(report_date) / "run-summary.json"

    def capability_audit_path(self, report_date: str) -> Path:
        return self.run_dir(report_date) / "capability-audit.json"

    def taxonomy_gap_candidates_path(self, report_date: str) -> Path:
        return self.run_dir(report_date) / "taxonomy-gap-candidates.json"

    def skill_candidates_path(self, report_date: str) -> Path:
        return self.run_dir(report_date) / "skill-candidates.json"

    def skill_merge_decisions_path(self, report_date: str) -> Path:
        return self.run_dir(report_date) / "skill-merge-decisions.json"

    def skill_sync_report_path(self, report_date: str) -> Path:
        return self.run_dir(report_date) / "skill-sync-report.json"

    @staticmethod
    def default_skill_sync_summary(
        *,
        config_ready: bool = False,
        candidate_count: int = 0,
        action_count: int = 0,
    ) -> dict[str, object]:
        summary: dict[str, object] = {
            "config_ready": config_ready,
            "candidate_count": candidate_count,
            "action_count": action_count,
        }
        for action in SKILL_SYNC_ACTIONS:
            summary[action] = 0
        return summary

    @classmethod
    def empty_skill_sync_report_payload(
        cls,
        report_date: str,
        *,
        config_ready: bool = False,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "report_date": report_date,
            "summary": cls.default_skill_sync_summary(config_ready=config_ready),
            "actions": [],
        }
    def write_classification_input(self, *, report_date: str, items: list[dict[str, object]]) -> Path:
        target = self.classification_input_path(report_date)
        payload = {
            "schema_version": 1,
            "analysis_format": "deep-repo-v1",
            "report_date": report_date,
            "taxonomy_path": self.taxonomy_path,
            "expected_output_filename": "classification-output.json",
            "items": items,
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def write_skill_candidates_input(self, *, report_date: str, candidates: list[dict[str, object]]) -> Path:
        target = self.skill_candidates_path(report_date)
        payload = {
            "schema_version": 1,
            "analysis_format": "skill-discovery-v1",
            "report_date": report_date,
            "expected_output_filename": "skill-merge-decisions.json",
            "candidates": candidates,
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def is_current_prepare_artifact(self, report_date: str) -> bool:
        path = self.classification_input_path(report_date)
        if not path.exists():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False
        if payload.get("analysis_format") == "deep-repo-v1":
            return True
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            return False
        return all(isinstance(item, dict) and "analysis_depth" in item for item in items)

    def write_run_summary(self, *, report_date: str, summary: dict[str, object]) -> Path:
        target = self.run_summary_path(report_date)
        target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def write_json_artifact(self, *, path: Path, payload: object) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def read_classification_input_payload(self, report_date: str) -> dict[str, object]:
        path = self.classification_input_path(report_date)
        if not path.exists():
            raise FileNotFoundError(f"Classification input not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Classification input must be a JSON object.")
        return payload

    def read_classification_input_items(self, report_date: str) -> list[dict[str, object]]:
        payload = self.read_classification_input_payload(report_date)
        items = payload.get("items")
        if not isinstance(items, list):
            raise ValueError("Classification input must include an items array.")
        normalized: list[dict[str, object]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"Classification input item #{index} must be an object.")
            normalized.append(item)
        return normalized

    def read_skill_candidates_payload(self, report_date: str) -> dict[str, object]:
        path = self.skill_candidates_path(report_date)
        if not path.exists():
            raise FileNotFoundError(f"Skill candidates input not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Skill candidates input must be a JSON object.")
        return payload

    def read_skill_candidates_items(self, report_date: str) -> list[dict[str, object]]:
        payload = self.read_skill_candidates_payload(report_date)
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            raise ValueError("Skill candidates input must include a candidates array.")
        normalized: list[dict[str, object]] = []
        for index, item in enumerate(candidates):
            if not isinstance(item, dict):
                raise ValueError(f"Skill candidate #{index} must be an object.")
            normalized.append(item)
        return normalized

    def read_skill_merge_decisions_payload(self, path: Path) -> dict[str, object] | list[object]:
        if not path.exists():
            raise FileNotFoundError(f"Skill merge decisions not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict | list):
            raise ValueError("Skill merge decisions must be a JSON object or array.")
        return payload

    def read_skill_merge_decisions(self, path: Path) -> list[SkillMergeDecisionRecord]:
        payload = self.read_skill_merge_decisions_payload(path)
        raw_items = payload.get("decisions") if isinstance(payload, dict) else payload
        if not isinstance(raw_items, list):
            raise ValueError("Skill merge decisions must include a decisions array.")

        records: list[SkillMergeDecisionRecord] = []
        seen_candidate_ids: set[str] = set()
        for index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, dict):
                raise ValueError(f"Skill merge decision #{index} must be an object.")
            candidate_id = self._require_non_empty_string(raw_item, "candidate_id", index=index)
            if candidate_id in seen_candidate_ids:
                raise ValueError(f"Duplicate skill merge decision for candidate_id '{candidate_id}'.")
            seen_candidate_ids.add(candidate_id)
            decision = self._require_non_empty_string(raw_item, "decision", candidate_id=candidate_id)
            canonical_name = self._require_non_empty_string(raw_item, "canonical_name", candidate_id=candidate_id)
            merge_target = raw_item.get("merge_target")
            if merge_target is not None:
                if not isinstance(merge_target, str) or not merge_target.strip():
                    raise ValueError(f"Skill merge decision '{candidate_id}' merge_target must be null or non-empty string.")
                merge_target = merge_target.strip()
            accepted = raw_item.get("accepted")
            if not isinstance(accepted, bool):
                raise ValueError(f"Skill merge decision '{candidate_id}' must include boolean accepted.")
            reason = self._require_non_empty_string(raw_item, "reason", candidate_id=candidate_id)
            records.append(
                SkillMergeDecisionRecord(
                    candidate_id=candidate_id,
                    decision=decision,
                    canonical_name=canonical_name,
                    merge_target=merge_target,
                    accepted=accepted,
                    reason=reason,
                )
            )
        return records

    def read_classification_output(self, path: Path) -> list[RepoClassificationRecord]:
        if not path.exists():
            raise FileNotFoundError(f"Classification output not found: {path}")

        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Classification output must be a JSON array.")

        records: list[RepoClassificationRecord] = []
        seen_repositories: set[str] = set()
        for index, raw_item in enumerate(payload):
            if not isinstance(raw_item, dict):
                raise ValueError(f"Classification output item #{index} must be an object.")
            repo_full_name = self._require_non_empty_string(raw_item, "repo_full_name", index=index)
            if repo_full_name in seen_repositories:
                raise ValueError(f"Duplicate classification output for repo '{repo_full_name}'.")
            seen_repositories.add(repo_full_name)
            capabilities_raw = raw_item.get("capabilities")
            if not isinstance(capabilities_raw, list):
                raise ValueError(f"Repo '{repo_full_name}' must include a capabilities array.")
            capabilities = tuple(
                self._parse_capability(repo_full_name=repo_full_name, raw_item=item, index=cap_index)
                for cap_index, item in enumerate(capabilities_raw)
            )
            records.append(RepoClassificationRecord(repo_full_name=repo_full_name, capabilities=capabilities))
        return records

    def _parse_capability(
        self,
        *,
        repo_full_name: str,
        raw_item: object,
        index: int,
    ) -> ClassifiedCapabilityRecord:
        if not isinstance(raw_item, dict):
            raise ValueError(f"Capability entry #{index} for repo '{repo_full_name}' must be an object.")
        capability_id = self._require_non_empty_string(raw_item, "capability_id", repo_full_name=repo_full_name, index=index)
        if not self.normalizer.is_known_capability(capability_id):
            raise ValueError(f"Repo '{repo_full_name}' uses unknown capability_id '{capability_id}'.")
        confidence = raw_item.get("confidence")
        if not isinstance(confidence, int | float):
            raise ValueError(f"Repo '{repo_full_name}' capability '{capability_id}' must include numeric confidence.")
        normalized_confidence = round(float(confidence), 2)
        if not 0.0 <= normalized_confidence <= 1.0:
            raise ValueError(f"Repo '{repo_full_name}' capability '{capability_id}' confidence must be within [0, 1].")
        reason = self._require_non_empty_string(raw_item, "reason", repo_full_name=repo_full_name, capability_id=capability_id)
        summary = self._require_non_empty_string(raw_item, "summary", repo_full_name=repo_full_name, capability_id=capability_id)
        needs_review = raw_item.get("needs_review")
        if not isinstance(needs_review, bool):
            raise ValueError(f"Repo '{repo_full_name}' capability '{capability_id}' must include boolean needs_review.")
        source_label = raw_item.get("source_label", "codex")
        if not isinstance(source_label, str) or not source_label.strip():
            raise ValueError(f"Repo '{repo_full_name}' capability '{capability_id}' must include a non-empty source_label.")
        return ClassifiedCapabilityRecord(
            capability_id=capability_id,
            confidence=normalized_confidence,
            reason=reason,
            summary=summary,
            needs_review=needs_review,
            source_label=source_label.strip(),
        )

    @staticmethod
    def _require_non_empty_string(
        raw_item: dict[str, Any],
        field_name: str,
        **context: object,
    ) -> str:
        value = raw_item.get(field_name)
        if not isinstance(value, str) or not value.strip():
            label = ", ".join(f"{key}={value}" for key, value in context.items())
            suffix = f" ({label})" if label else ""
            raise ValueError(f"Missing non-empty string field '{field_name}'{suffix}.")
        return value.strip()
