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

### 4. Orchestration

- `src/haotian/services/orchestration_service.py`

职责：

- 第一阶段：收集数据并生成待分类工件
- 第二阶段：读取 Codex 输出，写回数据库
- 调用 diff 与 report 服务生成最终结果

### 5. Reports

- `src/haotian/services/report_service.py`

职责：

- 生成 `data/reports/YYYY-MM-DD.md`
- 生成 `data/reports/YYYY-MM-DD.json`

### 6. Runner / Entrypoints

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
3. Python 生成 `data/runs/YYYY-MM-DD/classification-input.json`
4. 返回 `awaiting_classification`

### 第二阶段：Classify

1. Codex 读取 `classification-input.json`
2. Codex 读取 [`docs/capability-taxonomy.md`](capability-taxonomy.md)
3. Codex 写入 `classification-output.json`

### 第三阶段：Finalize

1. 再次运行 `python start_haotian.py`
2. Python 校验 `classification-output.json`
3. Python 写入 `repo_capabilities`
4. Python 更新 `capability_registry`
5. Python 生成 Markdown / JSON 报告

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
