# Haotian

Haotian 是一个本地运行的能力追踪与对话工具，支持：

- 抓取 GitHub Trending 仓库并生成日报
- 基于 taxonomy 归类能力项并写入本地 SQLite
- 启动本地 Web 对话页面或 CLI 对话模式
- 在配置 `TelegramBotToken` 后复用同一套对话服务接入 Telegram

## 环境要求

- Python `>= 3.11`
- 推荐先升级 pip：`python -m pip install --upgrade pip`
- 推荐在项目根目录使用同一个 Python 解释器完成安装、测试和启动

## 需要提前安装的依赖

项目的直接依赖已经定义在 [`pyproject.toml`](/E:/Haotian/pyproject.toml) 中。

运行时依赖：

- `beautifulsoup4`
- `python-dotenv`
- `pydantic`
- `typer`

测试依赖：

- `pytest`

推荐安装方式：

```bash
python -m pip install -e .
```

如果你也要运行测试：

```bash
python -m pip install -e ".[test]"
```

## 快速开始

1. 复制环境变量模板：

   ```bash
   cp .env.example .env
   ```

   Windows PowerShell:

   ```powershell
   Copy-Item .env.example .env
   ```

2. 在 `.env` 中填写至少一个可用的 `OPENAI_API_KEY`
3. 安装依赖：`python -m pip install -e .`
4. 启动服务

网页模式：

```bash
python start_haotian.py --mode web --host 127.0.0.1 --port 8765
```

CLI 模式：

```bash
python start_haotian.py --mode cli
```

说明：

- `start_haotian.py` 会在缺少运行依赖时提示执行 `python -m pip install -e .`
- CLI 模式现在会在 Windows 上自动处理常见的非 UTF-8 控制台编码问题
- 如果配置了 `TelegramBotToken`，启动 Web 或 CLI 时会同时拉起 Telegram 轮询桥接

## 常用命令

安装运行依赖：

```bash
python -m pip install -e .
```

安装运行依赖和测试依赖：

```bash
python -m pip install -e ".[test]"
```

运行测试：

```bash
python -m pytest -q
```

执行日报主流程：

```bash
haotian run daily --date 2026-03-20
```

如果你没有安装 console script，也可以使用：

```bash
python -m haotian.main run daily --date 2026-03-20
```

## 配置说明

常用环境变量见 [`.env.example`](/E:/Haotian/.env.example)：

- `DATABASE_URL`：本地 SQLite 路径，默认示例为 `sqlite:///./data/haotian.db`
- `LLM_PROVIDER`：当前默认使用 `openai`
- `OPENAI_API_KEY`：OpenAI API Key
- `OPENAI_BASE_URL`：可选，自定义 OpenAI 兼容接口地址
- `OPENAI_MODEL`：可选，默认模型由代码配置决定
- `REPORT_DIR`：日报输出目录，推荐与代码默认值一致使用 `./data/reports`
- `TelegramBotToken`：可选，配置后自动启用 Telegram bridge

兼容旧变量名：

- `OPENAI_API_KEY`
- `OpenAIAPI`
- `OPENAIAPI`

其中标准变量 `OPENAI_API_KEY` 的优先级最高。

## 排障

如果启动时看到下面这类错误：

```text
Haotian 缺少运行依赖，当前无法启动。
缺失模块：pydantic
请先在项目根目录执行：python -m pip install -e .
```

请回到项目根目录，确认使用的是同一个 Python 解释器，然后重新执行：

```bash
python -m pip install -e .
```

如果需要跑测试但提示 `No module named pytest`，请执行：

```bash
python -m pip install -e ".[test]"
```

## 文档

- 操作说明见 [`docs/ops.md`](/E:/Haotian/docs/ops.md)
- 架构说明见 [`docs/architecture.md`](/E:/Haotian/docs/architecture.md)
- 能力 taxonomy 见 [`docs/capability-taxonomy.md`](/E:/Haotian/docs/capability-taxonomy.md)
