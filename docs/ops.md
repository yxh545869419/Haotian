# Ops Guide

## 如何运行每日主流程

1. 执行 `haotian run daily --date 2026-03-20` 触发统一主流程入口。
2. MVP 默认使用 SQLite 本地文件 `data/app.db`，并在同一轮中依次执行 ingest、enrich、analyze、diff、report。
3. 命令结束时会输出健康检查摘要，包括本次抓取 repo 数、识别能力数、告警候选数和报告路径。
4. 默认输出目录是 `data/reports/`，文件名格式为 `YYYY-MM-DD.md`。
5. 可直接使用 `cat data/reports/2026-03-20.md`、编辑器或任意 Markdown 阅读器查看内容。

## Cron 示例

每天 UTC 02:00 执行一次：

```cron
0 2 * * * cd /workspace/Haotian && /root/.pyenv/shims/haotian run daily >> data/logs/daily_pipeline.log 2>&1
```

如果希望补跑指定日期，可改为：

```bash
haotian run daily --date 2026-03-20
```

## 如何执行审批命令

1. 使用 `haotian approval apply --capability browser_automation --action poc` 对能力项发起审批。
2. 可选参数包括：
   - `--reviewer <name>`：记录审批人。
   - `--note <text>`：记录审批原因或备注。
   - `--snapshot-date YYYY-MM-DD`：关联某次日报/快照日期。
3. 支持的审批动作有 `ignore`、`watchlist`、`poc`、`activate`、`reject`。
4. 每次审批都会写入 `capability_approvals` 审计表，并同步更新 `capability_registry` 中对应能力项的状态。
