# Ops Guide

## 如何运行每日主流程

1. 执行 `haotian run daily --date 2026-03-20` 触发统一主流程入口。
2. MVP 默认使用 SQLite 本地文件 `data/app.db`，并在同一轮中抓取 GitHub Trending 的 `daily` / `weekly` / `monthly` 三个周期，再依次执行 ingest、enrich、analyze、diff、report。
3. 若已配置 `OPENAI_API_KEY`，分析阶段会优先接入 OpenAI Codex / OpenAI Responses API 直接完成 taxonomy 归一化；未配置或调用失败时会自动回退到本地规则归一化。
4. diff 阶段不会再等待人工审批，而是基于能力分数自动写入 `watchlist` / `poc` / `active` / `deprecated` 状态，并记录自动配置审计日志。
5. 生成报告时会把仍需人工介入的项目显式放到 `Manual Attention` 区块。
6. 命令结束时会输出健康检查摘要，包括本次抓取唯一 repo 数、识别能力数、告警候选数和报告路径。
7. 默认输出目录是 `data/reports/`，文件名格式为 `YYYY-MM-DD.md`。
8. 可直接使用 `cat data/reports/2026-03-20.md`、编辑器或任意 Markdown 阅读器查看内容。

## 一键启动脚本

仓库根目录提供了一个跨平台的一键启动脚本：`start_haotian.py`。

如果你在 Windows 本地直接执行脚本时看到下面这种报错：

```text
ModuleNotFoundError: No module named 'dotenv'
```

说明当前 Python 环境缺少 `python-dotenv` 依赖。先进入项目根目录，再执行：

```bash
python -m pip install -e .
```

如果你暂时只想补齐这个依赖，也可以执行：

```bash
python -m pip install python-dotenv
```

项目现在即使没有安装 `python-dotenv` 也能启动；只是不会自动读取根目录 `.env` 文件，此时你需要手动在当前终端先设置环境变量。

### 网页版

```bash
python start_haotian.py --mode web --host 127.0.0.1 --port 8765
```

### 命令行版

```bash
python start_haotian.py --mode cli
```

Telegram 不再作为单独启动模式存在。只要启动网页版或命令行版，并且已配置 `TelegramBotToken`，系统就会自动在后台同时连上 Telegram Bot；回答仍然复用 `OPENAI_API_KEY`。

## 本地网页对话部署（Windows / Linux / Ubuntu）

Haotian 现在支持在本机启动一个轻量网页对话页面，默认监听一个相对不常用的端口 `8765`。

### 1. 准备 OpenAI API Key

本地环境统一使用 `OPENAI_API_KEY`；为了兼容旧配置，项目仍可读取 `OpenAIAPI` / `OPENAIAPI`。

#### 方式 A：使用 `.env` 文件（推荐）

1. 在项目根目录复制模板：

   ```bash
   copy .env.example .env
   ```

   如果你使用的是 PowerShell，也可以执行：

   ```powershell
   Copy-Item .env.example .env
   ```

2. 编辑 `.env`，填入你自己的 Key：

   ```env
   OPENAI_API_KEY=sk-xxxxx
   ```

3. 确认 `.gitignore` 已经忽略 `.env`，不要执行 `git add .env`。

#### 方式 B：只在当前终端设置，不落盘

`cmd.exe`：

```cmd
set OPENAI_API_KEY=sk-xxxxx
python start_haotian.py --mode web
```

PowerShell：

```powershell
$env:OPENAI_API_KEY="sk-xxxxx"
python start_haotian.py --mode web
```

这种方式不会把密钥写进仓库文件，更不需要上传到 GitHub。

#### 方式 C：设置为当前用户的 Windows 持久环境变量

PowerShell：

```powershell
[System.Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-xxxxx", "User")
```

设置完成后，重新打开一个新的终端窗口再启动 Haotian。

### 2. 如何避免把 API Key 上传到 GitHub

1. 把密钥放在 `.env` 或系统环境变量里，不要写进 `.py`、`.md`、`.json` 等会提交的文件。
2. 本仓库的 `.gitignore` 已经忽略 `.env`，所以正常情况下 `.env` 不会被提交。
3. 提交前可执行 `git status`，确认没有出现 `.env`。
4. 如果你误提交过密钥，需要立刻删除并轮换这个 Key。

### 3. 启动网页服务

跨平台推荐命令如下：

```bash
PYTHONPATH=src python -m haotian.main serve web --host 127.0.0.1 --port 8765
```

如果已经通过 `pip install -e .` 安装了 CLI，也可以直接执行：

```bash
haotian serve web --host 127.0.0.1 --port 8765
```

### 4. 浏览器访问

启动后，在浏览器打开：

```text
http://127.0.0.1:8765
```

### 5. 按需修改端口

如果 `8765` 被占用，可自行改成其他端口，例如：

```bash
PYTHONPATH=src python -m haotian.main serve web --host 127.0.0.1 --port 9631
```

Windows、Linux、Ubuntu 本地部署时都可使用同一套参数；区别只在于你如何启动 Python 或已安装的 CLI。

网页版启动后，左侧会显示 `对话 / 技能 / 配置` 三个页面；右侧对话区支持显示全部履历、一键删除、输入问题以及上传文件/图片等附件。

## Cron 示例

默认建议每天 **中国时间（Asia/Shanghai）10:00** 执行一次。对应的 UTC 时间是 **02:00**。

```cron
0 2 * * * cd /workspace/Haotian && /root/.pyenv/shims/haotian run daily >> data/logs/daily_pipeline.log 2>&1
```

如果你的服务器已经设置为中国时区，也可以直接写成：

```cron
0 10 * * * cd /workspace/Haotian && /root/.pyenv/shims/haotian run daily >> data/logs/daily_pipeline.log 2>&1
```

如果后续需要调整执行时间，只需要修改 cron 表达式中的分钟和小时字段即可。

如果希望补跑指定日期，可改为：

```bash
haotian run daily --date 2026-03-20
```

## 如何执行审批命令（可选人工覆盖）

1. 使用 `haotian approval apply --capability browser_automation --action poc` 对能力项发起审批。
2. 可选参数包括：
   - `--reviewer <name>`：记录审批人。
   - `--note <text>`：记录审批原因或备注。
   - `--snapshot-date YYYY-MM-DD`：关联某次日报/快照日期。
3. 支持的审批动作有 `ignore`、`watchlist`、`poc`、`activate`、`reject`。
4. 每次审批都会写入 `capability_approvals` 审计表，并同步更新 `capability_registry` 中对应能力项的状态。
