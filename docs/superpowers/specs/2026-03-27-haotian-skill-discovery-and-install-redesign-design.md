# Haotian Skill Discovery And Install Redesign

## English

### Summary

This redesign changes Haotian from a repository capability classifier into a skill discovery, merge, audit, and install pipeline for Codex.

The new system should:

1. Stop classifying repositories into taxonomy buckets as the primary output.
2. Read repository contents only to discover skill-packaged or skill-convertible sections.
3. Build the daily summary around merged skill cards, not repository capability cards.
4. Read currently installed Codex skills first and include them as baseline cards.
5. Merge similar skills found across multiple repositories into one canonical skill card.
6. Install new skills into the E-drive Codex skill root using the full source package content, not thin wrappers.
7. Keep deterministic extraction and packaging in Python, and call Codex only when a candidate reaches the landing decision stage and needs judgment for merge, naming, or final acceptance.

### Problem Statement

The current Haotian pipeline still reflects its capability-intelligence origin:

- The daily report centers on capability cards and taxonomy gaps instead of concrete skill inventory.
- Repository analysis still spends effort on taxonomy classification even though the user now wants repository content inspected only for skill potential.
- `installed_new` currently creates managed wrapper directories that look installed but do not contain the full original skill package, so they are not reliably usable skills.
- Newly installed managed skills currently land under the user profile skill directory instead of the E-drive Codex skill root.
- The daily report count can diverge from the number of managed skill directories because one is a report-time abstraction and the other is a cumulative filesystem inventory.

This causes confusion and overstates real skill usability.

### Goals

- Make Haotian a skill-first pipeline.
- Use repository analysis only to detect skill packages or skill-convertible packages.
- Make the daily report summarize concrete merged skills.
- Include existing installed Codex skills as baseline cards in the report model.
- Merge similar skills across multiple repositories into one canonical card.
- Install new skills into `E:/CodexHome/skills/haotian-managed`.
- Copy full skill package content on install, including `SKILL.md`, `references/`, `scripts/`, supporting markdown, configs, and other accepted package files.
- Keep deterministic discovery, packaging, installation, and reporting in Python.
- Use Codex only when a candidate skill is ready for landing and needs judgment for:
  - merge into an existing installed skill
  - canonical naming
  - final acceptance after audit/context review

### Non-Goals

- Full semantic classification of repositories into capability taxonomy buckets.
- Keeping taxonomy gap as the primary management view.
- Installing unaudited or partially packaged skills.
- Rewriting upstream third-party repositories in place.
- Treating wrapper-only registrations as real installed skills.

### Design

#### 1. Pipeline Shift: From Capability Classification To Skill Discovery

The new primary pipeline is:

1. Collect trending repositories.
2. Deep-read repository contents with bounded local probing.
3. Extract skill candidates from root-level or nested skill package evidence.
4. Compare candidates against currently installed Codex skills.
5. Merge or deduplicate candidates across repositories.
6. Run install-time audit and packaging checks.
7. Call Codex only for landing-stage judgment when deterministic Python rules cannot fully decide merge, naming, or acceptance.
8. Install accepted skills into the managed E-drive skill root.
9. Generate a daily skill summary report.

Repository capability classification becomes a secondary or deprecated artifact, not the report driver.

#### 2. What Counts As A Skill Candidate

Python should detect candidate skill packages using concrete file evidence. Strong evidence includes:

- `SKILL.md`
- `skills/**/SKILL.md`
- `AGENTS.md`
- `skills/**/AGENTS.md`
- `codex.md`
- `skills/**/codex.md`
- `references/**`
- `scripts/**`
- supporting markdown or settings files colocated with a skill root

Python should treat a repository section as a skill candidate when:

- there is a recognizable skill root
- the root contains `SKILL.md` or equivalent primary instructions
- and the surrounding files suggest a real package rather than an isolated note

Repositories should not be categorized for reporting purposes beyond whether they contribute candidate skills.

#### 3. Existing Codex Skills Become The Baseline Inventory

Before evaluating daily repository candidates, Haotian should read the current installed skill inventory from Codex roots, with the E-drive root as the primary baseline:

- `E:/CodexHome/skills`
- managed root: `E:/CodexHome/skills/haotian-managed`
- optional additional configured roots for discovery only

Installed skills should become baseline cards. This means the report no longer starts from repositories. It starts from the real Codex skill inventory, then overlays new repository discoveries.

Because the managed root sits underneath the broader E-drive Codex root, inventory scanning must deduplicate by canonical skill directory and stable canonical slug before any baseline cards are created. The same installed skill must never appear twice just because it is visible through both a parent root and the managed child root.

#### 4. Daily Report Becomes Skill-Centric

The daily Markdown and JSON reports should replace capability cards with skill cards.

Each skill card should represent one merged canonical skill and include:

- `name`
- `status`: `已集成` or `需确认`
- `purpose`
- `installed_paths`
- `source_repositories`
- `merged_from`
- `evidence_files`
- `audit_status`
- `first_seen_at`
- `last_seen_at`
- `last_touched_at`

The report should show:

- today-touched installed skills
- newly discovered but not yet integrated skills
- merged skills with multiple repository sources

It should no longer present repository capability taxonomy as the main summary.

#### 5. Merge Rules For Similar Skills

Multiple repositories may expose the same or near-identical skill. Python should perform the first-pass deterministic merge using:

- normalized skill slug
- normalized display name
- declared aliases
- file layout similarity
- purpose-text token similarity
- overlap in key evidence files

If Python reaches high-confidence deterministic agreement, it merges automatically.

If ambiguity remains, Haotian should call Codex during the landing stage to decide:

- whether the candidates are the same practical skill
- what the canonical installed name should be
- whether the candidate should merge into an existing installed skill or remain distinct

#### 6. Installation Root And Full Package Copy

New managed installs must land in:

- `E:/CodexHome/skills/haotian-managed`

`installed_new` must no longer create thin wrappers only.

Instead, Haotian should stage and install a complete copied package built from the discovered source package root, including accepted supporting files such as:

- `SKILL.md`
- `AGENTS.md`
- `codex.md`
- `README.md`
- `references/**`
- `scripts/**`
- package-local configs like `settings.json`

Haotian may still add small managed metadata files, but those must be supplemental. They cannot be the only installed content.

The full-package copy step must use an allowlist and explicit exclusions. It must not copy:

- `.git/**`
- cache or build directories
- vendored dependency trees that are not part of the skill contract
- secret-bearing files such as `.env*`
- temporary files, lockfiles, or editor metadata unrelated to actual skill behavior

#### 7. Python And Codex Responsibility Boundary

Python owns:

- repository collection
- local clone and cleanup
- bounded probing
- candidate extraction
- package completeness checks
- installed skill inventory scanning
- first-pass deterministic merging
- filesystem-safe staging
- audit invocation
- copy/install/rollback
- report generation

Codex is called only when a candidate is ready for landing and a deterministic rule is insufficient. Codex decides:

- merge or not
- canonical naming
- final acceptance summary
- audit interpretation when a decision needs language-level reasoning

This keeps most of the pipeline programmable and repeatable.

#### 8. Status Semantics

`已集成` means:

- the skill already exists in Codex and was aligned, or
- a full package was newly installed into the managed E-drive root

`需确认` means:

- the candidate was discovered but still needs landing-stage Codex judgment, or
- audit or merge resolution is still pending

Wrapper-only placeholder directories must never be reported as `已集成`.

### Data Model Changes

The new daily JSON report should center on:

- `installed_skill_cards`
- `discovered_skill_cards`
- `merged_skill_cards`
- `daily_skill_summary`
- `skill_sync_summary`
- `artifact_links`

Deprecated or secondary report fields:

- repository capability buckets
- taxonomy gap as the primary summary concept

Run artifacts should add or refocus around:

- `skill-candidates.json`
- `skill-merge-decisions.json`
- `skill-sync-report.json`

### Safety Rules

- No install without audit.
- No install of wrapper-only placeholders.
- No install outside `E:/CodexHome/skills/haotian-managed`.
- No direct in-place modification of upstream repository clones.
- No partial install; failed installs must roll back atomically.
- No claim of `已集成` unless the installed directory contains a complete accepted package.

### Rollout

1. Replace capability-centric reporting with skill-centric reporting.
2. Replace wrapper-only install logic with full-package managed installs.
3. Move managed root to the E-drive Codex skill directory.
4. Add baseline installed-skill card generation.
5. Add deterministic merge plus Codex landing-stage resolution.
6. Verify a real Haotian run end-to-end.

## 中文版

### 概述

这次重构会把 Haotian 从“仓库能力分类器”改成“Codex skill 的发现、合并、审计、安装流水线”。

新的系统应该做到：

1. 不再把仓库 taxonomy 分类作为主输出。
2. 只读取仓库内容，判断其中是否存在可落地的 skill 包或可转成 skill 的部分。
3. 每日报告主视角改成“合并后的 skill 卡片”，而不是“仓库能力卡片”。
4. 先读取当前 Codex 已安装的 skills，并把它们作为基线卡片。
5. 多个仓库里发现的类似 skill 自动合并成一个 canonical skill。
6. 新 skill 安装到 `E:/CodexHome/skills/haotian-managed`，并复制完整 skill 内容包，而不是只写一个薄 wrapper。
7. 确定性的发现、提取、安装、报告尽量由 Python 完成；只有在候选 skill 进入“真正要落地”的阶段，才调用 Codex 去做合并、命名和最终接纳判断。

### 问题定义

当前 Haotian 还保留着比较重的 capability-intelligence 影子：

- 每日报告仍以 capability 卡片和 taxonomy gap 为主，而不是具体的 skill 集合。
- 仓库分析还在花很多精力做 taxonomy 分类，但你现在希望仓库只用于发现 skill 潜力。
- 当前的 `installed_new` 会生成 `haotian-managed` 目录，但里面很多只是 `SKILL.md + haotian-wrapper.json`，并不是完整可用 skill。
- 新装 skill 的默认落点还在用户目录下，而不是你要求的 E 盘 Codex skill 根目录。
- 每日报告数字和 `haotian-managed` 目录数量经常对不上，因为前者是报告抽象，后者是历史累计目录。

这会导致报告高估真实 skill 的可用性，也会让你难以把日报当成实际的 skill inventory 来看。

### 目标

- 把 Haotian 改成真正的 skill-first 流水线。
- 仓库分析只做 skill 发现，不再做仓库 capability 分类主线。
- 每日报告只围绕具体 skill 集合来写。
- 把当前已安装的 Codex skills 纳入日报基线卡片。
- 多个仓库里的类似 skill 自动合并。
- 新 skill 统一安装到 `E:/CodexHome/skills/haotian-managed`。
- 安装时复制完整 skill 内容包，包括 `SKILL.md`、`references/`、`scripts/`、支持性 markdown、配置文件等。
- 确定性的发现、打包、安装、报告由 Python 实现。
- 只有当 skill 候选进入落地阶段时，才调用 Codex 去做：
  - 是否并入现有 skill
  - canonical 命名
  - 审计/上下文综合后的最终接纳判断

### 非目标

- 不再以仓库 capability taxonomy 分类作为核心产物。
- 不再把 taxonomy gap 作为管理视角主轴。
- 不安装未审计或半成品 skill。
- 不直接修改第三方上游仓库。
- 不把 wrapper-only 的目录当成真实已安装 skill。

### 设计

#### 1. 主流程从“能力分类”切到“Skill 发现”

新的主流程是：

1. 抓取 Trending 仓库。
2. 本地深读仓库内容。
3. 从仓库里提取 skill 候选。
4. 和当前已安装的 Codex skills 做对比。
5. 在多个仓库之间做去重和合并。
6. 做安装前审计与完整性检查。
7. 只有在 Python 规则无法完全决定时，才调用 Codex 参与落地判断。
8. 把通过的 skill 安装进 E 盘 managed skill 根目录。
9. 生成每日 skill 摘要报告。

repo capability classification 会退化成 secondary artifact，或者被逐步废弃，不再驱动日报。

#### 2. 什么算 Skill 候选

Python 需要基于明确文件证据来发现 skill 包。强信号包括：

- `SKILL.md`
- `skills/**/SKILL.md`
- `AGENTS.md`
- `skills/**/AGENTS.md`
- `codex.md`
- `skills/**/codex.md`
- `references/**`
- `scripts/**`
- 与 skill 根同目录的支持性 markdown 或配置文件

当某个仓库部分同时满足下面条件时，应视为一个 skill 候选：

- 存在明确的 skill 根目录
- skill 根包含 `SKILL.md` 或等价主说明文件
- 周边文件看起来像真实 skill 包，而不是单独的一页笔记

这里不再要求把仓库先归到 taxonomy 类目里。

#### 3. 当前 Codex 已安装 Skills 先成为基线

在处理当天仓库候选之前，Haotian 先读取当前 Codex 的已安装 skill inventory，E 盘根目录是主基线：

- `E:/CodexHome/skills`
- managed 根：`E:/CodexHome/skills/haotian-managed`
- 其他可配置 skill 根只做辅助发现

这些已安装 skill 会先变成基线卡片。  
也就是说，日报的出发点不再是仓库，而是“当前真实的 Codex skill inventory”，然后再把当天从仓库里发现的 skill 合并进来。

由于 managed 根目录就在更大的 `E:/CodexHome/skills` 下面，所以 inventory 扫描时必须先按 canonical skill 目录和稳定 canonical slug 去重，避免同一个已安装 skill 因为同时出现在父根和子根里而被重复统计。

#### 4. 每日报告改成 Skill-Centric

Markdown 和 JSON 都要把 capability cards 改成 skill cards。

每张 skill card 代表一个“合并后的 canonical skill”，包含：

- `name`
- `status`：`已集成` 或 `需确认`
- `purpose`
- `installed_paths`
- `source_repositories`
- `merged_from`
- `evidence_files`
- `audit_status`
- `first_seen_at`
- `last_seen_at`
- `last_touched_at`

日报应该展示：

- 今天触达或变化过的已集成 skills
- 今天新发现但还没完成集成的 skills
- 由多个仓库合并而来的 skills

而不是继续把 repo taxonomy 当成摘要主体。

#### 5. 类似 Skill 的合并规则

多个仓库可能带来本质相同或非常接近的 skill。Python 先做第一轮确定性合并，依据包括：

- 规范化后的 slug
- 规范化后的 display name
- 已声明 alias
- 文件结构相似度
- 用途文本 token 相似度
- 关键证据文件重叠度

如果 Python 能高置信自动判断，就直接合并。

如果仍有歧义，则在落地阶段调用 Codex 去判断：

- 这些候选是不是同一个实际 skill
- canonical 名称应该是什么
- 应该并入现有已安装 skill，还是保留为独立 skill

#### 6. 安装根目录与完整包复制

新的 managed 安装根目录必须是：

- `E:/CodexHome/skills/haotian-managed`

`installed_new` 不能再只生成薄 wrapper。

它必须从发现到的源 skill 根目录里复制完整 skill 包，允许带上这些支持文件：

- `SKILL.md`
- `AGENTS.md`
- `codex.md`
- `README.md`
- `references/**`
- `scripts/**`
- 像 `settings.json` 这样的 package 内配置文件

Haotian 可以额外加一点 metadata，但那些文件只能是附加信息，不能替代原 skill 包内容本身。

完整包复制时必须采用 allowlist，并显式排除这些内容：

- `.git/**`
- cache 或 build 目录
- 不属于 skill 契约的 vendored dependency tree
- 像 `.env*` 这样的秘密文件
- 与实际 skill 行为无关的临时文件、锁文件、编辑器元数据

#### 7. Python 与 Codex 的职责边界

Python 负责：

- 仓库抓取
- 本地 clone 和清理
- 有预算的深度探针
- 候选提取
- skill 完整性检查
- 已安装 skill inventory 扫描
- 第一轮确定性合并
- 安全 staging
- 调用审计脚本
- 复制、安装、回滚
- 报告生成

Codex 只在“准备落地但 Python 无法完全决策”的阶段被调用，用于决定：

- 合并还是不合并
- canonical 命名
- 最终接纳结论
- 当审计或上下文需要语言级判断时，做综合解释

这样能保证大部分流程仍然是可编程、可重复的。

#### 8. 状态语义

`已集成` 的定义必须明确：

- 要么这个 skill 已经存在于 Codex 中并被成功对齐
- 要么一个完整 skill 包已经被新安装到 E 盘 managed 根目录

`需确认` 表示：

- 已经发现了 skill 候选，但还需要落地阶段的 Codex 判断
- 或者审计/合并决策还没有收口

只有 wrapper 的目录绝不能再显示成 `已集成`。

### 数据模型变化

新的日报 JSON 结构应围绕以下对象：

- `installed_skill_cards`
- `discovered_skill_cards`
- `merged_skill_cards`
- `daily_skill_summary`
- `skill_sync_summary`
- `artifact_links`

会被降级或废弃成次级信息的字段包括：

- repo capability bucket
- taxonomy gap 作为主摘要概念

运行产物则新增或改造成围绕这些文件：

- `skill-candidates.json`
- `skill-merge-decisions.json`
- `skill-sync-report.json`

### 安全规则

- 未审计不得安装。
- wrapper-only 目录不得算安装成功。
- 不得安装到 `E:/CodexHome/skills/haotian-managed` 之外。
- 不得直接改写上游 clone 仓库。
- 安装失败必须原子回滚。
- 只有安装目录内存在完整接受包时，才能在报告里标成 `已集成`。

### 推进顺序

1. 先把 capability-centric 报告替换成 skill-centric 报告。
2. 把 wrapper-only 安装逻辑换成完整包复制安装。
3. 把 managed 根目录迁到 E 盘 Codex skill 目录。
4. 把“现有已安装 skills 的基线卡片”补进来。
5. 加上第一轮确定性合并和第二轮 Codex 落地决策。
6. 最后跑一轮真实 Haotian 流程验证。
