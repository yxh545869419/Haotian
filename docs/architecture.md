# Haotian 技术架构

## 目标

Haotian 的当前形态是一个 skill-first 仓库：

- 只在显式调用 skill 时运行
- Python 负责确定性流程
- Codex 负责 taxonomy 分类推理
- 最终产物稳定落盘为 Markdown / JSON

## 核心组件

### 1. Collectors

- `src/haotian/collectors/github_trending.py`
- `src/haotian/collectors/github_repository_metadata.py`

职责：

- 抓取 GitHub Trending
- 读取 README 与 topics
- 保持原始抓取与补充元数据的确定性输入

### 2. Persistence

- `src/haotian/db/schema.py`
- `src/haotian/services/ingest_service.py`
- `src/haotian/registry/capability_registry.py`

职责：

- 初始化本地 SQLite
- 写入 `trending_repos`
- 写入 `repo_capabilities`
- 维护 `capability_registry` 与 `capability_approvals`

### 3. Staged classification artifacts

- `src/haotian/services/classification_artifact_service.py`

职责：

- 写入 `classification-input.json`
- 校验 `classification-output.json`
- 写入 `run-summary.json`

### 4. Repository analysis snapshot

- `src/haotian/services/repository_workspace_service.py`
- `src/haotian/services/repository_probe_service.py`
- `src/haotian/services/repository_analysis_service.py`

职责：

- 把目标仓库克隆到 `TMP_REPO_DIR` 下的临时目录
- 只对代表性文件做 bounded probing，受 `MAX_REPO_PROBE_FILES`、`MAX_REPO_PROBE_FILE_BYTES` 和 `MAX_EVIDENCE_SNIPPETS` 约束
- 产出并持久化 `analysis_depth`、`matched_files`、`probe_summary`、`evidence_snippets` 和 `fallback_used`
- 分析结束后尝试删除临时 clone，通常会成功；失败时会保留临时工作区并通过清理状态暴露
- 当仓库预算用尽、根目录不可用或探测失败时，切换到 fallback analysis

### 5. Orchestration

- `src/haotian/services/orchestration_service.py`

职责：

- 第一阶段：收集数据并生成待分类工件
- 第二阶段前：执行仓库分析快照并把证据写入本地运行产物
- 第二阶段：读取 Codex 输出，写回数据库
- 调用 diff 与 report 服务生成最终结果

### 6. Reports

- `src/haotian/services/report_service.py`

职责：

- 生成 `data/reports/YYYY-MM-DD.md`
- 生成 `data/reports/YYYY-MM-DD.json`
- 把分析深度、命中文件和证据摘录渲染成 evidence-backed sections

### 7. Runner / Entrypoints

- `src/haotian/runner.py`
- `src/haotian/main.py`
- `start_haotian.py`
- `SKILL.md`

职责：

- 提供稳定的 skill-facing 入口
- 自动判断当前是“准备分类”还是“完成报告”
- 把阶段状态写回 `run-summary.json`

## 数据流

### 第一阶段：Prepare

1. 运行 `python start_haotian.py`
2. Python 抓取 Trending、补充元数据、写入本地 SQLite
3. Python 把目标仓库克隆到临时目录并执行 bounded probing
4. Python 生成 `data/runs/YYYY-MM-DD/classification-input.json`
5. Python 尝试删除临时 clone，通常会清理成功；如果失败，会保留临时工作区并返回 `awaiting_classification`

### 第二阶段：Classify

1. Codex 读取 `classification-input.json`
2. Codex 重点查看 `analysis_depth`、`matched_files`、`probe_summary` 和 `evidence_snippets`
3. Codex 读取 [`docs/capability-taxonomy.md`](capability-taxonomy.md)
4. Codex 写入 `classification-output.json`

### 第三阶段：Finalize

1. 再次运行 `python start_haotian.py`
2. Python 校验 `classification-output.json`
3. Python 写入 `repo_capabilities`
4. Python 更新 `capability_registry`
5. Python 生成带证据摘录的 Markdown / JSON 报告

## 目录与产物

```text
data/
├── app.db
├── reports/
│   ├── YYYY-MM-DD.md
│   └── YYYY-MM-DD.json
└── runs/
    └── YYYY-MM-DD/
        ├── classification-input.json
        ├── classification-output.json
        └── run-summary.json
```

## 设计约束

- 不再内置 Web UI、对话 CLI、Telegram bridge
- 不再从 Python 直接调用 OpenAI API
- 不再依赖 `OPENAI_API_KEY`
- capability id 必须来自本地 taxonomy，不允许运行时发明新 id

## 失败处理

- 如果第一阶段失败，`run-summary.json` 会记录 `stage_errors`
- 如果缺少 `classification-output.json`，流程会停在 `awaiting_classification`
- 如果 `classification-output.json` 非法，第二阶段会失败并给出校验错误

## 结论

Haotian 现在的边界非常清晰：Codex 负责推理分类，Python 负责可重复、可验证、可落盘的本地流程。这让仓库本身能够自然作为 skill 使用，而不是再叠加一层聊天产品壳。
