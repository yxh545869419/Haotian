# Ops Guide

## 如何运行每日主流程

1. 执行 `haotian run daily --date 2026-03-20` 触发统一主流程入口。
2. MVP 默认使用 SQLite 本地文件 `data/app.db`，并在同一轮中抓取 GitHub Trending 的 `daily` / `weekly` / `monthly` 三个周期，再依次执行 ingest、enrich、analyze、diff、report。
3. 若已在 Codex 管理页面配置 Secret `OpenAIAPI`，分析阶段会优先接入 OpenAI Codex / OpenAI Responses API 直接完成 taxonomy 归一化；未配置或调用失败时会自动回退到本地规则归一化。
4. diff 阶段不会再等待人工审批，而是基于能力分数自动写入 `watchlist` / `poc` / `active` / `deprecated` 状态，并记录自动配置审计日志。
5. 生成报告时会把仍需人工介入的项目显式放到 `Manual Attention` 区块。
6. 命令结束时会输出健康检查摘要，包括本次抓取唯一 repo 数、识别能力数、告警候选数和报告路径。
7. 默认输出目录是 `data/reports/`，文件名格式为 `YYYY-MM-DD.md`。
8. 可直接使用 `cat data/reports/2026-03-20.md`、编辑器或任意 Markdown 阅读器查看内容。

## 一键启动脚本

仓库根目录提供了一个跨平台的一键启动脚本：`start_haotian.py`。

### 网页版

```bash
python start_haotian.py --mode web --host 127.0.0.1 --port 8765
```

### 命令行版

```bash
python start_haotian.py --mode cli
```

Telegram 不再作为单独启动模式存在。只要启动网页版或命令行版，并且已配置 Secret `TelegramBotToken`，系统就会自动在后台同时连上 Telegram Bot；回答仍然复用 `OpenAIAPI`。

## 本地网页对话部署（Windows / Linux / Ubuntu）

Haotian 现在支持在本机启动一个轻量网页对话页面，默认监听一个相对不常用的端口 `8765`。

### 1. 准备 OpenAIAPI Secret

在 Codex 管理页面中配置 Secret `OpenAIAPI`，网页对话会直接使用它调用 OpenAI 模型进行思考和回答。

### 2. 启动网页服务

跨平台推荐命令如下：

```bash
PYTHONPATH=src python -m haotian.main serve web --host 127.0.0.1 --port 8765
```

如果已经通过 `pip install -e .` 安装了 CLI，也可以直接执行：

```bash
haotian serve web --host 127.0.0.1 --port 8765
```

### 3. 浏览器访问

启动后，在浏览器打开：

```text
http://127.0.0.1:8765
```

### 4. 按需修改端口

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
