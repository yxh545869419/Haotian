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

### 4. 完成最终入库与报告生成

再次执行同一个命令：

```bash
python start_haotian.py --date 2026-03-23
```

成功后会得到：

- `data/reports/2026-03-23.md`
- `data/reports/2026-03-23.json`
- `data/runs/2026-03-23/run-summary.json`

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
Get-Content data/runs/2026-03-23/run-summary.json
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

## 不再支持的旧入口

以下能力已经移除：

- 网页聊天
- 交互式 CLI 聊天
- Telegram bridge
- Python 内直接调用 OpenAI API 分类
