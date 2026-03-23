# Haotian Skill-First Refactor Design

## Goal

Refactor `Haotian` from a local chat-oriented application into a skill-first repository that Codex can invoke on demand. The refactored repository should:

- run the core trending-analysis pipeline when the `Haotian` skill is explicitly used
- remove built-in chat, web UI, CLI chat, and Telegram interaction layers
- stop depending on `OPENAI_API_KEY` or direct OpenAI API calls
- use Codex reasoning, guided by the project taxonomy, to classify capabilities during skill execution
- persist outputs as local structured artifacts and readable reports

## Scope

### In scope

- Add root-level `SKILL.md` so the repository itself is a Codex skill
- Keep and reshape the Python core around deterministic data processing
- Introduce a stable runner that executes one full analysis cycle and returns artifact paths
- Replace API-based LLM classification with a Codex-driven classification workflow
- Produce both `Markdown` and `JSON` outputs for each run
- Remove chat/web/Telegram/interactive UI code paths, tests, and docs
- Rewrite README and operations docs to describe skill-first usage

### Out of scope

- Building a browser UI
- Preserving interactive conversation features
- Supporting multiple hosted LLM providers from Python
- Automatic execution on Codex startup or project-open

## Current State Summary

The repository currently mixes two concerns:

1. A useful local intelligence pipeline:
   - fetch GitHub trending repositories
   - enrich metadata
   - classify capabilities
   - persist registry state
   - generate reports

2. Several interaction surfaces that are no longer wanted:
   - web chat UI
   - CLI chat
   - Telegram bridge
   - chat-oriented service layer

The existing LLM integration is Python-driven and depends on `OPENAI_API_KEY`. That conflicts with the new requirement that Codex itself should provide the reasoning step when the skill is used.

## Recommended Architecture

### 1. Skill-first repository layout

Add a root `SKILL.md` describing when the Haotian skill should trigger:

- run capability intelligence refreshes
- classify AI/agent repos into the local taxonomy
- produce daily or on-demand capability reports
- inspect previously generated reports and structured outputs

The skill should instruct Codex to:

1. run the local pipeline runner
2. read the generated staging artifacts
3. classify capabilities using the taxonomy in `docs/capability-taxonomy.md`
4. persist normalized capability results back into the local database/report outputs
5. summarize key findings for the current request

### 2. Preserve Python for deterministic work only

Keep Python responsible for:

- fetching trending repositories
- fetching repository metadata
- normalizing and storing raw inputs
- computing diffs and registry transitions once classified data is available
- writing `Markdown` and `JSON` reports

Python should no longer own the primary LLM reasoning path.

### 3. Replace direct API classification with a staged classification flow

Split the current analysis stage into two parts:

#### Stage A: deterministic staging

Python runner creates a structured classification input artifact containing:

- snapshot date
- repo identities and metadata
- candidate text fragments
- taxonomy reference path or embedded taxonomy ids

Suggested artifact path:

- `data/runs/YYYY-MM-DD/classification-input.json`

#### Stage B: Codex-driven classification

When the skill is invoked, Codex reads:

- the generated classification input artifact
- `docs/capability-taxonomy.md`

Codex then produces normalized classification results and writes them to:

- `data/runs/YYYY-MM-DD/classification-output.json`

Python then ingests that output into:

- `repo_capabilities`
- `capability_registry`
- final reports

This keeps reasoning inside Codex while leaving persistence and repeatable mechanics in Python.

### 4. Stable runner entrypoint

Add a dedicated runner module, for example:

- `src/haotian/runner.py`

Responsibilities:

- verify directories and database are ready
- execute collection and metadata enrichment
- generate `classification-input.json`
- optionally ingest an existing `classification-output.json`
- generate final report artifacts
- return a machine-readable summary object

The runner must be usable by both:

- the skill workflow
- focused tests

### 5. Output artifacts

Keep two final outputs per run:

- `Markdown` for human review
- `JSON` for Codex and automation

Suggested output set:

- `data/reports/YYYY-MM-DD.md`
- `data/reports/YYYY-MM-DD.json`
- `data/runs/YYYY-MM-DD/classification-input.json`
- `data/runs/YYYY-MM-DD/classification-output.json`
- optional `data/runs/YYYY-MM-DD/run-summary.json`

## Component Changes

### Remove entirely

- web server and embedded HTML UI
- chat service and chat history features
- CLI chat service
- Telegram integration
- OpenAI API client module
- environment variables related to direct OpenAI access

### Keep and adapt

- collectors
- database schema and registry repository
- diff service
- report generation
- orchestration logic, but reworked around staged classification

### Add

- root `SKILL.md`
- runner entrypoint module
- structured run artifact writers/readers
- tests for staged classification flow and artifact generation

## Data Flow

### Before

Python pipeline -> Python OpenAI client -> classified capabilities -> DB -> report -> optional chat UI

### After

Skill invocation -> Python runner builds raw snapshot -> Codex classifies using taxonomy -> Python ingests classifications -> DB -> Markdown/JSON reports -> Codex summarizes results

## Failure Handling

The new design should degrade gracefully.

### Collection or enrichment failure

- write stage errors into run summary
- continue to generate partial report when possible

### Missing classification output

- runner should stop before final ingest, with a clear message that classification by Codex is still required
- skill should surface this clearly instead of pretending the run is complete

### Invalid classification output

- validate required fields before ingest
- reject malformed records with useful error messages

## Testing Strategy

### Remove obsolete tests

- web server tests
- chat service tests
- Telegram tests
- CLI chat tests
- direct OpenAI client tests

### Keep or adapt

- taxonomy normalization tests
- orchestration/report tests
- config tests where still relevant
- start/runner tests

### Add

- runner generates staged classification input artifact
- ingest of Codex-produced classification output succeeds
- final `Markdown + JSON` reports are created
- skill-facing workflow can complete without any `OPENAI_API_KEY`

## Documentation Changes

Update:

- `README.md`
- `docs/architecture.md`
- `docs/ops.md`

New docs must describe:

- how to use the repository as a skill
- how the staged classification flow works
- where artifacts are written
- that `OPENAI_API_KEY` is no longer required

## Migration Plan

1. Add skill metadata and define skill workflow
2. Introduce runner and staged artifact generation
3. Replace API classification path with classification-input / classification-output flow
4. Update report generation to include JSON output
5. Remove chat/web/CLI/Telegram code and tests
6. Rewrite docs around skill-first usage
7. Verify with focused tests and a full regression pass

## Risks

### Risk: staged classification may feel more complex than direct API calls

Mitigation:

- keep the runner contract simple
- make artifact locations deterministic
- keep JSON schemas narrow and explicit

### Risk: partial old chat abstractions remain coupled to core services

Mitigation:

- isolate runner first
- then delete interaction layers cleanly

### Risk: Codex-generated classification output may vary

Mitigation:

- constrain output schema tightly in `SKILL.md`
- validate before ingest
- keep taxonomy canonical and explicit

## Final Recommendation

Refactor Haotian into a skill-first repository by keeping its Python pipeline as a deterministic local engine and moving capability classification into the Codex skill workflow itself. This satisfies the requirement that the repository becomes a skill, removes no-longer-wanted interaction surfaces, and eliminates the dependency on `OPENAI_API_KEY` while preserving durable local reports and registry state.

---

# Haotian Skill-First Refactor Design（中文版）

## 目标

将 `Haotian` 从一个偏本地聊天交互的应用，重构为一个以 skill 为中心的仓库，供 Codex 按需调用。重构后的仓库需要满足：

- 在显式调用 `Haotian` skill 时执行核心趋势分析流程
- 删除内置聊天、网页 UI、CLI 对话和 Telegram 交互层
- 不再依赖 `OPENAI_API_KEY` 或直接 OpenAI API 调用
- 在 skill 执行过程中，使用 Codex 推理并结合项目 taxonomy 完成能力分类
- 将结果持久化为本地结构化产物和可读报告

## 范围

### 包含内容

- 在仓库根目录新增 `SKILL.md`，让仓库本身成为 Codex skill
- 保留并重塑 Python 核心，使其只负责确定性数据处理
- 引入稳定 runner，用于执行一次完整分析并返回产物路径
- 用 Codex 驱动的分类工作流替代 API 型 LLM 分类
- 每次运行产出 `Markdown` 和 `JSON` 两类结果
- 删除 chat/web/Telegram/交互 UI 相关代码、测试和文档
- 将 README 和运维文档改写为 skill-first 使用方式

### 不包含内容

- 构建浏览器 UI
- 保留交互式对话功能
- 在 Python 中继续支持多个托管 LLM Provider
- 在 Codex 启动或进入项目时自动执行

## 当前状态摘要

仓库当前混合了两类能力：

1. 有价值的本地情报流水线：
   - 抓取 GitHub Trending 仓库
   - 富化元数据
   - 做能力分类
   - 持久化 registry 状态
   - 生成报告

2. 不再需要的交互外壳：
   - Web chat UI
   - CLI chat
   - Telegram bridge
   - chat-oriented service layer

现有 LLM 集成由 Python 直接驱动，并依赖 `OPENAI_API_KEY`。这与新需求冲突，因为现在需要让 Codex 自身在调用 skill 时承担推理分类职责。

## 推荐架构

### 1. 以 skill 为中心的仓库形态

在仓库根目录新增 `SKILL.md`，明确描述 `Haotian` skill 的触发场景：

- 运行 capability intelligence refresh
- 将 AI/agent 相关仓库归类到本地 taxonomy
- 生成每日或按需 capability report
- 查看既有报告和结构化产物

该 skill 应指引 Codex 执行：

1. 运行本地 pipeline runner
2. 读取生成的 staging artifacts
3. 使用 `docs/capability-taxonomy.md` 完成能力分类
4. 将标准化结果写回本地数据库和报告产物
5. 针对当前请求总结重点发现

### 2. 保留 Python 只负责确定性工作

Python 继续负责：

- 抓取 trending repositories
- 获取 repository metadata
- 归整并存储原始输入
- 在分类结果就绪后计算 diff 和 registry 迁移
- 写出 `Markdown` 和 `JSON` 报告

Python 不再承担主要 LLM 推理路径。

### 3. 用 staged classification flow 取代直接 API 分类

将当前 analyze 阶段拆成两段：

#### Stage A：确定性 staging

Python runner 先生成结构化分类输入产物，包含：

- snapshot date
- repo 身份和元数据
- candidate text fragments
- taxonomy reference path 或 taxonomy ids

建议路径：

- `data/runs/YYYY-MM-DD/classification-input.json`

#### Stage B：Codex 驱动分类

skill 被调用时，Codex 读取：

- 上述 classification input artifact
- `docs/capability-taxonomy.md`

然后由 Codex 输出标准化分类结果到：

- `data/runs/YYYY-MM-DD/classification-output.json`

之后再由 Python 将该输出写入：

- `repo_capabilities`
- `capability_registry`
- 最终报告

这样可以把推理留在 Codex 内部，同时让持久化和重复性流程继续由 Python 保证稳定性。

### 4. 稳定 runner 入口

建议新增专门 runner 模块，例如：

- `src/haotian/runner.py`

职责：

- 校验目录和数据库是否就绪
- 执行采集与元数据富化
- 生成 `classification-input.json`
- 在已有 `classification-output.json` 时执行 ingest
- 生成最终报告产物
- 返回一个机器可读 summary object

该 runner 需要同时适配：

- skill 工作流
- 聚焦测试

### 5. 输出产物

每次运行保留两类最终输出：

- `Markdown`：面向人类阅读
- `JSON`：面向 Codex 和自动化流程

建议产物集合：

- `data/reports/YYYY-MM-DD.md`
- `data/reports/YYYY-MM-DD.json`
- `data/runs/YYYY-MM-DD/classification-input.json`
- `data/runs/YYYY-MM-DD/classification-output.json`
- 可选 `data/runs/YYYY-MM-DD/run-summary.json`

## 组件改造

### 完全移除

- web server 和内嵌 HTML UI
- chat service 和 chat history
- CLI chat service
- Telegram integration
- OpenAI API client module
- 所有与直接 OpenAI 访问相关的环境变量

### 保留并改造

- collectors
- database schema 和 registry repository
- diff service
- report generation
- orchestration logic，但要改造成 staged classification 结构

### 新增

- 根目录 `SKILL.md`
- runner 入口模块
- 结构化 run artifact 的读写能力
- 面向 staged classification flow 和 artifact generation 的测试

## 数据流

### 之前

Python pipeline -> Python OpenAI client -> classified capabilities -> DB -> report -> optional chat UI

### 之后

Skill invocation -> Python runner builds raw snapshot -> Codex classifies using taxonomy -> Python ingests classifications -> DB -> Markdown/JSON reports -> Codex summarizes results

## 失败处理

新设计需要具备 graceful degradation。

### 采集或富化失败

- 将 stage errors 写入 run summary
- 在可能情况下继续生成 partial report

### 缺少 classification output

- runner 在最终 ingest 前停止，并明确提示还需要 Codex 完成分类
- skill 需要清晰反馈，而不是伪装成已完成

### classification output 非法

- ingest 前验证必要字段
- 对格式错误记录给出明确错误信息

## 测试策略

### 删除过时测试

- web server tests
- chat service tests
- Telegram tests
- CLI chat tests
- direct OpenAI client tests

### 保留或改造

- taxonomy normalization tests
- orchestration/report tests
- 仍然有价值的 config tests
- start/runner tests

### 新增

- runner 生成 staged classification input artifact
- Codex 产出的 classification output 可以被成功 ingest
- 最终 `Markdown + JSON` 报告会被生成
- skill-facing workflow 在没有任何 `OPENAI_API_KEY` 的情况下也能完成

## 文档改造

需要更新：

- `README.md`
- `docs/architecture.md`
- `docs/ops.md`

新文档应明确描述：

- 如何以 skill 方式使用该仓库
- staged classification flow 的工作方式
- artifact 输出位置
- `OPENAI_API_KEY` 已不再需要

## 迁移计划

1. 添加 skill metadata 并定义 skill workflow
2. 引入 runner 和 staged artifact generation
3. 将 API 分类路径替换为 classification-input / classification-output 流程
4. 更新 report generation，使其支持 JSON 输出
5. 删除 chat/web/CLI/Telegram 代码和测试
6. 按 skill-first 方式重写文档
7. 用聚焦测试和全量回归完成验证

## 风险

### 风险：staged classification 看起来比直接 API 调用更复杂

缓解方式：

- 保持 runner contract 简单
- 让 artifact 路径完全确定
- 保持 JSON schema 窄而明确

### 风险：旧 chat 抽象仍与核心服务耦合

缓解方式：

- 先隔离 runner
- 再干净地删除交互层

### 风险：Codex 生成的 classification output 存在波动

缓解方式：

- 在 `SKILL.md` 中强约束输出 schema
- ingest 前做校验
- 保持 taxonomy canonical 且清晰

## 最终建议

将 Haotian 重构为一个 skill-first 仓库：保留 Python pipeline 作为确定性的本地引擎，把 capability classification 移入 Codex skill workflow。这样既能满足“仓库本身就是 skill”的目标，又能删除不再需要的交互层，同时去掉对 `OPENAI_API_KEY` 的依赖，并继续保留稳定的本地报告和 registry 状态。
