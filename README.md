# Haotian

Haotian 现在是一个 repository-native Codex skill，用来刷新 GitHub Trending 上的 AI/Agent 项目、按本地 taxonomy 做能力分类，并生成本地 Markdown/JSON 报告。

它不再提供网页对话、CLI 对话或 Telegram 机器人，也不再依赖 `OPENAI_API_KEY`。能力分类由 Codex 在 skill 工作流中完成，Python 只负责抓取、入库、校验和产物生成。

在深度分析阶段，程序会先把目标仓库克隆到 `TMP_REPO_DIR` 下的临时目录，在本地做有边界的 probe，再把分析快照写入运行产物和报告数据。分析结束后会尝试删除临时 clone，通常会成功；如果清理失败，临时工作区可能会保留，并会通过 cleanup warnings / cleanup_completed state 暴露。程序会按批次自动完成当日所有需要深挖的仓库，同名仓库会优先复用历史深挖结果；只有当仓库再次上榜且 `pushed_at` 相比缓存结果推进至少 90 天时，才会重新深挖。克隆失败或探测失败时，流程会自动降级为 fallback analysis。

## 项目作用

- 抓取 GitHub Trending 的 `daily` / `weekly` / `monthly` 仓库
- 补充 README / topics 等元数据
- 先在临时本地 clone 上做 bounded probing，保留 `analysis_depth`、`matched_files`、`probe_summary` 和 `evidence_snippets`
- 分析后尝试删除临时 clone，通常会清理成功；失败时会保留临时工作区并上报清理状态
- 生成待分类工件 `classification-input.json`
- 让 Codex 按 [`docs/capability-taxonomy.md`](docs/capability-taxonomy.md) 写回 `classification-output.json`
- 将分类结果写入本地 SQLite，并生成最终报告

## 环境要求

- Python `>= 3.11`
- 推荐先升级 pip：`python -m pip install --upgrade pip`

## 需要提前安装的依赖

运行时依赖：

- `beautifulsoup4`
- `python-dotenv`
- `pydantic`

测试依赖：

- `pytest`

安装命令：

```bash
python -m pip install -e .
```

如果你也要运行测试：

```bash
python -m pip install -e ".[test]"
```

## 快速开始

1. 可选：复制环境变量模板

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

2. 安装依赖：`python -m pip install -e .`
3. 先运行一次，生成待分类工件：

```bash
python start_haotian.py --date 2026-03-23
```

4. 当输出里的 `status` 是 `awaiting_classification` 时：
   - 打开输出中的 `classification_input`
   - 读取 [`docs/capability-taxonomy.md`](docs/capability-taxonomy.md)
   - 由 Codex 在同目录写入 `classification-output.json`
   - 其中 `reason` 和 `summary` 使用中文

5. 再运行同一个命令完成最终入库与报告生成：

```bash
python start_haotian.py --date 2026-03-23
```

如果你在 Codex 中使用本仓库，直接调用根目录的 `Haotian` skill 即可，skill 会按上面的两阶段流程执行。

## 输出产物

- `data/runs/YYYY-MM-DD/classification-input.json`
- `data/runs/YYYY-MM-DD/classification-output.json`
- `data/runs/YYYY-MM-DD/capability-audit.json`
- `data/runs/YYYY-MM-DD/taxonomy-gap-candidates.json`
- `data/runs/YYYY-MM-DD/run-summary.json`
- `data/reports/YYYY-MM-DD.md`
- `data/reports/YYYY-MM-DD.json`

## 配置说明

常用环境变量见 [`.env.example`](.env.example)：

- `DATABASE_URL`：SQLite 连接串，默认 `sqlite:///./data/haotian.db`
- `TMP_REPO_DIR`：临时仓库 clone 目录，分析后会尝试清理；通常会成功，失败时会保留临时工作区并暴露清理状态
- `MAX_REPO_PROBE_FILES`：单仓库最多探测的文件数
- `MAX_REPO_PROBE_FILE_BYTES`：单文件探测字节上限
- `MAX_EVIDENCE_SNIPPETS`：单仓库最多保留的证据片段数
- `MAX_DEEP_ANALYSIS_REPOS`：每个深度分析批次允许处理的仓库数量；程序会自动继续后续批次
- `REPORT_DIR`：最终 Markdown / JSON 报告目录，默认 `./data/reports`
- `RUN_DIR`：分阶段工件目录，默认 `./data/runs`

当前不需要这些旧配置：

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `LLM_PROVIDER`
- `TelegramBotToken`

## 常用命令

安装运行依赖：

```bash
python -m pip install -e .
```

安装运行依赖和测试依赖：

```bash
python -m pip install -e ".[test]"
```

运行全部测试：

```bash
python -m pytest -q
```

直接执行一次 skill-first 流程入口：

```bash
python start_haotian.py
```

或：

```bash
python -m haotian.main
```

## 排障

如果启动时看到：

```text
Haotian 缺少运行依赖，当前无法启动。
缺失模块：pydantic
请先在项目根目录执行：python -m pip install -e .
```

说明当前解释器没有安装项目依赖。回到项目根目录后，用同一个 Python 解释器重新执行：

```bash
python -m pip install -e .
```

如果要跑测试但提示 `No module named pytest`，执行：

```bash
python -m pip install -e ".[test]"
```

如果第一次运行后没有生成报告，而是得到 `awaiting_classification`，这是正常的。说明还差 Codex 写入 `classification-output.json` 这一步，不是程序卡住。

如果报告里出现 fallback analysis，说明至少部分贡献证据来自 fallback analysis。优先查看 `analysis_depth`、`matched_files`、`evidence_snippets`，再结合 `probe_summary` 判断这次保留了多少证据、是否需要重新分析。运行摘要里的 `cached_reused_repos` 表示本轮直接复用了历史深挖证据、没有重新 clone 的仓库数量。

finalize 阶段现在还会自动做两件事：

- 审计增强候选：低风险、无人工关注、无 fallback 且证据完整的能力会自动提升；审计结果写入 `capability-audit.json`
- 识别 taxonomy 缺口：当天没有落入任何现有 taxonomy 的仓库，会被整理成 `taxonomy-gap-candidates.json`，方便后续扩充 taxonomy

最终生成的 Markdown / JSON 报告现在分成两层：

- Markdown 是给人看的管理摘要，重点展示一句话结论、今日重点、能力摘要卡片和产物路径
- JSON 是给程序读取的标准结构，后续自动化应优先读取 `report_format`、`executive_summary`、`highlights`、`capability_cards` 和 `artifact_links`

## 文档

- 运行说明见 [`docs/ops.md`](docs/ops.md)
- 架构说明见 [`docs/architecture.md`](docs/architecture.md)
- 能力 taxonomy 见 [`docs/capability-taxonomy.md`](docs/capability-taxonomy.md)
