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
