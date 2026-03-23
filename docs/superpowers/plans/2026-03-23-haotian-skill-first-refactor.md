# Haotian Skill-First Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `Haotian` into a repository-native Codex skill that runs the core capability-intelligence pipeline on demand, persists Markdown and JSON reports, and removes chat/web/CLI/Telegram plus direct OpenAI API dependencies.

**Architecture:** Keep Python as the deterministic local engine for collection, staging, persistence, and report generation. Move taxonomy classification into the Codex skill workflow by generating `classification-input.json`, having the skill produce `classification-output.json`, then ingesting that output back into SQLite and final reports. Replace the current interaction-oriented entrypoints with a stable runner plus root-level skill metadata.

**Tech Stack:** Python 3.11+, setuptools editable installs, pytest, SQLite, JSON/Markdown artifacts, Codex skill metadata (`SKILL.md`, `agents/openai.yaml`)

---

## Planned File Structure

- Keep: `src/haotian/collectors/`, `src/haotian/db/`, `src/haotian/registry/`, `src/haotian/services/diff_service.py`, `src/haotian/services/ingest_service.py`, `src/haotian/services/report_service.py`
- Create: `SKILL.md`
- Create: `agents/openai.yaml`
- Create: `src/haotian/runner.py`
- Create: `src/haotian/services/classification_artifact_service.py`
- Create: `tests/test_runner.py`
- Create: `tests/test_classification_artifact_service.py`
- Modify: `src/haotian/services/orchestration_service.py`
- Modify: `src/haotian/services/report_service.py`
- Modify: `src/haotian/config.py`
- Modify: `src/haotian/main.py`
- Modify: `src/haotian/cli/commands.py`
- Modify: `start_haotian.py`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/ops.md`
- Delete: `src/haotian/webapp/server.py`
- Delete: `src/haotian/services/chat_service.py`
- Delete: `src/haotian/services/cli_chat_service.py`
- Delete: `src/haotian/integrations/telegram_bot.py`
- Delete: `src/haotian/llm/openai_codex.py`
- Delete: `src/haotian/prompts/capability_classification.md`
- Delete or repurpose: `src/haotian/analyzers/capability_classifier.py`
- Delete: `tests/test_chat_service.py`
- Delete: `tests/test_cli_chat_service.py`
- Delete: `tests/test_web_server.py`
- Delete: `tests/test_telegram_bot.py`
- Delete: `tests/test_openai_codex.py`
- Delete or repurpose: `tests/test_capability_classifier.py`

**Important working-tree note:** The repository is already dirty before this refactor begins. Read `git status` first and decide whether the current uncommitted `README.md`, `src/haotian/webapp/server.py`, `src/haotian/services/chat_service.py`, and related test changes should be folded into this refactor or checkpointed separately. Do not blindly revert them.

### Task 1: Establish The Skill Shell And New Execution Surface

**Files:**
- Create: `SKILL.md`
- Create: `agents/openai.yaml`
- Modify: `pyproject.toml`
- Modify: `src/haotian/main.py`
- Modify: `src/haotian/cli/commands.py`
- Modify: `start_haotian.py`
- Test: `tests/test_start_haotian.py`

- [ ] **Step 1: Write the failing test for the new non-chat launcher behavior**

```python
def test_launcher_runs_core_pipeline(monkeypatch) -> None:
    called = {}

    def fake_run(*, report_date=None):
        called["report_date"] = report_date
        return {"markdown_report": "data/reports/2026-03-23.md"}

    monkeypatch.setattr(start_haotian, "run_once", fake_run)
    monkeypatch.setattr(start_haotian.sys, "argv", ["start_haotian.py"])

    start_haotian.main()

    assert called == {"report_date": None}
```

- [ ] **Step 2: Run the focused launcher test to verify it fails**

Run: `python -m pytest -q tests/test_start_haotian.py -v`
Expected: FAIL because the launcher still dispatches `web` / `cli` modes.

- [ ] **Step 3: Implement the minimal skill-facing entry surface**

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Haotian intelligence cycle.")
    parser.add_argument("--date", default=None, help="Optional report date (YYYY-MM-DD).")
    args = parser.parse_args()
    summary = run_once(report_date=args.date)
    print(summary["markdown_report"])
```

- [ ] **Step 4: Create the root skill metadata**

`SKILL.md` should instruct Codex to:
- run the local runner
- read `docs/capability-taxonomy.md`
- read `classification-input.json`
- write `classification-output.json` using a strict schema
- ask Python to ingest and finalize reports

Include a strict JSON output example:

```json
[
  {
    "repo_full_name": "acme/browser-bot",
    "capabilities": [
      {
        "capability_id": "browser_automation",
        "confidence": 0.91,
        "reason": "Repository description and README both describe browser workflow execution.",
        "summary": "Automates browser workflows for websites.",
        "needs_review": false,
        "source_label": "codex"
      }
    ]
  }
]
```

- [ ] **Step 5: Add `agents/openai.yaml` so the repo skill shows up cleanly in Codex UI**

Use values consistent with the skill:

```yaml
display_name: Haotian
short_description: Refresh and classify local AI capability intelligence into reports.
default_prompt: Run the Haotian capability intelligence workflow and summarize the latest report.
```

- [ ] **Step 6: Run launcher tests again**

Run: `python -m pytest -q tests/test_start_haotian.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add SKILL.md agents/openai.yaml pyproject.toml src/haotian/main.py src/haotian/cli/commands.py start_haotian.py tests/test_start_haotian.py
git commit -m "feat: add skill-first runner entrypoints"
```

### Task 2: Stage Classification Input And Validate Codex Output

**Files:**
- Create: `src/haotian/services/classification_artifact_service.py`
- Modify: `src/haotian/services/orchestration_service.py`
- Modify: `src/haotian/analyzers/capability_normalizer.py`
- Delete or repurpose: `src/haotian/analyzers/capability_classifier.py`
- Test: `tests/test_classification_artifact_service.py`
- Test: `tests/test_orchestration_service.py`

- [ ] **Step 1: Write the failing tests for staged classification artifacts**

```python
def test_write_classification_input_contains_repo_metadata(tmp_path):
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
```

```python
def test_read_classification_output_rejects_missing_capability_id(tmp_path):
    path = tmp_path / "classification-output.json"
    path.write_text('[{"repo_full_name":"acme/browser-bot","capabilities":[{"confidence":0.9}]}]', encoding="utf-8")

    with pytest.raises(ValueError):
        ClassificationArtifactService(base_dir=tmp_path).read_classification_output(path)
```

- [ ] **Step 2: Run the new artifact tests and confirm they fail**

Run: `python -m pytest -q tests/test_classification_artifact_service.py -v`
Expected: FAIL because the artifact service does not exist yet.

- [ ] **Step 3: Implement artifact read/write with strict validation**

```python
class ClassificationArtifactService:
    def write_classification_input(self, *, report_date: str, items: list[dict[str, object]]) -> Path:
        target = self.run_dir(report_date) / "classification-input.json"
        target.write_text(json.dumps({"report_date": report_date, "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def read_classification_output(self, path: Path) -> list[dict[str, object]]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        self._validate_output(payload)
        return payload
```

- [ ] **Step 4: Refactor orchestration so analysis is split into staging and ingest**

Add a pair of explicit methods:

```python
def build_classification_input(self, report_date: date) -> Path: ...
def ingest_classification_output(self, report_date: date, path: Path) -> DailyPipelineResult: ...
```

The old direct LLM call path must be removed from orchestration.

- [ ] **Step 5: Re-run the focused artifact and orchestration tests**

Run: `python -m pytest -q tests/test_classification_artifact_service.py tests/test_orchestration_service.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/haotian/services/classification_artifact_service.py src/haotian/services/orchestration_service.py src/haotian/analyzers/capability_normalizer.py src/haotian/analyzers/capability_classifier.py tests/test_classification_artifact_service.py tests/test_orchestration_service.py
git commit -m "feat: stage codex classification artifacts"
```

### Task 3: Add The Stable Runner And Final JSON Report Output

**Files:**
- Create: `src/haotian/runner.py`
- Modify: `src/haotian/services/report_service.py`
- Modify: `src/haotian/services/__init__.py`
- Test: `tests/test_runner.py`
- Modify: `tests/test_report_service.py`

- [ ] **Step 1: Write the failing tests for runner summaries and JSON reports**

```python
def test_runner_creates_markdown_and_json_reports(tmp_path):
    summary = run_once(report_date="2026-03-23", workspace=tmp_path)
    assert summary["markdown_report"].endswith("2026-03-23.md")
    assert summary["json_report"].endswith("2026-03-23.json")
```

```python
def test_report_service_writes_json_summary(tmp_path):
    path = ReportService(database_url=db_url, report_dir=tmp_path).generate_daily_report_json("2026-03-23")
    assert json.loads(path.read_text(encoding="utf-8"))["report_date"] == "2026-03-23"
```

- [ ] **Step 2: Run the focused runner/report tests and verify they fail**

Run: `python -m pytest -q tests/test_runner.py tests/test_report_service.py -v`
Expected: FAIL because the runner and JSON report writer do not exist yet.

- [ ] **Step 3: Implement the runner contract**

```python
def run_once(*, report_date: str | None = None) -> dict[str, object]:
    service = OrchestrationService()
    input_path = service.build_classification_input(parsed_date)
    output_path = input_path.with_name("classification-output.json")
    if not output_path.exists():
        return {"status": "awaiting_codex_classification", "classification_input": str(input_path)}
    result = service.ingest_classification_output(parsed_date, output_path)
    return {"status": "completed", "markdown_report": str(result.report_path), "json_report": str(result.json_report_path)}
```

- [ ] **Step 4: Add a JSON report writer next to the Markdown report**

```python
def generate_daily_report_json(self, report_date: date | str) -> Path:
    target = self.report_dir / f"{target_date.isoformat()}.json"
    target.write_text(json.dumps(self._build_report_payload(target_date), ensure_ascii=False, indent=2), encoding="utf-8")
    return target
```

- [ ] **Step 5: Re-run the focused tests**

Run: `python -m pytest -q tests/test_runner.py tests/test_report_service.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/haotian/runner.py src/haotian/services/report_service.py src/haotian/services/__init__.py tests/test_runner.py tests/test_report_service.py
git commit -m "feat: add staged runner and json reports"
```

### Task 4: Remove Chat, Web, Telegram, And Direct OpenAI Dependencies

**Files:**
- Delete: `src/haotian/webapp/server.py`
- Delete: `src/haotian/services/chat_service.py`
- Delete: `src/haotian/services/cli_chat_service.py`
- Delete: `src/haotian/integrations/telegram_bot.py`
- Delete: `src/haotian/llm/openai_codex.py`
- Delete: `src/haotian/prompts/capability_classification.md`
- Modify: `src/haotian/config.py`
- Modify: `src/haotian/services/__init__.py`
- Modify: `pyproject.toml`
- Delete: `tests/test_chat_service.py`
- Delete: `tests/test_cli_chat_service.py`
- Delete: `tests/test_web_server.py`
- Delete: `tests/test_telegram_bot.py`
- Delete: `tests/test_openai_codex.py`

- [ ] **Step 1: Write the failing config/package test for a no-OpenAI world**

```python
def test_settings_do_not_require_openai_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings.from_env()
    assert not hasattr(settings, "openai_api_key") or settings.openai_api_key is None
```

- [ ] **Step 2: Run focused config tests and confirm the old OpenAI assumptions still exist**

Run: `python -m pytest -q tests/test_config.py -v`
Expected: FAIL against the updated expectation until config and tests are rewritten.

- [ ] **Step 3: Remove OpenAI-specific fields and dependencies**

Update config and package metadata so the core dependency list no longer advertises direct API usage:

```toml
dependencies = [
  "beautifulsoup4>=4.12,<5.0",
  "python-dotenv>=1.0.1",
  "pydantic>=2.6,<3.0",
  "typer>=0.12,<1.0",
]
```

Keep `python-dotenv` only if local `.env` loading remains useful for non-secret paths like `DATABASE_URL` and `REPORT_DIR`.

- [ ] **Step 4: Delete obsolete interaction modules and obsolete tests**

Run exactly:

```bash
git rm src/haotian/webapp/server.py src/haotian/services/chat_service.py src/haotian/services/cli_chat_service.py src/haotian/integrations/telegram_bot.py src/haotian/llm/openai_codex.py src/haotian/prompts/capability_classification.md tests/test_chat_service.py tests/test_cli_chat_service.py tests/test_web_server.py tests/test_telegram_bot.py tests/test_openai_codex.py
```

- [ ] **Step 5: Re-run focused tests after pruning**

Run: `python -m pytest -q tests/test_config.py tests/test_start_haotian.py tests/test_runner.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/haotian/config.py src/haotian/services/__init__.py pyproject.toml tests/test_config.py
git commit -m "refactor: remove interaction surfaces and openai dependency"
```

### Task 5: Rewrite Docs Around The Skill Workflow

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/ops.md`
- Modify: `docs/capability-taxonomy.md` if the skill prompt needs stricter schema notes

- [ ] **Step 1: Write the failing doc assertions as grep-based checks**

Run:

```bash
rg -n "web chat|Telegram|OPENAI_API_KEY|start_haotian.py --mode web|start_haotian.py --mode cli" README.md docs
```

Expected: matches still exist and need to be removed or rewritten.

- [ ] **Step 2: Rewrite README as skill-first usage**

README must explain:
- the repo is a Codex skill
- how to invoke it explicitly
- what files are produced
- that classification is completed by Codex, not by `OPENAI_API_KEY`

Include a minimal usage block:

```text
Use Haotian to refresh local AI capability intelligence, classify repositories with the project taxonomy, and generate the latest Markdown and JSON reports.
```

- [ ] **Step 3: Rewrite architecture and ops docs**

Architecture should describe:
- runner
- staged classification artifacts
- Codex-driven classification

Ops should describe:
- how to run the deterministic stage
- where `classification-input.json` and `classification-output.json` live
- how final reports are generated

- [ ] **Step 4: Re-run the grep checks**

Run:

```bash
rg -n "web chat|Telegram|OPENAI_API_KEY|start_haotian.py --mode web|start_haotian.py --mode cli" README.md docs
```

Expected: no matches for removed behavior, except where historical context is explicitly intended.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/architecture.md docs/ops.md docs/capability-taxonomy.md
git commit -m "docs: rewrite haotian as a codex skill"
```

### Task 6: Full Verification And Cleanup

**Files:**
- Review: repository-wide
- Test: `tests/`

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: all remaining tests pass with no chat/web/telegram/OpenAI-specific coverage left behind.

- [ ] **Step 2: Run a smoke test for the new runner**

Run: `python start_haotian.py`
Expected: one of the following explicit outcomes:
- a summary showing `classification-input.json` was produced and Codex classification is now required, or
- a completed summary with Markdown and JSON report paths if classification output already exists

- [ ] **Step 3: Validate the root skill metadata**

Run:

```bash
python E:/CodexHome/skills/.system/skill-creator/scripts/quick_validate.py E:/Haotian
```

Expected: validation succeeds for the root `SKILL.md`.

- [ ] **Step 4: Review git diff for accidental leftovers**

Run:

```bash
git status --short
git diff --stat
```

Expected: only intended files remain changed; no orphaned interaction files remain.

- [ ] **Step 5: Commit the final cleanup**

```bash
git add -A
git commit -m "test: verify skill-first haotian pipeline"
```
