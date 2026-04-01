from __future__ import annotations

import json

import pytest

from haotian.services.classification_artifact_service import ClassificationArtifactService


def test_write_classification_input_contains_repo_metadata(tmp_path) -> None:
    service = ClassificationArtifactService(base_dir=tmp_path)

    path = service.write_classification_input(
        report_date="2026-03-23",
        items=[
            {
                "repo_full_name": "acme/browser-bot",
                "description": "Browser automation agent",
                "candidate_texts": ["Browser automation agent", "Playwright workflows"],
            }
        ],
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["items"][0]["repo_full_name"] == "acme/browser-bot"
    assert payload["taxonomy_path"] == "docs/capability-taxonomy.md"


def test_read_classification_output_rejects_missing_capability_id(tmp_path) -> None:
    path = tmp_path / "classification-output.json"
    path.write_text(
        '[{"repo_full_name":"acme/browser-bot","capabilities":[{"confidence":0.9,"reason":"x","summary":"y","needs_review":false}]}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        ClassificationArtifactService(base_dir=tmp_path).read_classification_output(path)


def test_read_classification_output_rejects_unknown_capability_id(tmp_path) -> None:
    path = tmp_path / "classification-output.json"
    path.write_text(
        '[{"repo_full_name":"acme/browser-bot","capabilities":[{"capability_id":"unknown_skill","confidence":0.9,"reason":"x","summary":"y","needs_review":false}]}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        ClassificationArtifactService(base_dir=tmp_path).read_classification_output(path)


def test_skill_candidate_and_merge_decision_paths_are_date_scoped(tmp_path) -> None:
    service = ClassificationArtifactService(base_dir=tmp_path)

    assert service.skill_candidates_path("2026-03-27") == tmp_path / "2026-03-27" / "skill-candidates.json"
    assert service.skill_merge_decisions_path("2026-03-27") == tmp_path / "2026-03-27" / "skill-merge-decisions.json"


def test_write_skill_candidates_input_uses_skill_decision_contract(tmp_path) -> None:
    service = ClassificationArtifactService(base_dir=tmp_path)

    path = service.write_skill_candidates_input(
        report_date="2026-03-27",
        candidates=[
            {
                "candidate_id": "cand-123",
                "display_name": "agent-builder",
                "repo_full_name": "shareAI-lab/learn-claude-code",
                "relative_root": "skills/agent-builder",
                "files": ["SKILL.md", "references/agent-philosophy.md"],
            }
        ],
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["analysis_format"] == "skill-discovery-v1"
    assert payload["expected_output_filename"] == "skill-merge-decisions.json"
    assert payload["candidates"][0]["candidate_id"] == "cand-123"


def test_read_skill_merge_decisions_returns_valid_records(tmp_path) -> None:
    service = ClassificationArtifactService(base_dir=tmp_path)
    path = service.skill_merge_decisions_path("2026-03-27")
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "report_date": "2026-03-27",
                "decisions": [
                    {
                        "candidate_id": "cand-123",
                        "decision": "accept",
                        "canonical_name": "Agent Builder",
                        "merge_target": "agent-builder",
                        "accepted": True,
                        "reason": "Stable skill package with a clear canonical name.",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    records = service.read_skill_merge_decisions(path)

    assert len(records) == 1
    assert records[0].candidate_id == "cand-123"
    assert records[0].decision == "accept"
    assert records[0].canonical_name == "Agent Builder"
    assert records[0].merge_target == "agent-builder"
    assert records[0].accepted is True
    assert records[0].reason == "Stable skill package with a clear canonical name."


def test_read_skill_merge_decisions_rejects_duplicate_candidate_ids(tmp_path) -> None:
    service = ClassificationArtifactService(base_dir=tmp_path)
    path = service.skill_merge_decisions_path("2026-03-27")
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "report_date": "2026-03-27",
                "decisions": [
                    {
                        "candidate_id": "cand-123",
                        "decision": "accept",
                        "canonical_name": "Agent Builder",
                        "merge_target": "agent-builder",
                        "accepted": True,
                        "reason": "First entry.",
                    },
                    {
                        "candidate_id": "cand-123",
                        "decision": "accept",
                        "canonical_name": "Agent Builder v2",
                        "merge_target": "agent-builder-v2",
                        "accepted": True,
                        "reason": "Duplicate entry.",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        service.read_skill_merge_decisions(path)


def test_read_skill_merge_decisions_requires_unique_candidate_ids(tmp_path) -> None:
    path = tmp_path / "skill-merge-decisions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "candidate_id": "cand-123",
                    "decision": "install",
                    "canonical_name": "agent-builder",
                    "merge_target": None,
                    "accepted": True,
                    "reason": "完整 skill 包，可直接安装。",
                },
                {
                    "candidate_id": "cand-123",
                    "decision": "merge",
                    "canonical_name": "agent-builder",
                    "merge_target": "agent-builder",
                    "accepted": True,
                    "reason": "重复 candidate_id。",
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        ClassificationArtifactService(base_dir=tmp_path).read_skill_merge_decisions(path)
