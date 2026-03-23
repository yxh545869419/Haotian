# Haotian Deep Repository Analysis Design

## Goal

Upgrade `Haotian` from metadata-level repository classification into a deeper, evidence-driven analysis skill. The upgraded system should:

- temporarily clone selected GitHub Trending repositories to local disk
- inspect repository structure, key config files, documentation, and representative source files
- extract structured evidence before Codex performs capability classification
- delete the temporary local repository copy after analysis completes
- generate Chinese reports that explain capability conclusions with concrete evidence

The goal is not to turn Haotian into a full static-analysis platform. The goal is to improve classification quality by moving from README-only signals to bounded, repeatable repository probing.

## Scope

### In scope

- Add a temporary local clone stage for repository analysis
- Define deterministic repository probes with bounded file and size budgets
- Expand classification input artifacts to include deep-analysis evidence
- Prioritize documentation and skill-oriented signals such as `skill*`, `*.md`, `agents/`, `docs/`, `prompts/`, and `skills/`
- Delete cloned repositories after analysis, with explicit cleanup status reporting
- Update Markdown and JSON reports to show evidence depth and fallback conditions
- Add tests for probe selection, cleanup, downgrade behavior, and report rendering

### Out of scope

- Full-repository indexing or exhaustive source traversal
- Persistent local mirrors of analyzed repositories
- Full dependency graph construction for every repository
- Runtime execution, sandboxed builds, or code execution inside cloned repositories
- Replacing Codex taxonomy reasoning with Python heuristics

## Current State Summary

Haotian currently classifies repositories using:

- GitHub Trending metadata
- repository description
- README excerpt
- repository topics
- light candidate text extraction

This is useful, but still shallow. It misses many high-signal artifacts that often define an AI/agent repository more accurately than the README:

- `package.json`, `pyproject.toml`, `requirements.txt`, `Dockerfile`
- workflow and automation files in `.github/workflows/`
- root or docs markdown files that explain product boundaries
- `skill*` files and skill-package structures
- representative source files such as `main`, `server`, `cli`, `agent`, or `workflow` entrypoints

As a result, current reports are still best understood as metadata-based judgments, not repository-research outputs.

## Recommended Approach

Use a layered deep-analysis pipeline with temporary local clones and bounded evidence probes.

### Why this approach

This design improves analysis quality without making Haotian too slow or fragile. It keeps Python responsible for deterministic local probing, keeps Codex responsible for capability reasoning, and limits blast radius through strict budgets and cleanup guarantees.

## Architecture

### 1. Temporary repository workspace

For each repository selected for analysis, Haotian should create a temporary local workspace under a deterministic root such as:

- `data/tmp/repos/YYYY-MM-DD/<repo-slug>/`

The repository is cloned with:

- shallow clone only
- default branch only
- no long-term retention

After analysis, the local clone should be deleted immediately. Cleanup must run in `finally` logic so that both success and failure paths attempt deletion.

Optional future debug mode may preserve failed workspaces, but default behavior must delete them.

### 2. Two-layer repository probing

#### Layer 1: universal probe

Every repository gets the same first-pass probe:

- root file list
- directory list at shallow depth
- `README*`
- root `*.md`
- root `skill*`
- `package.json`
- `pyproject.toml`
- `requirements.txt`
- `poetry.lock`
- `uv.lock`
- `Dockerfile`
- `.github/workflows/*`
- `agents/*`
- `docs/*`
- `prompts/*`
- `skills/*`

The purpose of Layer 1 is to capture structure and intent without reading too much code.

#### Layer 2: targeted probe

Only if Layer 1 detects relevant signals should Haotian continue into representative source inspection.

Priority filename patterns should include:

- `skill*`
- `*.md`
- `main*`
- `app*`
- `server*`
- `cli*`
- `agent*`
- `workflow*`
- `orchestr*`
- `tool*`
- `browser*`
- `rag*`
- `retriev*`
- `codegen*`

Priority directories should include:

- `src/`
- `app/`
- `server/`
- `cli/`
- `agents/`
- `skills/`
- `docs/`
- `prompts/`

This second pass should read only a small number of representative files, not scan the full repository.

### 3. Structured evidence extraction

Python should produce a structured repository evidence package before Codex classification.

Suggested fields for each repository item in `classification-input.json`:

- `analysis_depth`
- `clone_strategy`
- `cleanup_required`
- `cleanup_completed`
- `root_files`
- `matched_files`
- `matched_keywords`
- `architecture_signals`
- `probe_summary`
- `evidence_snippets`
- `analysis_limits`
- `fallback_used`

This evidence package gives Codex higher-quality input while preserving deterministic preprocessing.

### 4. Controlled budgets

To keep the system stable, deep analysis must enforce hard limits:

- maximum clone count per run if needed
- maximum files read per repository
- maximum bytes read per file
- maximum bytes stored per evidence snippet
- maximum number of evidence snippets per capability decision

If a repository exceeds these limits, Haotian should summarize what was skipped in `analysis_limits`.

## Data Flow

### Stage 1: collect

1. Fetch GitHub Trending repositories
2. Persist trending rows
3. Decide which repositories should enter deep analysis

### Stage 2: clone and probe

1. Create temporary local repo directory
2. Run shallow clone
3. Execute Layer 1 probes
4. Conditionally execute Layer 2 probes
5. Extract structured evidence
6. Delete the local clone
7. Record cleanup outcome

### Stage 3: classify

1. Write `classification-input.json` with probe evidence
2. Codex reads taxonomy plus repository evidence
3. Codex writes `classification-output.json`

### Stage 4: finalize

1. Validate classification output
2. Ingest into `repo_capabilities`
3. Update `capability_registry`
4. Generate final Markdown and JSON reports

## Probe Design Details

### Documentation-first signals

Haotian should explicitly treat documentation as first-class evidence. Many AI, agent, and skill-oriented repositories explain their actual boundaries more clearly in markdown than in entrypoint code.

High-priority documentation probes:

- root `README*`
- root `*.md`
- `docs/**/*.md`
- `agents/**/*.md`
- `skills/**/*.md`
- `prompts/**/*.md`
- `skill*`

This is especially important for:

- skill repositories
- methodology repositories
- prompt libraries
- orchestration frameworks
- agent templates

### Representative code signals

When code inspection is triggered, Haotian should prefer representative entry or registration files over large internal implementations.

Examples of useful signals:

- command registration
- tool registry setup
- browser automation libraries
- agent orchestration loops
- retrieval pipelines
- code generation entrypoints
- server bootstraps
- workflow definitions

### Evidence snippets

Evidence snippets should be short, normalized text extracts with file path attribution. They are not meant to reproduce whole files. They exist to justify classification decisions in reports.

Each snippet should include:

- relative path
- short excerpt
- why it matters

## Cleanup and Failure Handling

### Cleanup contract

Every repository analysis must report:

- `clone_started`
- `analysis_completed`
- `cleanup_attempted`
- `cleanup_completed`

If cleanup fails, that is a surfaced warning, not a hidden detail.

### Fallback behavior

If cloning or local probing fails, Haotian should degrade to the existing metadata-level mode:

- repository description
- README via API
- topics
- basic file metadata if available remotely in future

The run should still complete when possible, but the repository evidence must show:

- `analysis_depth: "fallback"`
- `fallback_used: true`

### Large or unusual repositories

If a repository is too large, has nonstandard structure, or yields too many probe hits:

- stop at budget limits
- record skipped work in `analysis_limits`
- continue with partial evidence

## Reporting Design

### Markdown report

Keep the report readable and concise. The Markdown report should show:

- high-level capability summary
- evidence-backed capability sections
- analysis depth indicator
- key matched files
- 1-3 short evidence snippets where useful
- note when the result came from fallback analysis rather than deep local probing

### JSON report

The JSON report should be more structured and preserve fields needed for downstream automation:

- `analysis_depth`
- `matched_files`
- `matched_keywords`
- `probe_summary`
- `evidence_snippets`
- `fallback_used`
- `cleanup_completed`

## Testing Strategy

### Unit tests

Add unit coverage for:

- probe path matching
- keyword matching, including `skill*` and `*.md`
- evidence snippet truncation
- file budget enforcement
- cleanup state handling
- report rendering for deep-analysis evidence

### Integration tests

Use fixture repositories stored locally for deterministic tests. These should simulate:

- a skill-heavy repo
- a code-heavy agent repo
- a docs-heavy methodology repo
- a clone failure or missing repo case

Each integration test should verify:

- evidence extraction
- expected fallback behavior
- clone directory deletion after analysis

### Regression tests

Ensure:

- the pipeline still works without any deep-analysis signals
- report generation remains stable
- invalid or partial probe output does not break final report creation

## Documentation Changes

Update:

- `README.md`
- `docs/architecture.md`
- `docs/ops.md`
- `SKILL.md`

The docs should explain:

- that Haotian now temporarily clones repositories for analysis
- that local copies are deleted after probing
- how fallback mode works
- what evidence appears in reports
- what file patterns and directories are prioritized

## Risks

### Risk: clone-heavy runs become slow

Mitigation:

- shallow clone only
- strict file budgets
- targeted second-pass probing

### Risk: cleanup failures leave local residue

Mitigation:

- cleanup in `finally`
- explicit cleanup status in run artifacts
- surfaced warnings in reports and summaries

### Risk: markdown and docs dominate classification too much

Mitigation:

- combine doc signals with code/config signals
- mark `analysis_depth`
- retain matched file attribution so decisions stay auditable

### Risk: large repositories distort evidence quality

Mitigation:

- bounded file count
- representative-file selection only
- explicit `analysis_limits` disclosure

## Final Recommendation

Upgrade Haotian to a temporary-clone, evidence-driven repository analysis workflow. Use deterministic Python probes to inspect bounded local copies of repositories, prioritize `skill*` and `*.md` alongside critical config and entry files, delete local clones immediately after analysis, and hand structured evidence to Codex for taxonomy classification. This gives Haotian a much more credible “researched” output while preserving speed, repeatability, and operational clarity.

---

# Haotian Deep Repository Analysis Design（中文版）

## 目标

把 `Haotian` 从“基于仓库元数据的分类”升级为“基于仓库深度证据的分析型 skill”。升级后的系统需要：

- 临时把选中的 GitHub Trending 仓库拉到本地
- 检查仓库结构、关键配置文件、文档和代表性源码文件
- 在 Codex 做 capability 分类前先提取结构化证据
- 分析完成后删除本地临时仓库副本
- 生成带有具体证据说明的中文报告

目标不是把 Haotian 变成一个完整静态分析平台，而是在可控、可重复的边界内，把分类依据从 README 级信号提升到“仓库研究”级信号。

## 范围

### 包含内容

- 新增临时本地 clone 阶段
- 定义带预算限制的确定性仓库探针
- 扩展 `classification-input.json`，让它携带深度分析证据
- 优先纳入 `skill*`、`*.md`、`agents/`、`docs/`、`prompts/`、`skills/` 这类文档和 skill 相关信号
- 分析完成后删除 clone 下来的本地仓库，并明确记录清理状态
- 更新 Markdown/JSON 报告，展示证据深度和降级情况
- 新增探针、清理、降级和报告渲染相关测试

### 不包含内容

- 对整个仓库做穷尽式索引或全量源码遍历
- 长期保留本地仓库镜像
- 为每个仓库构建完整依赖图
- 在 clone 下来的仓库里执行构建、运行或动态分析
- 用 Python 启发式完全替代 Codex taxonomy 推理

## 当前状态摘要

Haotian 当前的分类输入主要来自：

- GitHub Trending 元数据
- 仓库描述
- README 摘要
- 仓库 topics
- 轻量 candidate text 提取

这些信息有价值，但仍然偏浅。很多 AI、agent 和 skill 仓库的真实边界，并不写在 README 第一屏里，而是分散在这些高信号文件中：

- `package.json`、`pyproject.toml`、`requirements.txt`、`Dockerfile`
- `.github/workflows/` 下的自动化文件
- 根目录或 `docs/` 里的 markdown 说明
- `skill*` 文件以及 skill package 结构
- `main`、`server`、`cli`、`agent`、`workflow` 等代表性入口文件

因此现在的报告更准确地说，还是“基于元数据的判断”，还不能算“做过仓库研究以后的结果”。

## 推荐方案

采用“分层深挖 + 临时本地 clone + 预算受控探针”的方式。

### 为什么推荐这个方案

这个设计能明显提升分析质量，又不会让 Haotian 变成一个又慢又脆的重型扫描器。Python 继续负责确定性探测和证据整理，Codex 继续负责 taxonomy 推理，整体边界仍然清楚。

## 架构设计

### 1. 临时仓库工作区

对于每个进入深挖流程的仓库，Haotian 应在固定根目录下创建临时工作区，例如：

- `data/tmp/repos/YYYY-MM-DD/<repo-slug>/`

clone 规则：

- 只做浅克隆
- 只拉默认分支
- 不做长期保留

分析完成后，立即删除本地副本。清理逻辑必须放在 `finally` 中，确保成功和失败路径都会尝试删除。

未来可以考虑显式调试模式下保留失败现场，但默认行为必须删除。

### 2. 两层仓库探针

#### 第一层：通用探针

所有仓库都执行同一套第一层探针：

- 根目录文件列表
- 浅层目录列表
- `README*`
- 根目录 `*.md`
- 根目录 `skill*`
- `package.json`
- `pyproject.toml`
- `requirements.txt`
- `poetry.lock`
- `uv.lock`
- `Dockerfile`
- `.github/workflows/*`
- `agents/*`
- `docs/*`
- `prompts/*`
- `skills/*`

第一层的目标是在不读太多源码的前提下，尽快抓到结构和定位信号。

#### 第二层：定向探针

只有当第一层命中有效信号时，才继续进入代表性源码检查。

优先文件名模式建议包括：

- `skill*`
- `*.md`
- `main*`
- `app*`
- `server*`
- `cli*`
- `agent*`
- `workflow*`
- `orchestr*`
- `tool*`
- `browser*`
- `rag*`
- `retriev*`
- `codegen*`

优先目录建议包括：

- `src/`
- `app/`
- `server/`
- `cli/`
- `agents/`
- `skills/`
- `docs/`
- `prompts/`

第二层只读取少量代表文件，而不是把整个仓库全扫一遍。

### 3. 结构化证据提取

在 Codex 做 capability 分类之前，Python 应先产出结构化的仓库证据包。

建议在每个仓库的 `classification-input.json` 项里增加：

- `analysis_depth`
- `clone_strategy`
- `cleanup_required`
- `cleanup_completed`
- `root_files`
- `matched_files`
- `matched_keywords`
- `architecture_signals`
- `probe_summary`
- `evidence_snippets`
- `analysis_limits`
- `fallback_used`

这样 Codex 看到的就不再只是 README 和描述，而是一组可审计、可解释的仓库分析证据。

### 4. 成本控制

为了保持流程稳定，深挖必须有硬性预算限制：

- 每次运行最多深挖多少仓库
- 每个仓库最多读取多少文件
- 每个文件最多读取多少字节
- 每条证据摘录最多保留多少字节
- 每个 capability 决策最多引用多少条证据

如果超出预算，就把跳过的信息写进 `analysis_limits`。

## 数据流

### 第一阶段：采集

1. 抓取 GitHub Trending 仓库
2. 写入 trending 数据
3. 决定哪些仓库进入深挖分析

### 第二阶段：clone 与探针分析

1. 创建临时本地仓库目录
2. 执行浅克隆
3. 运行第一层探针
4. 按命中情况决定是否运行第二层探针
5. 提取结构化证据
6. 删除本地 clone
7. 记录清理结果

### 第三阶段：分类

1. 把探针证据写进 `classification-input.json`
2. Codex 读取 taxonomy 和仓库证据
3. Codex 生成 `classification-output.json`

### 第四阶段：收尾

1. 校验分类输出
2. 写入 `repo_capabilities`
3. 更新 `capability_registry`
4. 生成 Markdown 和 JSON 报告

## 探针设计细节

### 文档优先信号

Haotian 应明确把文档视为一等证据。很多 AI、agent、skill 仓库的真实产品边界，在 markdown 里比在入口代码里更清楚。

高优先级文档探针包括：

- 根目录 `README*`
- 根目录 `*.md`
- `docs/**/*.md`
- `agents/**/*.md`
- `skills/**/*.md`
- `prompts/**/*.md`
- `skill*`

这对这些项目尤其重要：

- skill 仓库
- 方法论仓库
- prompt 库
- orchestration framework
- agent 模板仓库

### 代表性代码信号

当代码探针被触发时，Haotian 应优先读取代表性入口和注册文件，而不是大量内部实现。

例如：

- 命令注册
- 工具注册表
- 浏览器自动化能力接线
- agent orchestration 主循环
- retrieval pipeline
- code generation 入口
- server 启动逻辑
- workflow 定义

### 证据摘录

证据摘录应是短文本片段，并带文件路径归属，不应该复制整段文件内容。它的作用是帮助解释为什么某个 capability 判断成立。

每条摘录应包含：

- 相对路径
- 短摘录
- 这条摘录为什么重要

## 清理与失败处理

### 清理契约

每个仓库分析都要明确记录：

- `clone_started`
- `analysis_completed`
- `cleanup_attempted`
- `cleanup_completed`

如果清理失败，这必须是可见告警，不能悄悄吞掉。

### 降级行为

如果 clone 或本地探针失败，Haotian 应降级回现有的元数据模式：

- 仓库描述
- 通过 API 获取的 README
- topics
- 未来如果需要可补远程文件元数据

整个日报在可能情况下仍应继续完成，但仓库证据里必须明确标注：

- `analysis_depth: "fallback"`
- `fallback_used: true`

### 大仓库和异常结构仓库

如果仓库太大、结构太特殊或命中过多文件：

- 到预算上限就停止
- 在 `analysis_limits` 中记录被跳过的部分
- 用部分证据继续完成分析

## 报告设计

### Markdown 报告

Markdown 应继续保持“可读简报”的定位，不要变成大段源码 dump。

建议展示：

- 高层 capability 摘要
- 带证据的 capability 分区
- 分析深度标记
- 命中的关键文件
- 1 到 3 条短证据摘录
- 如果是降级分析结果，要明确标出“分析深度受限”

### JSON 报告

JSON 报告应保留更完整的结构化证据，便于后续自动化处理：

- `analysis_depth`
- `matched_files`
- `matched_keywords`
- `probe_summary`
- `evidence_snippets`
- `fallback_used`
- `cleanup_completed`

## 测试策略

### 单元测试

新增覆盖：

- 探针路径匹配
- 关键词匹配，特别是 `skill*` 和 `*.md`
- 证据摘录截断
- 文件预算限制
- 清理状态处理
- 深挖报告渲染

### 集成测试

主测试应使用本地 fixture 仓库，保持确定性。建议至少模拟：

- skill 特征明显的仓库
- 代码特征明显的 agent 仓库
- 文档特征明显的方法论仓库
- clone 失败或缺失仓库的情况

每个集成测试都要验证：

- 证据提取是否正确
- 降级路径是否生效
- 分析结束后 clone 目录是否已删除

### 回归测试

确保：

- 没有深挖信号时，流水线仍能正常工作
- 报告生成保持稳定
- 即使探针输出不完整，也不会把最终报告直接打崩

## 文档改造

需要更新：

- `README.md`
- `docs/architecture.md`
- `docs/ops.md`
- `SKILL.md`

文档应明确说明：

- Haotian 现在会临时 clone 仓库做分析
- 分析后会删除本地副本
- 降级模式如何工作
- 报告里会展示哪些证据
- 优先关注哪些文件模式和目录

## 风险

### 风险：clone 密集型运行变慢

缓解：

- 只做浅克隆
- 严格预算限制
- 仅对第二层做定向探针

### 风险：清理失败导致本地残留

缓解：

- 在 `finally` 里清理
- 在 run artifact 中记录清理状态
- 在报告和 summary 中明确告警

### 风险：markdown 和文档信号权重过高

缓解：

- 文档信号与代码/配置文件信号组合使用
- 保留 `analysis_depth`
- 保留命中文件归属，确保结论可审计

### 风险：大仓库拉低证据质量

缓解：

- 限制文件数量
- 只取代表文件
- 明确披露 `analysis_limits`

## 最终建议

把 Haotian 升级为“临时 clone + 证据驱动”的仓库分析工作流。由 Python 在本地对仓库副本做有边界的确定性探针分析，优先关注 `skill*`、`*.md`、关键配置文件和代表性入口文件，分析后立刻删除本地 clone，再把结构化证据交给 Codex 做 taxonomy 分类。这样 Haotian 的输出就能更接近“做过仓库研究后的结论”，同时仍然保持速度、可重复性和运维清晰度。
