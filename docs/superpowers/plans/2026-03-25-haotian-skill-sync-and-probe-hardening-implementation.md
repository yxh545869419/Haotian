# Haotian Skill Sync And Probe Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add taxonomy gaps to daily reports, harden repository probing for skill ecosystems, and add deterministic audited Codex skill sync that installs only integrable audit-safe skills.

**Architecture:** Keep Haotian's two-stage pipeline intact, but expand the deterministic Python side with three new layers: richer report serialization, probe-time skill-package detection, and finalize-time skill inventory/audit/sync services. Codex remains responsible only for repository capability classification and any non-template skill text that cannot be copied or scaffolded safely from source materials.

**Tech Stack:** Python 3.11, `pydantic`, SQLite, `pytest`, local filesystem staging, `subprocess` integration with `skill-audit-guard`

---

## Planned File Map

**Modify**

- `E:/Haotian/src/haotian/config.py`
- `E:/Haotian/src/haotian/services/classification_artifact_service.py`
- `E:/Haotian/src/haotian/services/report_service.py`
- `E:/Haotian/src/haotian/services/repository_probe_service.py`
- `E:/Haotian/src/haotian/services/repository_analysis_service.py`
- `E:/Haotian/src/haotian/services/orchestration_service.py`
- `E:/Haotian/src/haotian/runner.py`
- `E:/Haotian/.env.example`
- `E:/Haotian/README.md`
- `E:/Haotian/docs/ops.md`
- `E:/Haotian/docs/architecture.md`
- `E:/Haotian/tests/test_config.py`
- `E:/Haotian/tests/test_report_service.py`
- `E:/Haotian/tests/test_repository_probe_service.py`
- `E:/Haotian/tests/test_orchestration_service.py`
- `E:/Haotian/tests/test_runner.py`

**Create**

- `E:/Haotian/src/haotian/services/repository_skill_package_service.py`
- `E:/Haotian/src/haotian/services/codex_skill_inventory_service.py`
- `E:/Haotian/src/haotian/services/skill_audit_service.py`
- `E:/Haotian/src/haotian/services/skill_sync_service.py`
- `E:/Haotian/tests/test_repository_skill_package_service.py`
- `E:/Haotian/tests/test_codex_skill_inventory_service.py`
- `E:/Haotian/tests/test_skill_audit_service.py`
- `E:/Haotian/tests/test_skill_sync_service.py`

The new services split responsibilities cleanly:

- `repository_skill_package_service.py` discovers installable skill packages inside a cloned repository.
- `codex_skill_inventory_service.py` scans local skill roots and normalizes installed skill metadata.
- `skill_audit_service.py` wraps the local `skill-audit-guard` script and normalizes audit results.
- `skill_sync_service.py` performs deterministic matching, staging, install, rollback, and reporting.

### Task 1: Add Config And Artifact Plumbing

**Files:**
- Modify: `E:/Haotian/src/haotian/config.py`
- Modify: `E:/Haotian/src/haotian/services/classification_artifact_service.py`
- Modify: `E:/Haotian/src/haotian/runner.py`
- Modify: `E:/Haotian/tests/test_config.py`
- Modify: `E:/Haotian/tests/test_runner.py`

- [ ] **Step 1: Write the failing config and runner tests**

```python
def test_settings_support_codex_skill_roots_and_audit_script(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_SKILL_ROOTS", f"{tmp_path / 'skills-a'};{tmp_path / 'skills-b'}")
    monkeypatch.setenv("CODEX_MANAGED_SKILL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setenv("SKILL_AUDIT_SCRIPT", str(tmp_path / "audit_skill.py"))

    settings = config_module.Settings.from_env()

    assert list(settings.codex_skill_roots) == [tmp_path / "skills-a", tmp_path / "skills-b"]
    assert settings.codex_managed_skill_root == tmp_path / "managed"
    assert settings.skill_audit_script == tmp_path / "audit_skill.py"


def test_finalize_summary_includes_skill_sync_report():
    assert second["skill_sync_report"].endswith("skill-sync-report.json")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_config.py E:\Haotian\tests\test_runner.py -q`

Expected: FAIL because the new settings fields and `skill_sync_report` summary key do not exist yet.

- [ ] **Step 3: Add the minimal settings and artifact paths**

```python
class Settings(BaseModel):
    codex_skill_roots: tuple[Path, ...] = Field(default_factory=tuple, alias="CODEX_SKILL_ROOTS")
    codex_managed_skill_root: Path | None = Field(default=None, alias="CODEX_MANAGED_SKILL_ROOT")
    skill_audit_script: Path | None = Field(default=None, alias="SKILL_AUDIT_SCRIPT")


def skill_sync_report_path(self, report_date: str) -> Path:
    return self.run_directory(report_date) / "skill-sync-report.json"
```

- [ ] **Step 4: Wire the new artifact into runner summary output**

```python
"skill_sync_report": str(result.skill_sync_report_path) if result.skill_sync_report_path else None,
```

- [ ] **Step 5: Re-run the targeted tests**

Run: `E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_config.py E:\Haotian\tests\test_runner.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git -C E:\Haotian add src/haotian/config.py src/haotian/services/classification_artifact_service.py src/haotian/runner.py tests/test_config.py tests/test_runner.py
git -C E:\Haotian commit -m "feat: add skill sync config and artifacts"
```

### Task 2: Add Taxonomy Gap Data To Markdown And JSON Reports

**Files:**
- Modify: `E:/Haotian/src/haotian/services/report_service.py`
- Modify: `E:/Haotian/tests/test_report_service.py`
- Modify: `E:/Haotian/tests/test_runner.py`

- [ ] **Step 1: Write the failing report tests**

```python
def test_report_payload_includes_taxonomy_gap_summary(tmp_path):
    payload = service._build_report_payload(date(2026, 3, 25), sections, repo_snapshot)

    assert payload["taxonomy_gap_summary"]["candidate_count"] == 2
    assert payload["taxonomy_gap_candidates"][0]["display_name"] == "内容生成 / 营销自动化"


def test_markdown_renders_taxonomy_gap_section(tmp_path):
    markdown = service._render_markdown(date(2026, 3, 25), payload)
    assert "## Taxonomy Gap 候选" in markdown
    assert "内容生成 / 营销自动化" in markdown
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_report_service.py E:\Haotian\tests\test_runner.py -q`

Expected: FAIL because the report payload and Markdown do not expose gap data yet.

- [ ] **Step 3: Add report payload fields and Markdown section**

```python
"taxonomy_gap_summary": {
    "candidate_count": len(taxonomy_gap_candidates),
    "repo_count": sum(candidate["repo_count"] for candidate in taxonomy_gap_candidates),
},
"taxonomy_gap_candidates": taxonomy_gap_candidates,
```

```python
lines.extend(["", "## Taxonomy Gap 候选", ""])
for candidate in payload["taxonomy_gap_candidates"]:
    lines.append(f"- `{candidate['display_name']}`：涉及 {candidate['repo_count']} 个 repo，代表仓库 {repo_text}。")
    lines.append(f"  原因：{candidate['reason']}")
```

- [ ] **Step 4: Keep the JSON stable for programmatic reads**

```python
"artifact_links": {
    **self._build_artifact_links(target_date),
}
```

- [ ] **Step 5: Re-run the targeted report tests**

Run: `E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_report_service.py E:\Haotian\tests\test_runner.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git -C E:\Haotian add src/haotian/services/report_service.py tests/test_report_service.py tests/test_runner.py
git -C E:\Haotian commit -m "feat: add taxonomy gap summaries to reports"
```

### Task 3: Harden Probe Rules For Skill Ecosystems

**Files:**
- Modify: `E:/Haotian/src/haotian/services/repository_probe_service.py`
- Modify: `E:/Haotian/src/haotian/services/repository_analysis_service.py`
- Modify: `E:/Haotian/tests/test_repository_probe_service.py`

- [ ] **Step 1: Write failing probe tests for root skill files and misclassification guard**

```python
def test_probe_prioritizes_root_and_nested_skill_files(tmp_path):
    repo = tmp_path / "repo"
    (repo / "SKILL.md").write_text("# Root skill", encoding="utf-8")
    (repo / "skills" / "seo-audit" / "SKILL.md").parent.mkdir(parents=True)
    (repo / "skills" / "seo-audit" / "SKILL.md").write_text("# Nested skill", encoding="utf-8")

    result = RepositoryProbeService(max_files=8, max_file_bytes=256).probe(repo)

    assert "SKILL.md" in result.matched_files
    assert "skills/seo-audit/SKILL.md" in result.matched_files
    assert "codex-skill-package" in result.architecture_signals


def test_probe_does_not_treat_skill_name_as_entrypoint(tmp_path):
    repo = tmp_path / "repo"
    target = repo / "skills" / "app-store-optimization" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("# app-store-optimization", encoding="utf-8")

    result = RepositoryProbeService(max_files=8, max_file_bytes=256).probe(repo)

    assert "app*" not in result.matched_keywords
```

- [ ] **Step 2: Run the probe tests to verify they fail**

Run: `E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_repository_probe_service.py -q`

Expected: FAIL because root-level skill files are not prioritized and basename heuristics still misclassify nested skill names.

- [ ] **Step 3: Add skill-aware path classification helpers**

```python
def _is_skill_package_context(self, path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return relative.name in {"SKILL.md", "AGENTS.md", "codex.md"} or "skills" in {part.lower() for part in relative.parts[:-1]}


if self._is_skill_package_context(path, root):
    keywords.extend(["skill-package"])
    group = group or "skill-package"
```

- [ ] **Step 4: Add explicit architecture signals and keep depth=1 clone untouched**

```python
if any(keyword in keyword_set for keyword in {"skill-package", "skills/**/*.SKILL.md"}):
    signals.append("codex-skill-package")
    signals.append("skill-ecosystem")
```

- [ ] **Step 5: Re-run the probe tests**

Run: `E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_repository_probe_service.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git -C E:\Haotian add src/haotian/services/repository_probe_service.py src/haotian/services/repository_analysis_service.py tests/test_repository_probe_service.py
git -C E:\Haotian commit -m "feat: harden repository probe for skill ecosystems"
```

### Task 4: Add Repository Skill Package Discovery

**Files:**
- Create: `E:/Haotian/src/haotian/services/repository_skill_package_service.py`
- Create: `E:/Haotian/tests/test_repository_skill_package_service.py`
- Modify: `E:/Haotian/src/haotian/services/repository_analysis_service.py`

- [ ] **Step 1: Write the failing discovery tests**

```python
def test_repository_skill_package_service_discovers_multiple_skill_packages(tmp_path):
    repo = tmp_path / "repo"
    first = repo / "skills" / "agent-designer" / "SKILL.md"
    second = repo / "skills" / "rag-architect" / "SKILL.md"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("# agent-designer", encoding="utf-8")
    second.write_text("# rag-architect", encoding="utf-8")

    packages = RepositorySkillPackageService().discover(repo)

    assert [package.skill_name for package in packages] == ["agent-designer", "rag-architect"]
```

- [ ] **Step 2: Run the package discovery tests to verify they fail**

Run: `E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_repository_skill_package_service.py -q`

Expected: FAIL because the service does not exist yet.

- [ ] **Step 3: Implement deterministic skill package discovery**

```python
@dataclass(frozen=True, slots=True)
class DiscoveredSkillPackage:
    skill_name: str
    package_root: Path
    relative_root: str
    files: tuple[str, ...]


def discover(self, repo_root: Path) -> tuple[DiscoveredSkillPackage, ...]:
    ...
```

- [ ] **Step 4: Surface package manifests back into repository analysis results**

```python
"discovered_skill_packages": [package.to_dict() for package in packages],
```

- [ ] **Step 5: Re-run the new tests**

Run: `E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_repository_skill_package_service.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git -C E:\Haotian add src/haotian/services/repository_skill_package_service.py src/haotian/services/repository_analysis_service.py tests/test_repository_skill_package_service.py
git -C E:\Haotian commit -m "feat: discover skill packages inside analyzed repositories"
```

### Task 5: Add Local Skill Inventory And Audit Wrappers

**Files:**
- Create: `E:/Haotian/src/haotian/services/codex_skill_inventory_service.py`
- Create: `E:/Haotian/src/haotian/services/skill_audit_service.py`
- Create: `E:/Haotian/tests/test_codex_skill_inventory_service.py`
- Create: `E:/Haotian/tests/test_skill_audit_service.py`
- Modify: `E:/Haotian/src/haotian/config.py`

- [ ] **Step 1: Write the failing inventory and audit tests**

```python
def test_codex_skill_inventory_scans_roots_in_precedence_order(tmp_path):
    managed = tmp_path / "managed"
    shared = tmp_path / "shared"
    (managed / "seo-audit" / "SKILL.md").parent.mkdir(parents=True)
    (shared / "seo-audit" / "SKILL.md").parent.mkdir(parents=True)

    inventory = CodexSkillInventoryService((managed, shared)).scan()

    assert inventory["seo-audit"].source_root == managed


def test_skill_audit_service_parses_clean_result(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", fake_completed_process("CLEAN"))
    result = SkillAuditService(script_path=tmp_path / "audit_skill.py").audit(tmp_path / "candidate")
    assert result.status == "clean"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_codex_skill_inventory_service.py E:\Haotian\tests\test_skill_audit_service.py -q`

Expected: FAIL because the services do not exist yet.

- [ ] **Step 3: Implement inventory scanning with canonical paths**

```python
def scan(self) -> dict[str, InstalledSkillRecord]:
    for root_index, root in enumerate(self.skill_roots):
        resolved_root = root.resolve(strict=False)
        ...
```

- [ ] **Step 4: Implement audit wrapper with strict pass criteria**

```python
def is_installable(self) -> bool:
    return self.status == "clean"
```

- [ ] **Step 5: Re-run the inventory and audit tests**

Run: `E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_codex_skill_inventory_service.py E:\Haotian\tests\test_skill_audit_service.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git -C E:\Haotian add src/haotian/services/codex_skill_inventory_service.py src/haotian/services/skill_audit_service.py tests/test_codex_skill_inventory_service.py tests/test_skill_audit_service.py src/haotian/config.py
git -C E:\Haotian commit -m "feat: add codex skill inventory and audit services"
```

### Task 6: Implement Deterministic Skill Sync

**Files:**
- Create: `E:/Haotian/src/haotian/services/skill_sync_service.py`
- Modify: `E:/Haotian/src/haotian/services/classification_artifact_service.py`
- Modify: `E:/Haotian/src/haotian/services/orchestration_service.py`
- Modify: `E:/Haotian/src/haotian/runner.py`
- Create: `E:/Haotian/tests/test_skill_sync_service.py`
- Modify: `E:/Haotian/tests/test_orchestration_service.py`
- Modify: `E:/Haotian/tests/test_runner.py`

- [ ] **Step 1: Write failing skill sync tests**

```python
def test_skill_sync_aligns_existing_audit_safe_skill(tmp_path):
    result = service.sync(report_date=date(2026, 3, 25), candidates=[candidate], inventory=inventory)
    assert result.actions[0]["action"] == "aligned_existing"


def test_skill_sync_installs_new_audit_safe_skill_atomically(tmp_path):
    result = service.sync(report_date=date(2026, 3, 25), candidates=[candidate], inventory={})
    assert (managed_root / "agent-designer" / "SKILL.md").exists()
    assert result.actions[0]["action"] == "installed_new"


def test_skill_sync_discards_non_integrable_candidate(tmp_path):
    assert result.actions[0]["action"] == "discarded_non_integrable"


def test_skill_sync_blocks_failed_audit(tmp_path):
    assert result.actions[0]["action"] == "blocked_audit_failure"
```

- [ ] **Step 2: Run the new sync tests to verify they fail**

Run: `E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_skill_sync_service.py E:\Haotian\tests\test_orchestration_service.py E:\Haotian\tests\test_runner.py -q`

Expected: FAIL because there is no sync service, no `skill-sync-report.json`, and no orchestration path for sync actions.

- [ ] **Step 3: Implement deterministic matching and action schema**

```python
def match_candidate(self, candidate, inventory):
    return (
        self._exact_name_match(candidate, inventory)
        or self._alias_match(candidate, inventory)
        or self._slug_match(candidate, inventory)
        or self._similarity_match(candidate, inventory, threshold=0.72)
    )
```

- [ ] **Step 4: Implement atomic staging, install, and rollback**

```python
staging_dir = managed_root.parent / f".haotian-stage-{candidate.slug}"
target_dir = managed_root / candidate.slug
...
staging_dir.replace(target_dir)
```

- [ ] **Step 5: Wire sync results into finalize artifacts and runner summary**

```python
result.skill_sync_report_path = self.artifact_service.write_json_artifact(
    path=self.artifact_service.skill_sync_report_path(target_date.isoformat()),
    payload=sync_payload,
)
```

- [ ] **Step 6: Re-run the sync and orchestration tests**

Run: `E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_skill_sync_service.py E:\Haotian\tests\test_orchestration_service.py E:\Haotian\tests\test_runner.py -q`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git -C E:\Haotian add src/haotian/services/skill_sync_service.py src/haotian/services/classification_artifact_service.py src/haotian/services/orchestration_service.py src/haotian/runner.py tests/test_skill_sync_service.py tests/test_orchestration_service.py tests/test_runner.py
git -C E:\Haotian commit -m "feat: add audited codex skill sync"
```

### Task 7: Update Docs And Run End-To-End Verification

**Files:**
- Modify: `E:/Haotian/.env.example`
- Modify: `E:/Haotian/README.md`
- Modify: `E:/Haotian/docs/ops.md`
- Modify: `E:/Haotian/docs/architecture.md`

- [ ] **Step 1: Write the failing doc-facing regression assertions**

```python
def test_readme_mentions_skill_sync_report():
    assert "skill-sync-report.json" in Path("README.md").read_text(encoding="utf-8")
    assert "CODEX_SKILL_ROOTS" in Path(".env.example").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the focused checks to verify the docs need updates**

Run: `E:\Python\python.exe -m pytest -q E:\Haotian\tests\test_config.py E:\Haotian\tests\test_runner.py -q`

Expected: PASS or FAIL depending on prior tasks; if no doc assertions are committed as tests, use this step to manually confirm missing references before editing docs.

- [ ] **Step 3: Update docs and examples**

```text
CODEX_SKILL_ROOTS=...
CODEX_MANAGED_SKILL_ROOT=...
SKILL_AUDIT_SCRIPT=...
```

- [ ] **Step 4: Run the full suite**

Run: `E:\Python\python.exe -m pytest -q`

Expected: PASS

- [ ] **Step 5: Run one real Haotian cycle**

Run: `E:\Python\python.exe E:\Haotian\start_haotian.py --date 2026-03-25`

Expected:
- `status` is `completed`
- `E:\Haotian\data\runs\2026-03-25\skill-sync-report.json` exists
- `E:\Haotian\data\reports\2026-03-25.md` contains a `Taxonomy Gap 候选` section
- skill-heavy repositories surface skill-package evidence instead of generic entrypoint bias

- [ ] **Step 6: Commit**

```bash
git -C E:\Haotian add .env.example README.md docs/ops.md docs/architecture.md
git -C E:\Haotian commit -m "docs: document skill sync and probe hardening"
```

## Final Verification Checklist

- [ ] `E:\Python\python.exe -m pytest -q`
- [ ] `E:\Python\python.exe E:\Haotian\start_haotian.py --date 2026-03-25`
- [ ] Verify `E:\Haotian\data\runs\2026-03-25\skill-sync-report.json`
- [ ] Verify `E:\Haotian\data\reports\2026-03-25.md`
- [ ] Verify `E:\Haotian\data\reports\2026-03-25.json`
