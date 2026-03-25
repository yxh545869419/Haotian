"""Wrapper around the offline Codex skill auditor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
import sys


@dataclass(frozen=True, slots=True)
class SkillAuditFinding:
    """One finding returned by the skill auditor."""

    rule_id: str
    severity: str
    file: str
    line: int
    message: str
    evidence: str = ""


@dataclass(frozen=True, slots=True)
class SkillAuditReport:
    """One per-skill report entry from the audit JSON."""

    name: str
    path: Path
    verdict: str
    score: int
    files_scanned: int
    severity_counts: dict[str, int]
    external_urls: tuple[str, ...]
    findings: tuple[SkillAuditFinding, ...]


@dataclass(frozen=True, slots=True)
class SkillAuditResult:
    """Normalized wrapper output for install-time decisions."""

    target: Path
    script_path: Path
    command: tuple[str, ...]
    returncode: int
    status: str
    overall_verdict: str
    overall_score: int
    skill_count: int
    generated_at: str
    reports: tuple[SkillAuditReport, ...]
    findings: tuple[SkillAuditFinding, ...]
    stdout: str
    stderr: str
    raw_payload: dict[str, object] | None

    def is_installable(self) -> bool:
        return self.status == "clean" and self.returncode == 0


class SkillAuditService:
    """Run the local skill auditor and normalize its verdict."""

    def __init__(
        self,
        *,
        script_path: Path | str,
        python_executable: str | None = None,
    ) -> None:
        self.script_path = Path(script_path).resolve(strict=False)
        self.python_executable = python_executable or sys.executable

    def audit(self, target: Path | str) -> SkillAuditResult:
        target_path = Path(target).resolve(strict=False)
        command = (
            self.python_executable,
            str(self.script_path),
            "scan",
            "--json",
            str(target_path),
        )
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
        )
        payload = self._parse_payload(completed.stdout)
        status, overall_verdict = self._normalize_status(payload, completed.returncode)
        reports = self._parse_reports(payload)
        findings = tuple(
            finding
            for report in reports
            for finding in report.findings
        )
        return SkillAuditResult(
            target=target_path,
            script_path=self.script_path,
            command=command,
            returncode=completed.returncode,
            status=status,
            overall_verdict=overall_verdict,
            overall_score=int(payload.get("overall_score", 0)) if payload else 0,
            skill_count=int(payload.get("skill_count", 0)) if payload else 0,
            generated_at=str(payload.get("generated_at", "")) if payload else "",
            reports=reports,
            findings=findings,
            stdout=completed.stdout,
            stderr=completed.stderr,
            raw_payload=payload,
        )

    @staticmethod
    def _parse_payload(stdout: str) -> dict[str, object] | None:
        stripped = stdout.strip()
        if not stripped:
            return None
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            return payload
        return None

    @staticmethod
    def _normalize_status(payload: dict[str, object] | None, returncode: int) -> tuple[str, str]:
        verdict = ""
        if payload is not None:
            verdict = str(payload.get("overall_verdict", "")).strip().upper()
        if not verdict:
            if returncode == 0:
                verdict = "CLEAN"
            elif returncode == 1:
                verdict = "REVIEW"
            elif returncode == 2:
                verdict = "BLOCK"
            else:
                verdict = "ERROR"

        status = verdict.lower() if verdict in {"CLEAN", "REVIEW", "BLOCK"} else "error"
        return status, verdict

    @staticmethod
    def _parse_reports(payload: dict[str, object] | None) -> tuple[SkillAuditReport, ...]:
        if payload is None:
            return ()

        reports_raw = payload.get("reports", ())
        if not isinstance(reports_raw, list):
            return ()

        reports: list[SkillAuditReport] = []
        for item in reports_raw:
            if not isinstance(item, dict):
                continue
            findings_raw = item.get("findings", ())
            findings = tuple(
                SkillAuditFinding(
                    rule_id=str(finding.get("rule_id", "")),
                    severity=str(finding.get("severity", "")),
                    file=str(finding.get("file", "")),
                    line=int(finding.get("line", 0) or 0),
                    message=str(finding.get("message", "")),
                    evidence=str(finding.get("evidence", "")),
                )
                for finding in findings_raw
                if isinstance(finding, dict)
            )
            severity_counts_raw = item.get("severity_counts", {})
            severity_counts = (
                {str(key): int(value) for key, value in severity_counts_raw.items()}
                if isinstance(severity_counts_raw, dict)
                else {}
            )
            reports.append(
                SkillAuditReport(
                    name=str(item.get("name", "")),
                    path=Path(str(item.get("path", ""))).resolve(strict=False),
                    verdict=str(item.get("verdict", "")),
                    score=int(item.get("score", 0) or 0),
                    files_scanned=int(item.get("files_scanned", 0) or 0),
                    severity_counts=severity_counts,
                    external_urls=tuple(
                        str(url)
                        for url in item.get("external_urls", ())
                        if isinstance(url, str)
                    ),
                    findings=findings,
                )
            )
        return tuple(reports)
