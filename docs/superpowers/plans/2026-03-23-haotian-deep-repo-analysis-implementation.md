# Haotian Deep Repository Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Haotian from metadata-level repository classification into a temporary-clone, evidence-driven analysis pipeline that inspects bounded local repository copies, deletes them after probing, and produces evidence-backed Chinese reports.

**Architecture:** Keep Python as the deterministic execution engine for cloning, probing, cleanup, persistence, and report generation. Add a bounded repository-analysis layer that temporarily clones repositories, extracts structured evidence from `skill*`, `*.md`, config files, and representative source files, persists per-repo analysis snapshots, and feeds those snapshots into the existing Codex taxonomy classification workflow. Reports should render both capability conclusions and the evidence depth or fallback status behind them.

**Tech Stack:** Python 3.11+, pytest, SQLite, git CLI, pathlib, subprocess, JSON/Markdown artifacts, existing Haotian services (`orchestration_service`, `report_service`, `classification_artifact_service`)

---

## Planned File Structure

- Create: `src/haotian/services/repository_workspace_service.py`
- Create: `src/haotian/services/repository_probe_service.py`
- Create: `src/haotian/services/repository_analysis_service.py`
- Modify: `src/haotian/config.py`
- Modify: `src/haotian/db/schema.py`
- Modify: `src/haotian/services/orchestration_service.py`
- Modify: `src/haotian/runner.py`
- Modify: `src/haotian/services/report_service.py`
- Modify: `src/haotian/services/__init__.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `SKILL.md`
- Modify: `docs/architecture.md`
- Modify: `docs/ops.md`
- Create: `tests/test_repository_workspace_service.py`
- Create: `tests/test_repository_probe_service.py`
- Create: `tests/fixtures/repos/skill-heavy/`
- Create: `tests/fixtures/repos/agent-heavy/`
- Create: `tests/fixtures/repos/docs-heavy/`
- Modify: `tests/test_config.py`
- Modify: `tests/test_orchestration_service.py`
- Modify: `tests/test_runner.py`
- Modify: `tests/test_report_service.py`

**Important working-tree note:** The repository is already dirty before implementation begins. Preserve the current uncommitted changes in `README.md`, `SKILL.md`, `docs/ops.md`, `src/haotian/services/report_service.py`, `tests/test_orchestration_service.py`, and `tests/test_report_service.py`. Do not revert or overwrite them blindly while implementing this plan. Prefer isolating execution in a fresh worktree before touching code.

### Task 1: Add Temporary Clone Settings And Workspace Lifecycle

**Files:**
- Create: `src/haotian/services/repository_workspace_service.py`
- Modify: `src/haotian/config.py`
- Modify: `.env.example`
- Modify: `tests/test_config.py`
- Test: `tests/test_repository_workspace_service.py`

- [ ] **Step 1: Write the failing settings and cleanup tests**

```python
def test_settings_include_repo_analysis_defaults(monkeypatch) -> None:
    monkeypatch.delenv("TMP_REPO_DIR", raising=False)
    monkeypatch.delenv("MAX_REPO_PROBE_FILES", raising=False)
    monkeypatch.delenv("MAX_REPO_PROBE_FILE_BYTES", raising=False)
    monkeypatch.delenv("MAX_DEEP_ANALYSIS_REPOS", raising=False)

    settings = Settings.from_env()

    assert settings.tmp_repo_dir == Path("data/tmp/repos")
    assert settings.max_repo_probe_files == 16
    assert settings.max_repo_probe_file_bytes == 24000
    assert settings.max_deep_analysis_repos == 12
```

```python
def test_workspace_cleanup_deletes_cloned_directory(tmp_path) -> None:
    source = init_local_git_repo(tmp_path / "source")
    service = RepositoryWorkspaceService(base_dir=tmp_path / "tmp-repos")

    workspace = service.clone_repo(repo_full_name="acme/demo", repo_url=str(source))
    assert workspace.path.exists()

    service.cleanup_repo(workspace)

    assert not workspace.path.exists()
```

- [ ] **Step 2: Run the focused config and workspace tests to verify they fail**

Run: `python -m pytest -q tests/test_config.py tests/test_repository_workspace_service.py -v`
Expected: FAIL because the new settings and workspace service do not exist yet.

- [ ] **Step 3: Implement bounded workspace configuration and clone cleanup**

Add new config fields with sane defaults:

```python
class Settings(BaseModel):
    tmp_repo_dir: Path = Field(default=Path("data/tmp/repos"), alias="TMP_REPO_DIR")
    max_repo_probe_files: int = Field(default=16, alias="MAX_REPO_PROBE_FILES")
    max_repo_probe_file_bytes: int = Field(default=24000, alias="MAX_REPO_PROBE_FILE_BYTES")
    max_evidence_snippets: int = Field(default=6, alias="MAX_EVIDENCE_SNIPPETS")
    max_deep_analysis_repos: int = Field(default=12, alias="MAX_DEEP_ANALYSIS_REPOS")
```

Implement a focused workspace service:

```python
@dataclass(frozen=True, slots=True)
class ClonedWorkspace:
    repo_full_name: str
    path: Path


class RepositoryWorkspaceService:
    def clone_repo(self, *, repo_full_name: str, repo_url: str) -> ClonedWorkspace:
        target = self.workspace_path(repo_full_name)
        subprocess.run(["git", "clone", "--depth", "1", repo_url, str(target)], check=True)
        return ClonedWorkspace(repo_full_name=repo_full_name, path=target)

    def cleanup_repo(self, workspace: ClonedWorkspace) -> None:
        shutil.rmtree(workspace.path, ignore_errors=False)
```

- [ ] **Step 4: Re-run the focused tests**

Run: `python -m pytest -q tests/test_config.py tests/test_repository_workspace_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/haotian/config.py src/haotian/services/repository_workspace_service.py .env.example tests/test_config.py tests/test_repository_workspace_service.py
git commit -m "feat: add temporary repo workspace lifecycle"
```

### Task 2: Build The Layered Repository Probe Engine

**Files:**
- Create: `src/haotian/services/repository_probe_service.py`
- Create: `tests/test_repository_probe_service.py`
- Create: `tests/fixtures/repos/skill-heavy/SKILL.md`
- Create: `tests/fixtures/repos/skill-heavy/docs/guide.md`
- Create: `tests/fixtures/repos/skill-heavy/agents/browser/notes.md`
- Create: `tests/fixtures/repos/skill-heavy/skills/browser/SKILL.md`
- Create: `tests/fixtures/repos/skill-heavy/prompts/system/agent.md`
- Create: `tests/fixtures/repos/agent-heavy/pyproject.toml`
- Create: `tests/fixtures/repos/agent-heavy/src/agent/main.py`
- Create: `tests/fixtures/repos/agent-heavy/src/agent/workflow.py`
- Create: `tests/fixtures/repos/docs-heavy/README.md`
- Create: `tests/fixtures/repos/docs-heavy/docs/methodology.md`
- Create: `tests/fixtures/repos/no-signal/NOTICE.txt`

- [ ] **Step 1: Write the failing probe tests for `skill*`, `*.md`, and representative code selection**

```python
def test_probe_prioritizes_skill_and_markdown_files(fixtures_dir) -> None:
    repo_path = fixtures_dir / "skill-heavy"
    result = RepositoryProbeService(max_files=16, max_file_bytes=24000).probe(repo_path)

    assert "SKILL.md" in result.matched_files
    assert "docs/guide.md" in result.matched_files
    assert "agents/browser/notes.md" in result.matched_files
    assert "skills/browser/SKILL.md" in result.matched_files
    assert "prompts/system/agent.md" in result.matched_files
    assert "skill*" in result.matched_keywords
    assert "*.md" in result.matched_keywords
```

```python
def test_probe_extracts_representative_source_files_only(fixtures_dir) -> None:
    repo_path = fixtures_dir / "agent-heavy"
    result = RepositoryProbeService(max_files=4, max_file_bytes=2000).probe(repo_path)

    assert "src/agent/main.py" in result.matched_files
    assert "src/agent/workflow.py" in result.matched_files
    assert any(snippet.path == "src/agent/workflow.py" for snippet in result.evidence_snippets)
    assert result.analysis_limits == ()
```

```python
def test_probe_records_budget_limits(fixtures_dir) -> None:
    repo_path = fixtures_dir / "docs-heavy"
    result = RepositoryProbeService(max_files=1, max_file_bytes=120).probe(repo_path)

    assert result.analysis_limits
```

```python
def test_probe_truncates_evidence_snippets(fixtures_dir) -> None:
    repo_path = fixtures_dir / "docs-heavy"
    result = RepositoryProbeService(max_files=4, max_file_bytes=80).probe(repo_path)

    assert all(len(snippet.excerpt) <= 80 for snippet in result.evidence_snippets)
```

```python
def test_probe_handles_repository_with_no_deep_signals(fixtures_dir) -> None:
    repo_path = fixtures_dir / "no-signal"
    result = RepositoryProbeService(max_files=8, max_file_bytes=2000).probe(repo_path)

    assert result.matched_files == ()
    assert result.evidence_snippets == ()
```

- [ ] **Step 2: Run the probe tests and confirm they fail**

Run: `python -m pytest -q tests/test_repository_probe_service.py -v`
Expected: FAIL because the probe service and fixture repositories do not exist yet.

- [ ] **Step 3: Implement the probe service with a strict two-layer strategy**

Use focused dataclasses and path-matching helpers:

```python
@dataclass(frozen=True, slots=True)
class EvidenceSnippet:
    path: str
    excerpt: str
    why_it_matters: str


@dataclass(frozen=True, slots=True)
class RepositoryProbeResult:
    analysis_depth: str
    root_files: tuple[str, ...]
    matched_files: tuple[str, ...]
    matched_keywords: tuple[str, ...]
    architecture_signals: tuple[str, ...]
    probe_summary: str
    evidence_snippets: tuple[EvidenceSnippet, ...]
    analysis_limits: tuple[str, ...]
```

Priority patterns must include:

```python
FIRST_PASS_PATTERNS = ("README*", "*.md", "skill*", "package.json", "pyproject.toml", "requirements.txt", "Dockerfile")
SECOND_PASS_PATTERNS = ("skill*", "*.md", "main*", "app*", "server*", "cli*", "agent*", "workflow*", "orchestr*", "tool*", "browser*", "rag*", "retriev*", "codegen*")
```

The implementation must match recursively under:
- `docs/**/*.md`
- `agents/**/*.md`
- `skills/**/*.md`
- `prompts/**/*.md`

- [ ] **Step 4: Re-run the probe tests**

Run: `python -m pytest -q tests/test_repository_probe_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/haotian/services/repository_probe_service.py tests/test_repository_probe_service.py tests/fixtures/repos/skill-heavy tests/fixtures/repos/agent-heavy tests/fixtures/repos/docs-heavy
git commit -m "feat: add layered repository probe engine"
```

### Task 3: Compose Clone, Probe, Fallback, And Snapshot Persistence

**Files:**
- Create: `src/haotian/services/repository_analysis_service.py`
- Modify: `src/haotian/db/schema.py`
- Modify: `src/haotian/services/orchestration_service.py`
- Modify: `src/haotian/runner.py`
- Modify: `tests/test_orchestration_service.py`
- Modify: `tests/test_runner.py`

- [ ] **Step 1: Write the failing orchestration tests for deep-analysis evidence and fallback**

```python
def test_build_classification_input_includes_deep_analysis_fields(tmp_path) -> None:
    service = build_service(
        tmp_path,
        analysis_service=StubRepositoryAnalysisService(
            analysis_depth="deep",
            clone_strategy="git_depth_1",
            clone_started=True,
            analysis_completed=True,
            cleanup_attempted=True,
            cleanup_required=True,
            matched_files=("SKILL.md", "docs/guide.md"),
            matched_keywords=("skill*", "*.md"),
            root_files=("README.md", "SKILL.md"),
            architecture_signals=("skill_package",),
            probe_summary="Repository exposes skill metadata and browser docs.",
            analysis_limits=(),
            cleanup_completed=True,
            fallback_used=False,
        ),
    )

    result = service.build_classification_input(date(2026, 3, 20))
    payload = json.loads(result.classification_input_path.read_text(encoding="utf-8"))
    item = payload["items"][0]

    assert item["analysis_depth"] == "deep"
    assert item["clone_strategy"] == "git_depth_1"
    assert item["clone_started"] is True
    assert item["analysis_completed"] is True
    assert item["cleanup_attempted"] is True
    assert item["cleanup_required"] is True
    assert item["matched_files"] == ["SKILL.md", "docs/guide.md"]
    assert item["matched_keywords"] == ["skill*", "*.md"]
    assert item["root_files"] == ["README.md", "SKILL.md"]
    assert item["architecture_signals"] == ["skill_package"]
    assert item["probe_summary"] == "Repository exposes skill metadata and browser docs."
    assert item["analysis_limits"] == []
    assert item["cleanup_completed"] is True
    assert item["fallback_used"] is False
```

```python
def test_build_classification_input_marks_fallback_when_clone_fails(tmp_path) -> None:
    service = build_service(
        tmp_path,
        analysis_service=FailingRepositoryAnalysisService(),
    )

    result = service.build_classification_input(date(2026, 3, 20))
    payload = json.loads(result.classification_input_path.read_text(encoding="utf-8"))

    assert payload["items"][0]["analysis_depth"] == "fallback"
    assert payload["items"][0]["fallback_used"] is True
```

```python
def test_build_classification_input_marks_clone_failure_before_workspace_assignment(tmp_path) -> None:
    service = build_service(
        tmp_path,
        analysis_service=CloneFailsBeforeWorkspaceService(),
    )

    result = service.build_classification_input(date(2026, 3, 20))
    payload = json.loads(result.classification_input_path.read_text(encoding="utf-8"))

    item = payload["items"][0]
    assert item["clone_started"] is False
    assert item["cleanup_attempted"] is False
    assert item["cleanup_completed"] is False
    assert item["fallback_used"] is True
```

- [ ] **Step 2: Run the orchestration and runner tests to verify they fail**

Run: `python -m pytest -q tests/test_orchestration_service.py tests/test_runner.py -v`
Expected: FAIL because orchestration does not yet know how to clone, probe, persist analysis snapshots, or summarize fallback counts.

- [ ] **Step 3: Add a repository-analysis composition service and snapshot table**

Create a repository-analysis service that wraps workspace + probe + fallback:

```python
class RepositoryAnalysisService:
    def analyze_repository(self, *, repo_full_name: str, repo_url: str, description: str | None) -> RepositoryAnalysisResult:
        workspace = None
        try:
            workspace = self.workspace_service.clone_repo(repo_full_name=repo_full_name, repo_url=repo_url)
            probe = self.probe_service.probe(workspace.path)
            return RepositoryAnalysisResult.from_probe(probe, cleanup_required=True)
        except Exception:
            return RepositoryAnalysisResult.fallback(description=description)
        finally:
            if workspace is not None:
                self.workspace_service.cleanup_repo(workspace)
```

Add a new SQLite table to persist per-repo analysis evidence:

```sql
CREATE TABLE IF NOT EXISTS repo_analysis_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    repo_full_name TEXT NOT NULL,
    analysis_depth TEXT NOT NULL,
    clone_strategy TEXT NOT NULL,
    clone_started INTEGER NOT NULL DEFAULT 0,
    analysis_completed INTEGER NOT NULL DEFAULT 0,
    cleanup_attempted INTEGER NOT NULL DEFAULT 0,
    cleanup_required INTEGER NOT NULL DEFAULT 1,
    cleanup_completed INTEGER NOT NULL DEFAULT 0,
    fallback_used INTEGER NOT NULL DEFAULT 0,
    root_files_json TEXT NOT NULL,
    matched_files_json TEXT NOT NULL,
    matched_keywords_json TEXT NOT NULL,
    architecture_signals_json TEXT NOT NULL,
    probe_summary TEXT NOT NULL,
    evidence_snippets_json TEXT NOT NULL,
    analysis_limits_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_date, repo_full_name)
);
```

- [ ] **Step 4: Integrate deep-analysis snapshots into `build_classification_input` and runner summaries**

`OrchestrationService.build_classification_input()` should:
- call `RepositoryAnalysisService.analyze_repository()`
- persist `repo_analysis_snapshots`
- add deep-analysis fields to every `classification-input.json` item
- enforce `max_deep_analysis_repos` and mark over-budget repositories as fallback with an `analysis_limits` budget note

`run_once()` should add summary counts such as:

```python
{
    "deep_analyzed_repos": 12,
    "fallback_repos": 3,
    "skipped_due_to_budget": 4,
    "cleanup_warnings": 0,
}
```

- [ ] **Step 5: Re-run the orchestration and runner tests**

Run: `python -m pytest -q tests/test_orchestration_service.py tests/test_runner.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/haotian/services/repository_analysis_service.py src/haotian/db/schema.py src/haotian/services/orchestration_service.py src/haotian/runner.py tests/test_orchestration_service.py tests/test_runner.py
git commit -m "feat: integrate deep repo analysis into staging"
```

### Task 4: Render Evidence And Fallback State In Reports

**Files:**
- Modify: `src/haotian/services/report_service.py`
- Modify: `tests/test_report_service.py`

- [ ] **Step 1: Write the failing report tests for analysis depth, matched files, and evidence snippets**

```python
def test_report_service_renders_deep_analysis_evidence(tmp_path) -> None:
    seed_repo_analysis_snapshot(
        database_url,
        repo_full_name="acme/browser-bot",
        analysis_depth="deep",
        matched_files=["SKILL.md", "src/agent/workflow.py"],
        evidence_snippets=[
            {"path": "SKILL.md", "excerpt": "Run browser workflows", "why_it_matters": "Shows skill-driven automation."}
        ],
        fallback_used=False,
        cleanup_completed=True,
    )

    content = ReportService(database_url=database_url, report_dir=tmp_path / "reports").generate_daily_report("2026-03-20").read_text(encoding="utf-8")

    assert "分析深度：deep" in content
    assert "命中文件：`SKILL.md`, `src/agent/workflow.py`" in content
    assert "关键证据：`SKILL.md` - Run browser workflows" in content
```

```python
def test_report_service_marks_fallback_analysis(tmp_path) -> None:
    seed_repo_analysis_snapshot(
        database_url,
        repo_full_name="acme/docs-only",
        analysis_depth="fallback",
        matched_files=["README.md"],
        evidence_snippets=[],
        fallback_used=True,
        cleanup_completed=True,
    )

    content = ReportService(database_url=database_url, report_dir=tmp_path / "reports").generate_daily_report("2026-03-20").read_text(encoding="utf-8")
    assert "分析深度受限：是" in content
```

```python
def test_report_service_includes_deep_analysis_fields_in_json(tmp_path) -> None:
    seed_repo_analysis_snapshot(
        database_url,
        repo_full_name="acme/browser-bot",
        analysis_depth="deep",
        matched_files=["SKILL.md"],
        evidence_snippets=[
            {"path": "SKILL.md", "excerpt": "Run browser workflows", "why_it_matters": "Shows skill-driven automation."}
        ],
        fallback_used=False,
        cleanup_completed=True,
    )

    payload = json.loads(
        ReportService(database_url=database_url, report_dir=tmp_path / "reports")
        .generate_daily_report_json("2026-03-20")
        .read_text(encoding="utf-8")
    )

    item = payload["sections"]["enhancement_candidates"][0]
    assert item["analysis_depth"] == "deep"
    assert item["matched_files"] == ["SKILL.md"]
    assert item["fallback_used"] is False
    assert item["cleanup_completed"] is True
    assert item["evidence_snippets"][0]["path"] == "SKILL.md"
```

```python
def test_report_service_tolerates_partial_probe_payload(tmp_path) -> None:
    seed_partial_repo_analysis_snapshot(database_url, repo_full_name="acme/partial")

    payload = json.loads(
        ReportService(database_url=database_url, report_dir=tmp_path / "reports")
        .generate_daily_report_json("2026-03-20")
        .read_text(encoding="utf-8")
    )

    assert payload["report_date"] == "2026-03-20"
```

- [ ] **Step 2: Run the focused report tests and confirm they fail**

Run: `python -m pytest -q tests/test_report_service.py -v`
Expected: FAIL because reports do not yet join or render repository analysis evidence.

- [ ] **Step 3: Extend report aggregation to join `repo_analysis_snapshots`**

Add report-level evidence fields to the rendered item payload:

```python
{
    "analysis_depth": "deep",
    "matched_files": ["SKILL.md", "src/agent/workflow.py"],
    "evidence_snippets": [
        {"path": "SKILL.md", "excerpt": "Run browser workflows", "why_it_matters": "Shows skill-driven automation."}
    ],
    "fallback_used": False,
    "cleanup_completed": True,
}
```

Markdown sections should render:

```text
- 分析深度：deep
- 分析深度受限：否
- 命中文件：`SKILL.md`, `src/agent/workflow.py`
- 关键证据：`SKILL.md` - Run browser workflows
```

JSON output must also carry:

```json
{
  "analysis_depth": "deep",
  "matched_files": ["SKILL.md"],
  "evidence_snippets": [
    {"path": "SKILL.md", "excerpt": "Run browser workflows", "why_it_matters": "Shows skill-driven automation."}
  ],
  "fallback_used": false,
  "cleanup_completed": true
}
```

- [ ] **Step 4: Re-run the focused report tests**

Run: `python -m pytest -q tests/test_report_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/haotian/services/report_service.py tests/test_report_service.py
git commit -m "feat: render deep analysis evidence in reports"
```

### Task 5: Update Skill Instructions, Docs, And Runtime Knobs

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/ops.md`
- Modify: `.env.example`

- [ ] **Step 1: Write the failing documentation checks**

Run:

```bash
rg -n "TMP_REPO_DIR|MAX_REPO_PROBE_FILES|analysis_depth|evidence_snippets|临时 clone|分析后删除" SKILL.md README.md docs .env.example
```

Expected: missing matches for the new deep-analysis workflow wording.

- [ ] **Step 2: Update `SKILL.md` to require evidence-aware classification**

The skill must instruct Codex to:
- read `analysis_depth`, `matched_files`, `probe_summary`, and `evidence_snippets`
- prefer concrete repository evidence over README-only claims
- continue writing Chinese `reason` and `summary`
- note when an item came from fallback analysis

- [ ] **Step 3: Update runtime docs and example env vars**

Document the new knobs:

```env
TMP_REPO_DIR=./data/tmp/repos
MAX_REPO_PROBE_FILES=16
MAX_REPO_PROBE_FILE_BYTES=24000
MAX_EVIDENCE_SNIPPETS=6
MAX_DEEP_ANALYSIS_REPOS=12
```

README, architecture, and ops docs must explain:
- temporary local clone
- bounded probing
- analysis snapshot persistence
- clone deletion after analysis
- fallback mode
- evidence-backed report sections

- [ ] **Step 4: Re-run the documentation checks**

Run:

```bash
rg -n "TMP_REPO_DIR|MAX_REPO_PROBE_FILES|analysis_depth|evidence_snippets|临时 clone|分析后删除" SKILL.md README.md docs .env.example
```

Expected: matches exist in the intended documentation files.

- [ ] **Step 5: Commit**

```bash
git add SKILL.md README.md docs/architecture.md docs/ops.md .env.example
git commit -m "docs: describe deep repository analysis workflow"
```

### Task 6: Full Verification, Smoke Test, And Cleanup Review

**Files:**
- Review: repository-wide
- Test: `tests/`

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass, including new workspace, probe, orchestration, runner, and report coverage.

- [ ] **Step 2: Run a deterministic fixture-backed end-to-end verification**

Run: `python -m pytest -q tests/test_runner.py::test_runner_stages_then_finalizes_reports -v`
Expected: PASS with a deterministic fixture-backed flow that verifies staging, finalization, and report generation without depending on live GitHub state.

- [ ] **Step 3: Inspect the staged artifact and confirm deep-analysis evidence is present**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("data/runs/2026-03-24/classification-input.json").read_text(encoding="utf-8"))
item = payload["items"][0]
print(item["analysis_depth"])
print(item["clone_strategy"])
print(item["clone_started"])
print(item["analysis_completed"])
print(item["cleanup_attempted"])
print(item["matched_files"][:3])
print(item["cleanup_completed"])
PY
```

Expected: prints non-empty deep-analysis fields without raising `KeyError`.

- [ ] **Step 4: Run an optional live smoke test only after deterministic verification passes**

Run: `python start_haotian.py --date 2026-03-24`
Expected: either a staged summary or a completed summary. If network conditions or remote rate limits interfere, record that limitation explicitly instead of treating it as the primary verification gate.

- [ ] **Step 5: Review git state for accidental leftovers and temp-directory residue**

Run:

```bash
git status --short
git diff --stat
python - <<'PY'
from pathlib import Path
tmp_root = Path("data/tmp/repos")
print(tmp_root.exists(), list(tmp_root.glob("*"))[:5] if tmp_root.exists() else [])
PY
```

Expected: only intended source/doc/test changes remain, and no repository clone residue is left behind after the smoke test.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "test: verify deep repo analysis pipeline"
```
