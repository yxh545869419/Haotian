from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from haotian.services.skill_audit_service import SkillAuditService


def test_skill_audit_service_parses_clean_result(monkeypatch, tmp_path) -> None:
    script_path = tmp_path / "audit_skill.py"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    stdout = json.dumps(
        {
            "target": str(candidate),
            "generated_at": "2026-03-25T00:00:00+00:00",
            "skill_count": 1,
            "overall_score": 0,
            "overall_verdict": "CLEAN",
            "reports": [],
        }
    )

    def fake_run(command, check, capture_output, text):  # noqa: ANN001
        assert command == [sys.executable, str(script_path), "scan", "--json", str(candidate)]
        assert check is False
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = SkillAuditService(script_path=script_path).audit(candidate)

    assert result.status == "clean"
    assert result.is_installable() is True
    assert result.overall_verdict == "CLEAN"
    assert result.findings == ()
    assert result.target == candidate.resolve()


def test_skill_audit_service_rejects_non_clean_results(monkeypatch, tmp_path) -> None:
    script_path = tmp_path / "audit_skill.py"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    stdout = json.dumps(
        {
            "target": str(candidate),
            "generated_at": "2026-03-25T00:00:00+00:00",
            "skill_count": 1,
            "overall_score": 18,
            "overall_verdict": "BLOCK",
            "reports": [
                {
                    "name": "candidate",
                    "path": str(candidate),
                    "verdict": "BLOCK",
                    "score": 18,
                    "files_scanned": 1,
                    "severity_counts": {"CRITICAL": 1},
                    "external_urls": [],
                    "findings": [
                        {
                            "rule_id": "prompt-injection",
                            "severity": "CRITICAL",
                            "file": "SKILL.md",
                            "line": 1,
                            "message": "Prompt-injection or rule-override text detected",
                            "evidence": "ignore previous instructions",
                        }
                    ],
                }
            ],
        }
    )

    def fake_run(command, check, capture_output, text):  # noqa: ANN001
        return subprocess.CompletedProcess(command, 2, stdout=stdout, stderr="blocked")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = SkillAuditService(script_path=script_path).audit(candidate)

    assert result.status == "block"
    assert result.is_installable() is False
    assert result.overall_verdict == "BLOCK"


@pytest.mark.parametrize("verdict", ["LOW", "OBSERVE"])
def test_skill_audit_service_maps_low_style_verdicts_to_review_status(monkeypatch, tmp_path, verdict) -> None:
    script_path = tmp_path / "audit_skill.py"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    stdout = json.dumps(
        {
            "target": str(candidate),
            "generated_at": "2026-03-25T00:00:00+00:00",
            "skill_count": 1,
            "overall_score": 3,
            "overall_verdict": verdict,
            "reports": [],
        }
    )

    def fake_run(command, check, capture_output, text):  # noqa: ANN001
        return subprocess.CompletedProcess(command, 1, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = SkillAuditService(script_path=script_path).audit(candidate)

    assert result.status == "review"
    assert result.is_installable() is False
    assert result.overall_verdict == verdict


def test_skill_audit_service_normalizes_launch_failure(monkeypatch, tmp_path) -> None:
    script_path = tmp_path / "audit_skill.py"
    candidate = tmp_path / "candidate"
    candidate.mkdir()

    def fake_run(command, check, capture_output, text):  # noqa: ANN001
        raise FileNotFoundError("missing python")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = SkillAuditService(script_path=script_path).audit(candidate)

    assert result.status == "error"
    assert result.overall_verdict == "ERROR"
    assert result.returncode == -1
    assert "missing python" in result.stderr
    assert result.raw_payload is None


def test_skill_audit_service_degrades_gracefully_for_malformed_report_values(
    monkeypatch, tmp_path
) -> None:
    script_path = tmp_path / "audit_skill.py"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    stdout = json.dumps(
        {
            "target": str(candidate),
            "generated_at": "2026-03-25T00:00:00+00:00",
            "skill_count": "2",
            "overall_score": "7",
            "overall_verdict": "REVIEW",
            "reports": [
                {
                    "name": "candidate",
                    "path": str(candidate),
                    "verdict": "REVIEW",
                    "score": "not-a-number",
                    "files_scanned": "also-bad",
                    "severity_counts": {"LOW": "oops"},
                    "external_urls": ["https://example.com"],
                    "findings": [
                        {
                            "rule_id": "broken-field",
                            "severity": "LOW",
                            "file": "SKILL.md",
                            "line": "NaN",
                            "message": "Bad line number",
                            "evidence": 42,
                        }
                    ],
                }
            ],
        }
    )

    def fake_run(command, check, capture_output, text):  # noqa: ANN001
        return subprocess.CompletedProcess(command, 1, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = SkillAuditService(script_path=script_path).audit(candidate)

    assert result.status == "review"
    assert result.overall_score == 7
    assert result.skill_count == 2
    assert result.reports[0].score == 0
    assert result.reports[0].files_scanned == 0
    assert result.reports[0].severity_counts == {"LOW": 0}
    assert result.reports[0].findings[0].line == 0
    assert result.reports[0].findings[0].evidence == "42"
