# Haotian

Haotian 现在是一个 repository-native Codex skill，用来刷新 GitHub Trending 上的 AI/Agent 项目、按本地 taxonomy 做能力分类，并生成本地 Markdown/JSON 报告。

它不再提供网页对话、CLI 对话或 Telegram 机器人，也不再依赖 `OPENAI_API_KEY`。能力分类由 Codex 在 skill 工作流中完成，Python 只负责抓取、入库、校验和产物生成。

## 项目作用

- 抓取 GitHub Trending 的 `daily` / `weekly` / `monthly` 仓库
- 补充 README / topics 等元数据
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

5. 再运行同一个命令完成最终入库与报告生成：

```bash
python start_haotian.py --date 2026-03-23
```

如果你在 Codex 中使用本仓库，直接调用根目录的 `Haotian` skill 即可，skill 会按上面的两阶段流程执行。

## 输出产物

- `data/runs/YYYY-MM-DD/classification-input.json`
- `data/runs/YYYY-MM-DD/classification-output.json`
- `data/runs/YYYY-MM-DD/run-summary.json`
- `data/reports/YYYY-MM-DD.md`
- `data/reports/YYYY-MM-DD.json`

## 配置说明

常用环境变量见 [`.env.example`](.env.example)：

- `DATABASE_URL`：SQLite 连接串，默认 `sqlite:///./data/app.db`
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

## 文档

- 运行说明见 [`docs/ops.md`](docs/ops.md)
- 架构说明见 [`docs/architecture.md`](docs/architecture.md)
- 能力 taxonomy 见 [`docs/capability-taxonomy.md`](docs/capability-taxonomy.md)
