# Haotian Skill Sync And Probe Hardening Design

## English

### Summary

This change extends Haotian in three coordinated ways:

1. Add taxonomy gap candidates directly into the daily Markdown and JSON report payloads.
2. Harden deep repository probing so skill ecosystems are detected correctly instead of being flattened into generic workflow labels.
3. Add an audited Codex skill sync stage that automatically installs or aligns audit-safe skills, while discarding repositories that cannot be turned into acceptable Codex skills.

The system should continue to use Python for deterministic collection, probing, auditing, installation, and reporting. Codex should only be used for judgment-heavy classification and skill authoring cases that cannot be templated safely.

### Problem Statement

The current pipeline has three important gaps:

- Taxonomy gap candidates are generated as side artifacts but are not visible in the daily management summary.
- The repository probe is too coarse for skill-heavy repositories. It matches many files, keeps only a small bounded subset, and can misread skill names such as `app-store-optimization` as executable entrypoints because the current rules over-index on file basenames.
- "Covered" capabilities only reflect Haotian's internal registry state. They are not compared against the machine's installed Codex skill inventory, so Haotian cannot automatically align, install, or discard skill candidates.

This leads to under-reporting of Codex-oriented skill repositories such as `alirezarezvani/claude-skills`, where the repo is present in the run artifacts but its skill-packaging evidence is not surfaced strongly enough.

### Goals

- Show taxonomy gap candidates in both human-readable and machine-readable daily reports.
- Improve probe precision for skill repositories without changing the shallow clone strategy.
- Prefer skill-package evidence over generic entrypoint heuristics when a repository is primarily a skill ecosystem.
- Compare active capabilities and taxonomy-gap-derived skill candidates against local Codex skill directories.
- Automatically audit every candidate skill before install or alignment.
- Automatically install or align audit-safe skills.
- Discard non-integrable skill candidates instead of keeping them as noisy pending items.
- Keep deterministic workflow steps in Python.

### Non-Goals

- Full-source semantic analysis of every cloned repository.
- Direct in-place modification of third-party upstream skill repositories.
- Automatic installation of anything that fails audit or cannot be mapped into an acceptable Codex skill package.
- Replacing Codex judgment for taxonomy classification or non-template skill content.

### Design

#### 1. Report Enrichment

Haotian will extend the report payload with a first-class taxonomy gap section:

- Markdown:
  - Add a taxonomy gap count to the executive overview.
  - Add a `Taxonomy Gap Candidates` section after the capability summary.
  - Each gap entry shows display name, repo count, representative repos, and reason.
- JSON:
  - Add `taxonomy_gap_summary`.
  - Add `taxonomy_gap_candidates`.
  - Keep the artifact path link for traceability.

The Markdown remains optimized for management reading. The JSON remains the canonical machine-readable interface.

#### 2. Probe Hardening For Skill Repositories

The clone strategy remains `git clone --depth 1`. This limits Git history only; it does not limit directory depth.

The probe logic changes in two ways:

- High-priority skill paths:
  - `skills/**/SKILL.md`
  - `skills/**/AGENTS.md`
  - `skills/**/codex.md`
  - `agents/**/*.md`
  - `commands/**/*.md`
  - `references/**/*.md`
  - `scripts/**/*.py`
- Heuristic refinement:
  - Stop treating basename prefixes such as `app*`, `agent*`, or `server*` as strong entrypoint signals when the file lives inside obvious skill-package directories.
  - Add explicit architecture signals such as:
    - `codex-skill-package`
    - `skill-ecosystem`
    - `plugin-ecosystem`

This lets repos like `claude-skills` surface as skill ecosystems first, with workflow-orchestration treated as a secondary interpretation if still justified.

#### 3. Audited Codex Skill Sync

After classification and automatic audit, Haotian will add a deterministic skill sync stage.

Inputs:

- Active capabilities from the registry
- Taxonomy gap candidates
- Local installed skill inventories from:
  - `C:\Users\AVALLY-SH-027\.agents\skills`
  - `E:\CodexHome\skills`

Process:

1. Build a canonical local skill inventory:
   - skill name
   - source path
   - description
   - audit status
   - managed/unmanaged flag
   - alias set
2. Evaluate whether each candidate repository can become a Codex skill:
   - Accept only repositories with usable skill packaging evidence.
   - Reject repositories that cannot be turned into a valid Codex skill package.
3. Audit candidate skills before any install or alignment action.
4. If an equivalent or near-equivalent local skill already exists and passes audit:
   - Record canonical alignment and alias mapping.
   - Do not mutate the upstream third-party repository.
   - Prefer a managed wrapper or metadata mapping over direct upstream edits.
5. If no equivalent skill exists and the candidate is integrable plus audit-safe:
   - Generate a Haotian-managed skill package.
   - Install it into the local Codex skill system.
6. If the candidate is not integrable or fails audit:
   - Mark it as discarded.
   - Do not install it.

Outputs:

- `skill-sync-report.json`
- Report summary fields for:
  - aligned skills
  - newly installed skills
  - discarded candidates
  - audit failures

#### 4. Automation Boundary

Python should own:

- repository collection
- clone and cleanup
- probing
- deterministic evidence extraction
- taxonomy gap aggregation
- local skill inventory scanning
- skill auditing
- alias matching
- managed skill scaffolding
- installation and reporting

Codex should only be used for:

- repository capability classification
- non-template skill content authoring when a generated skill package needs human-like synthesis

### Data Model Changes

The daily JSON report will add:

- `taxonomy_gap_summary`
- `taxonomy_gap_candidates`
- `skill_sync_summary`
- `skill_sync_actions`

Run artifacts will add:

- `skill-sync-report.json`

The probe result model will add richer skill-package signals and preserve enough evidence to explain why a repo was installed, aligned, or discarded.

### Safety Rules

- No install without audit.
- No direct rewrite of third-party upstream skill repositories.
- No promotion of repositories that do not contain acceptable Codex skill packaging evidence.
- No fallback from audit failure to silent install.

### Testing

- Unit tests for report payload and Markdown rendering with taxonomy gaps.
- Unit tests for probe matching of:
  - `skills/**/SKILL.md`
  - `skills/**/AGENTS.md`
  - `skills/**/codex.md`
- Regression test ensuring skill names like `app-store-optimization` do not trigger entrypoint misclassification.
- Unit and integration tests for skill sync:
  - align existing audit-safe skills
  - install new audit-safe managed skills
  - discard non-integrable candidates
  - block audit failures
- End-to-end runner test verifying new report fields and skill sync artifact generation.

### Rollout

1. Add report enrichment.
2. Harden probe logic and regression coverage.
3. Add local skill inventory scanning and audit plumbing.
4. Add deterministic skill sync actions and artifacts.
5. Re-run a real Haotian cycle and verify that skill-heavy repositories are surfaced correctly.

## 中文版

### 概述

这次改动会把 Haotian 往 3 个方向一起推进：

1. 把 taxonomy gap 候选直接放进每日 Markdown 和 JSON 报告主结构。
2. 强化深度探针，让 skill 生态类仓库不再被粗暴压成泛化的工作流标签。
3. 新增一个带审计的 Codex skill 同步阶段，对可落地且审计通过的 skill 自动安装或对齐；不能变成合格 Codex skill 的候选则直接舍弃。

整体原则保持不变：确定性的抓取、探测、审计、安装、报告都尽量由 Python 完成；只有真正需要判断或内容合成的部分才调用 Codex。

### 问题定义

当前流程主要有 3 个缺口：

- taxonomy gap 目前只生成 side artifact，没有进入每日管理摘要正文。
- 对 skill 型仓库的探针太粗，命中文件很多但预算只保留少量样本，而且像 `app-store-optimization` 这类 skill 名称，会因为 basename 命中 `app*` 被误判成入口文件。
- “已覆盖”只代表 Haotian 内部 registry 里的 `ACTIVE` 状态，并不会自动和本机 Codex skill 目录对比，因此无法自动做对齐、安装或舍弃。

这会导致像 `alirezarezvani/claude-skills` 这样的仓库虽然进入了运行产物，但它的 skill 打包证据没有被足够强地展示出来。

### 目标

- 在人类可读和程序可读的日报里都展示 taxonomy gap。
- 在不修改 shallow clone 策略的前提下，提高 skill 仓库探针精度。
- 当仓库本质上是 skill 生态时，优先使用 skill 打包证据，而不是泛化的入口文件启发式。
- 将 active capabilities 与 taxonomy gap 推导出的 skill 候选，自动拿去和本机 Codex skill 目录对比。
- 所有候选 skill 在安装或对齐前都必须先审计。
- 审计通过且可整合的 skill 自动落地。
- 不能整合成合格 Codex skill 的候选直接舍弃，不继续保留成噪音。
- 尽量把整个流程代码化。

### 非目标

- 不做每个 clone 仓库的全量语义源码分析。
- 不直接原地修改第三方上游 skill 仓库。
- 不会把审计失败或无法映射成合格 Codex skill 的内容自动安装。
- 不会用规则系统取代 Codex 对 taxonomy 分类和非模板 skill 内容的判断。

### 设计

#### 1. 报告增强

Haotian 会把 taxonomy gap 升级成日报里的一级结构：

- Markdown：
  - 在总览里增加 taxonomy gap 数量摘要
  - 在能力摘要后增加 `Taxonomy Gap 候选` 小节
  - 每个 gap 展示名称、repo 数、代表 repo 和原因
- JSON：
  - 增加 `taxonomy_gap_summary`
  - 增加 `taxonomy_gap_candidates`
  - 同时保留 artifact path 方便追溯

Markdown 继续偏向管理摘要；JSON 继续作为程序读取的标准接口。

#### 2. 面向 Skill 仓库的探针强化

clone 策略保持 `git clone --depth 1`。这里的 `depth 1` 只限制 Git 历史，不限制目录深度。

真正要改的是 probe：

- 新增高优先级 skill 路径：
  - `skills/**/SKILL.md`
  - `skills/**/AGENTS.md`
  - `skills/**/codex.md`
  - `agents/**/*.md`
  - `commands/**/*.md`
  - `references/**/*.md`
  - `scripts/**/*.py`
- 启发式修正：
  - 如果文件位于明显的 skill-package 目录下，就不要再把 basename 前缀 `app*`、`agent*`、`server*` 当成强入口信号
  - 新增明确的架构信号：
    - `codex-skill-package`
    - `skill-ecosystem`
    - `plugin-ecosystem`

这样 `claude-skills` 这类仓库会优先表现为 skill 生态，再根据需要决定是否附带工作流编排解释，而不是先被压成 `workflow_orchestration`。

#### 3. 带审计的 Codex Skill 同步

在分类和自动审计之后，Haotian 会新增一个确定性的 skill sync 阶段。

输入：

- registry 中的 active capabilities
- taxonomy gap candidates
- 本机 skill 目录：
  - `C:\Users\AVALLY-SH-027\.agents\skills`
  - `E:\CodexHome\skills`

流程：

1. 建立本机 skill inventory：
   - skill 名称
   - 来源路径
   - 描述
   - 审计状态
   - 是否为 Haotian managed
   - alias 集合
2. 判断每个候选仓库是否真的能整合成 Codex skill：
   - 只有具有可用 skill packaging 证据的仓库才进入下一步
   - 不能整理成有效 Codex skill 包的仓库直接拒绝
3. 在任何安装或对齐动作前，先做 skill 审计
4. 如果本机已经存在等价或近似 skill，且审计通过：
   - 建立 canonical 对齐和 alias 映射
   - 不直接改写第三方上游仓库
   - 优先用 managed wrapper 或 metadata mapping，而不是改第三方本体
5. 如果本机不存在对应 skill，且候选可整合并且审计通过：
   - 生成 Haotian-managed skill package
   - 安装到本机 Codex skill 体系
6. 如果候选无法整合或审计失败：
   - 标记为 discarded
   - 不做安装

输出：

- `skill-sync-report.json`
- 报告摘要字段：
  - 已对齐 skill
  - 新安装 skill
  - 已舍弃候选
  - 审计失败项

#### 4. 自动化边界

Python 负责：

- 仓库抓取
- clone 与清理
- probing
- 确定性证据抽取
- taxonomy gap 聚合
- 本机 skill inventory 扫描
- skill 审计
- alias 匹配
- managed skill scaffold
- 安装与报告生成

Codex 只负责：

- repo capability 分类
- 当新 skill 包无法完全模板化时，补全少量非模板说明内容

### 数据结构变化

日报 JSON 会新增：

- `taxonomy_gap_summary`
- `taxonomy_gap_candidates`
- `skill_sync_summary`
- `skill_sync_actions`

运行工件会新增：

- `skill-sync-report.json`

probe 结果模型也会补充更明确的 skill-package 信号，并保留足够的证据来解释为什么某个仓库最终被安装、对齐或舍弃。

### 安全规则

- 不审计，不安装。
- 不直接改写第三方上游 skill 仓库。
- 没有合格 Codex skill packaging 证据的仓库，不推进安装。
- 审计失败后不能静默回退成安装成功。

### 测试

- 报告 payload 与 Markdown 渲染的 taxonomy gap 测试
- 针对以下路径的 probe 单测：
  - `skills/**/SKILL.md`
  - `skills/**/AGENTS.md`
  - `skills/**/codex.md`
- 回归测试：`app-store-optimization` 这类 skill 名称不能再被误判成 entrypoint
- skill sync 单测 / 集成测试：
  - 对齐已有且审计通过的 skill
  - 安装新的审计通过 managed skill
  - 舍弃无法整合的候选
  - 阻断审计失败项
- runner 端到端测试，验证新增报告字段和 `skill-sync-report.json`

### 推进顺序

1. 先加报告增强
2. 再强化 probe 和回归测试
3. 再加本机 skill inventory 扫描与审计 plumbing
4. 最后加确定性的 skill sync 动作与产物
5. 跑一次真实 Haotian cycle，验证 skill-heavy repo 能被正确凸显
