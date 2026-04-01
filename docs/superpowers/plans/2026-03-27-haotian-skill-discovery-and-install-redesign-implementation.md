# Haotian Skill Discovery And Install Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans` to implement this plan task-by-task. Keep the pipeline deterministic in Python and reserve Codex calls for landing-stage merge and acceptance decisions only.

## Goal

Turn Haotian into a skill-first pipeline that:

- scans repositories only for skill-package content
- reports merged concrete skills instead of capability cards
- reads existing Codex skills as the baseline inventory
- installs full skill packages into `E:/CodexHome/skills/haotian-managed`
- uses Codex only at the landing stage for merge, naming, and final acceptance decisions

## Architecture

Keep the local clone-and-probe flow, but replace the classification-centered finalize path with a skill inventory path:

1. Python extracts skill candidates from repository contents.
2. Python scans installed Codex skills and creates the baseline inventory.
3. Python performs deterministic merge and package completeness checks.
4. Ambiguous landing cases are staged for Codex judgment.
5. Python executes audit, full-package copy, install, rollback, and reporting.

## Tech Stack

- Python 3.11
- `pydantic`
- SQLite
- `pytest`
- local filesystem staging
- `skill-audit-guard`

---

## Planned File Map

**Modify**

- `E:/Haotian/src/haotian/config.py`
- `E:/Haotian/src/haotian/services/classification_artifact_service.py`
- `E:/Haotian/src/haotian/services/orchestration_service.py`
- `E:/Haotian/src/haotian/services/report_service.py`
- `E:/Haotian/src/haotian/services/repository_probe_service.py`
- `E:/Haotian/src/haotian/services/repository_analysis_service.py`
- `E:/Haotian/src/haotian/services/skill_sync_service.py`
- `E:/Haotian/src/haotian/runner.py`
- `E:/Haotian/README.md`
- `E:/Haotian/docs/ops.md`
- `E:/Haotian/docs/architecture.md`
- `E:/Haotian/.env.example`
- `E:/Haotian/tests/test_config.py`
- `E:/Haotian/tests/test_classification_artifact_service.py`
- `E:/Haotian/tests/test_orchestration_service.py`
- `E:/Haotian/tests/test_report_service.py`
- `E:/Haotian/tests/test_repository_probe_service.py`
- `E:/Haotian/tests/test_runner.py`
- `E:/Haotian/tests/test_skill_sync_service.py`

**Create**

- `E:/Haotian/src/haotian/services/repository_skill_candidate_service.py`
- `E:/Haotian/src/haotian/services/skill_merge_service.py`
- `E:/Haotian/tests/test_repository_skill_candidate_service.py`
- `E:/Haotian/tests/test_skill_merge_service.py`

**Likely deprecate or downgrade**

- repository capability summary logic in report payloads
- taxonomy-gap-first reporting logic
- wrapper-only `installed_new` packaging flow

---

## Task 1: Repoint Configuration And Managed Install Root

**Files**

- Modify: `E:/Haotian/src/haotian/config.py`
- Modify: `E:/Haotian/.env.example`
- Modify: `E:/Haotian/tests/test_config.py`

- [ ] Write failing tests for:
  - default managed root resolves to `E:/CodexHome/skills/haotian-managed`
  - configured runtime paths still pin to the Haotian project root
  - optional discovery roots remain readable

- [ ] Implement:
  - `CODEX_MANAGED_SKILL_ROOT` default -> `E:/CodexHome/skills/haotian-managed`
  - keep `E:/CodexHome/skills` as the primary installed baseline root

- [ ] Re-run targeted tests.

Verification:

```powershell
E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_config.py
```

---

## Task 2: Replace Repository Capability Discovery With Skill Candidate Extraction

**Files**

- Create: `E:/Haotian/src/haotian/services/repository_skill_candidate_service.py`
- Modify: `E:/Haotian/src/haotian/services/repository_probe_service.py`
- Modify: `E:/Haotian/src/haotian/services/repository_analysis_service.py`
- Modify: `E:/Haotian/tests/test_repository_probe_service.py`
- Create: `E:/Haotian/tests/test_repository_skill_candidate_service.py`

- [ ] Write failing tests for:
  - root-level `SKILL.md`
  - nested `skills/**/SKILL.md`
  - package-local `references/`, `scripts/`, `README.md`, `settings.json`
  - rejecting isolated markdown notes that are not real skill packages
  - not treating nested skill names like `app-store-optimization` as entrypoint evidence

- [ ] Implement candidate extraction:
  - detect skill roots
  - gather package-local evidence files
  - generate stable `candidate_id` values from source repo, relative skill root, and normalized skill slug
  - emit `SkillCandidate` records
  - stop promoting repository taxonomy buckets as the main result

- [ ] Add `skill-candidates.json` artifact writing.

Verification:

```powershell
E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_repository_probe_service.py E:\Haotian\tests\test_repository_skill_candidate_service.py
```

---

## Task 3: Build Baseline Installed Skill Inventory Cards

**Files**

- Modify: `E:/Haotian/src/haotian/services/codex_skill_inventory_service.py`
- Modify: `E:/Haotian/src/haotian/services/orchestration_service.py`
- Modify: `E:/Haotian/tests/test_orchestration_service.py`

- [ ] Write failing tests for:
  - reading baseline installed skills from `E:/CodexHome/skills`
  - including `haotian-managed` inventory as installed cards
  - stable deduplication across multiple roots

- [ ] Implement baseline card generation:
  - installed skill name
  - description/purpose
  - installed path
  - aliases
  - managed/unmanaged flag

- [ ] Ensure baseline cards are available even when no new repository skills are discovered.

Verification:

```powershell
E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_orchestration_service.py
```

---

## Task 4: Add Deterministic Skill Merge Service

**Files**

- Create: `E:/Haotian/src/haotian/services/skill_merge_service.py`
- Modify: `E:/Haotian/src/haotian/services/orchestration_service.py`
- Create: `E:/Haotian/tests/test_skill_merge_service.py`

- [ ] Write failing tests for:
  - merging same-slug skills from multiple repositories
  - merging near-identical display names and aliases
  - preserving multiple source repositories on one merged card
  - keeping truly distinct skills separate

- [ ] Implement deterministic merge rules:
  - normalized slug
  - normalized display name
  - alias overlap
  - evidence file similarity
  - purpose token similarity

- [ ] Emit `merged_skill_cards` and `discovered_skill_cards`.

Verification:

```powershell
E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_skill_merge_service.py E:\Haotian\tests\test_orchestration_service.py
```

---

## Task 5: Introduce Landing-Stage Codex Decision Artifacts

**Files**

- Modify: `E:/Haotian/src/haotian/services/classification_artifact_service.py`
- Modify: `E:/Haotian/src/haotian/services/orchestration_service.py`
- Modify: `E:/Haotian/src/haotian/runner.py`
- Modify: `E:/Haotian/tests/test_runner.py`

- [ ] Write failing tests for a new landing-stage flow:
  - ambiguous or install-ready candidates produce `awaiting_skill_decision`
  - Python finalizes only after `skill-merge-decisions.json` exists
  - `candidate_id` joins reliably back to the deterministic extraction artifact
  - the old `classification-output.json` path is no longer the primary finalize contract

- [ ] Explicitly retire the classification-first path from the primary flow:
  - remove `classification-output.json` as the required finalize artifact for this pipeline
  - update downstream consumers to read `skill-merge-decisions.json`
  - keep old classification artifacts only as legacy compatibility data if needed

- [ ] Define `skill-merge-decisions.json` schema for Codex judgment:
  - `candidate_id`
  - `decision`
  - `canonical_name`
  - `merge_target`
  - `accepted`
  - `reason`

- [ ] Update artifact contract tests in `E:/Haotian/tests/test_classification_artifact_service.py`.

Verification:

```powershell
E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_runner.py E:\Haotian\tests\test_orchestration_service.py
```

---

## Task 6: Replace Wrapper-Only Installs With Full-Package Managed Installs

**Files**

- Modify: `E:/Haotian/src/haotian/services/skill_sync_service.py`
- Modify: `E:/Haotian/src/haotian/services/skill_audit_service.py`
- Modify: `E:/Haotian/tests/test_skill_sync_service.py`

- [ ] Write failing tests for:
  - copying a full source skill package into managed root
  - refusing wrapper-only installs
  - keeping optional supporting files that are accepted by policy
  - rolling back failed staged installs

- [ ] Implement:
  - stage complete package copy from discovered source root
  - audit staged package
  - atomic replace into `E:/CodexHome/skills/haotian-managed`
  - optional supplemental metadata file only after content copy
  - enforce package allowlist and exclude `.git`, caches, vendored dependencies, `.env*`, temporary files, and editor metadata

- [ ] Add a migration helper for existing wrapper-only managed installs so they can be identified and replaced or marked unusable.

Verification:

```powershell
E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_skill_sync_service.py
```

---

## Task 7: Rebuild Daily Report Around Skill Cards

**Files**

- Modify: `E:/Haotian/src/haotian/services/report_service.py`
- Modify: `E:/Haotian/tests/test_report_service.py`

- [ ] Write failing tests for:
  - `Skill 摘要` replacing capability summary
  - installed baseline cards rendering
  - merged repository sources appearing on one skill card
  - statuses only `已集成` / `需确认`
  - showing concrete installed paths
  - card timestamps for `first_seen_at`, `last_seen_at`, and `last_touched_at`

- [ ] Remove capability-card-first reporting from Markdown and JSON.

- [ ] Render the daily report using:
  - `installed_skill_cards`
  - `discovered_skill_cards`
  - `merged_skill_cards`
  - `daily_skill_summary`

Verification:

```powershell
E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_report_service.py
```

---

## Task 8: Update Ops And User-Facing Workflow

**Files**

- Modify: `E:/Haotian/README.md`
- Modify: `E:/Haotian/docs/ops.md`
- Modify: `E:/Haotian/docs/architecture.md`
- Modify: `E:/Haotian/.env.example`

- [ ] Document the new two-stage flow:
  - Python discovery stage
  - Codex landing-decision stage
  - Python install and report finalize stage

- [ ] Document the new artifact set:
  - `skill-candidates.json`
  - `skill-merge-decisions.json`
  - `skill-sync-report.json`

- [ ] Document that `已集成` requires a real installed package in `E:/CodexHome/skills/haotian-managed`.

Verification:

```powershell
rg -n "skill-candidates|skill-merge-decisions|haotian-managed|Skill 摘要" E:\Haotian\README.md E:\Haotian\docs\ops.md E:\Haotian\docs\architecture.md E:\Haotian\.env.example
```

---

## Task 9: End-To-End Validation

**Files**

- No new source files; validate the full pipeline.

- [ ] Run the full test suite.
- [ ] Run one real Haotian cycle.
- [ ] Confirm:
  - artifacts land under `E:/Haotian/data/...`
  - new installs land under `E:/CodexHome/skills/haotian-managed`
  - wrapper-only installs are not reported as usable
  - the Markdown report is skill-centric

Verification:

```powershell
E:\Python\python.exe -m pytest -q
E:\Python\python.exe E:\Haotian\start_haotian.py --date 2026-03-27
```

Expected manual checks:

- `E:/Haotian/data/runs/2026-03-27/skill-candidates.json`
- `E:/Haotian/data/runs/2026-03-27/skill-merge-decisions.json`
- `E:/Haotian/data/runs/2026-03-27/skill-sync-report.json`
- `E:/Haotian/data/reports/2026-03-27.md`
- `E:/CodexHome/skills/haotian-managed`

---

## Notes For Execution

- Do not claim a skill is integrated unless the managed install directory contains the copied source package content.
- Prefer replacing old wrapper-only managed installs during migration rather than trying to reinterpret them as usable.
- Keep Codex out of the basic extraction path; only invoke it at landing time for ambiguous or judgment-heavy decisions.
