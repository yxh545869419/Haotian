# Ops Guide

## 如何查看日报

1. 执行 `haotian run daily --date 2026-03-20` 生成指定日期的日报。
2. 默认输出目录是 `data/reports/`，文件名格式为 `YYYY-MM-DD.md`。
3. 可直接使用 `cat data/reports/2026-03-20.md`、编辑器或任意 Markdown 阅读器查看内容。

## 如何执行审批命令

1. 使用 `haotian approval apply --capability browser_automation --action poc` 对能力项发起审批。
2. 可选参数包括：
   - `--reviewer <name>`：记录审批人。
   - `--note <text>`：记录审批原因或备注。
   - `--snapshot-date YYYY-MM-DD`：关联某次日报/快照日期。
3. 支持的审批动作有 `ignore`、`watchlist`、`poc`、`activate`、`reject`。
4. 每次审批都会写入 `capability_approvals` 审计表，并同步更新 `capability_registry` 中对应能力项的状态。
