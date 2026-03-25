# Ops Guide

## 运行方式

Haotian 现在采用两阶段运行：

1. `prepare`：抓取数据并生成 `classification-input.json`
2. `finalize`：读取 `classification-output.json`，入库并生成报告

同一个命令会自动判断当前应该执行哪个阶段：

```bash
python start_haotian.py --date 2026-03-23
```

第一次运行通常会得到 `awaiting_classification`。

这类运行会先在 `TMP_REPO_DIR` 下创建临时 clone，按边界限制做 probe，然后把 `analysis_depth`、`matched_files`、`probe_summary` 和 `evidence_snippets` 写进运行快照。分析完成后会尝试删除临时 clone，通常会成功；如果清理失败，临时工作区可能会保留，并会通过 cleanup warnings / cleanup_completed state 暴露。程序会按批次自动继续处理当天所有需要深挖的仓库；如果同名仓库已有历史深挖结果，会直接复用，只有当它再次上榜且 `pushed_at` 相比缓存记录推进至少 90 天时，才会重新深挖。

## 标准操作流程

### 1. 安装依赖

```bash
python -m pip install -e .
```

如果还要跑测试：

```bash
python -m pip install -e ".[test]"
```

### 2. 生成待分类工件

```bash
python start_haotian.py --date 2026-03-23
```

检查输出中的这些字段：

- `status`
- `classification_input`
- `classification_output`
- `run_summary`

这些分析字段不在 runner 的直接输出里，而是在 `classification_input` 对应的 staged artifact 中：

- `analysis_depth`
- `matched_files`
- `probe_summary`
- `evidence_snippets`

### 3. 让 Codex 写入分类结果

Codex 需要：

- 读取 `classification_input`
- 读取 [`docs/capability-taxonomy.md`](capability-taxonomy.md)
- 在同目录写入 `classification-output.json`

要求：

- 顶层必须是 JSON array
- 每个 repo 只能出现一次
- `capability_id` 必须是 taxonomy 中已有的 id
- `confidence` 必须在 `0` 到 `1` 之间
- `reason` 和 `summary` 使用中文
- 优先依据仓库证据，而不是 README 的单独陈述
- 遇到 `fallback` 分析时，在 `reason` 里明确说明

### 4. 完成最终入库与报告生成

再次执行同一个命令：

```bash
python start_haotian.py --date 2026-03-23
```

成功后会得到：

- `data/reports/2026-03-23.md`
- `data/reports/2026-03-23.json`
- `data/runs/2026-03-23/capability-audit.json`
- `data/runs/2026-03-23/taxonomy-gap-candidates.json`
- `data/runs/2026-03-23/run-summary.json`

Markdown 报告现在是管理摘要，适合人快速阅读；JSON 报告是程序后续识别内容的标准结构。后续自动化应优先读取 `report_format`、`executive_summary`、`highlights`、`capability_cards` 和 `artifact_links`，不要依赖解析自由文本 Markdown。能力卡片里仍然会保留分析深度、回退与清理状态等关键字段；如果看到 `fallback analysis`，说明至少部分贡献证据来自 fallback analysis。`run-summary.json` 中的 `cached_reused_repos` 表示本轮复用了历史深挖证据的仓库数量。

finalize 之后会额外输出：

- `capability-audit.json`：自动增强审计结果，包括自动提升项、仍有风险的增强候选，以及需要人工关注的内容
- `taxonomy-gap-candidates.json`：当天未能落入现有 taxonomy 的仓库候选，用于后续扩充 taxonomy

## 常用检查

运行全部测试：

```bash
python -m pytest -q
```

查看最近一次 Markdown 报告：

```bash
type data\\reports\\2026-03-23.md
```

PowerShell:

```powershell
Get-Content data/reports/2026-03-23.md
```

查看最近一次 JSON 报告：

```powershell
Get-Content data/reports/2026-03-23.json
```

## 常见问题

### 缺少运行依赖

如果看到：

```text
Haotian 缺少运行依赖，当前无法启动。
```

请在项目根目录重新执行：

```bash
python -m pip install -e .
```

### 没有生成报告

如果 `status` 是 `awaiting_classification`，说明流程仍停在第一阶段。需要先让 Codex 写入 `classification-output.json`，再重新运行命令。

### 分类输出校验失败

优先检查：

- 是否是合法 JSON
- `repo_full_name` 是否在 `classification-input.json` 中出现过
- `capability_id` 是否来自 taxonomy
- `needs_review` 是否是布尔值

### 深度分析预算耗尽

`MAX_DEEP_ANALYSIS_REPOS` 现在表示单个深度分析批次的大小，不再表示整轮只允许分析这么多仓库。程序会自动继续处理后续批次，因此正常情况下不会再因为仓库数量多而直接触发 budget fallback。只有 clone 或 probe 本身失败时，相关仓库才会进入 fallback analysis。

## 不再支持的旧入口

以下能力已经移除：

- 网页聊天
- 交互式 CLI 聊天
- Telegram bridge
- Python 内直接调用 OpenAI API 分类
