# Haotian 技术架构设计

## 目标

本次初始化聚焦于建立一个可扩展的 Python 3.11+ CLI 工程骨架，用于承载未来的 `run daily` 每日主流程。当前阶段重点是：

- 明确项目打包与命令入口。
- 将环境变量配置集中管理。
- 为后续数据库接入、LLM 调用与报告生成预留扩展点。
- 提供仓库内可维护的技术设计说明。

## 目录结构

```text
.
├── .env.example
├── docs/
│   └── architecture.md
├── pyproject.toml
└── src/
    └── haotian/
        ├── __init__.py
        ├── config.py
        ├── main.py
        └── cli/
            ├── __init__.py
            └── commands.py
```

## 架构分层

### 1. Packaging / Distribution

- 使用 `pyproject.toml` 作为统一项目配置入口。
- 基于 `setuptools` 进行打包，兼容常见 Python 工具链。
- 通过 `project.scripts` 暴露 `haotian` CLI 命令。

### 2. Configuration Layer

`src/haotian/config.py` 负责：

- 读取 `.env` 与系统环境变量。
- 对配置项进行结构化建模。
- 暴露缓存后的 `get_settings()`，避免重复解析环境变量。
- 在启动时确保报告输出目录存在。

当前规划的核心配置包括：

- `DATABASE_URL`：数据库连接地址。
- `LLM_PROVIDER`：大模型提供方标识。
- `OpenAIAPI`：在 Codex 管理页面中配置的 Secret，用于驱动 OpenAI 主导的 capability taxonomy 归一化。
- `REPORT_DIR`：报告输出目录。

### 3. CLI Layer

`src/haotian/cli/commands.py` 负责统一管理命令行命令：

- 顶层命令空间：`haotian`
- 子命令组：`run`
- 预留主流程命令：`haotian run daily`

当前 `run daily` 仅输出配置与占位信息，后续可以演进为：

1. 读取数据源。
2. 执行指标计算与数据聚合。
3. 调用 LLM 生成分析结论。
4. 输出 Markdown / HTML / JSON 报告。

### 4. Application Entrypoint

`src/haotian/main.py` 提供统一入口，职责保持极简：

- 导入 CLI app。
- 提供 `main()` 函数供脚本入口调用。
- 支持 `python -m haotian.main` 与安装后的 `haotian` 命令两种运行方式。

## 后续扩展建议

### 数据层

建议后续新增：

- `src/haotian/db/`：数据库连接、Repository、迁移管理。
- `src/haotian/models/`：领域对象与数据模型。

### LLM 集成层

建议后续新增：

- `src/haotian/llm/`：按 Provider 封装统一接口。
- Provider 适配器：`openai.py`、`azure.py`、`anthropic.py` 等。

### 报告生成层

建议后续新增：

- `src/haotian/reports/`：模板、导出器、文件命名规范。
- 支持多格式导出（Markdown、HTML、PDF、JSON）。

### 工作流编排层

建议后续新增：

- `src/haotian/workflows/`：将 `daily` 主流程拆分为独立步骤。
- 每一步保持单一职责，方便测试与重试。

## 配置与安全原则

- 敏感信息仅通过环境变量或密钥管理系统注入，不写入源码。
- `.env.example` 只保留占位示例，不包含真实密钥。
- CLI 默认输出应避免打印完整密钥内容。

## 测试建议

初始化完成后，建议优先补充：

1. `config.py` 的环境变量解析测试。
2. CLI 命令调用测试。
3. `run daily` 工作流的集成测试。

## 结论

当前工程已具备最小可运行骨架，可作为后续“数据库 + LLM + 报告生成”主流程的稳定起点。后续迭代应围绕模块解耦、配置统一、命令职责清晰三个方向逐步扩展。
