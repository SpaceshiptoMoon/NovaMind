# NovaMind 后端

NovaMind 后端是一个基于 FastAPI 的应用，负责整个平台的认证、知识空间、知识库、文档处理、RAG 问答、深度研究、Agent、技能广场、通知中心和应用中心等能力。

后端代码按领域组织，而不是只按接口层拆分。业务模块位于 `src/features/`，共享基础设施和知识处理运行时位于 `src/core/`、`src/setting/` 和 `src/shared/`。

## 后端负责什么

- `用户与认证`：登录、刷新令牌、密码流程、用户管理、模型配置
- `知识空间`：空间、成员、权限、可见性、空间级默认配置
- `知识库`：KB 配置、文档上传、解析、切分、索引、检索、评测
- `RAG 与聊天`：会话管理、检索增强回答、流式聊天
- `深度研究`：多源研究流程和报告生成
- `Agent 平台`：Agent、MCP Server、工具编排、安全执行
- `技能广场`：技能上传、审核、安装和元数据管理
- `应用与通知`：场景应用、站内通知、偏好设置

## 技术栈

| 类别 | 技术 |
| --- | --- |
| Web 框架 | FastAPI |
| 语言 | Python 3.12+ |
| ORM / 校验 | SQLAlchemy, Pydantic |
| 数据库 | MySQL 8.4+ |
| 缓存 / 异步任务 | Redis 7, ARQ |
| 检索 | Elasticsearch 9.3+ |
| 对象存储 | MinIO |
| 认证 | JWT |
| 打包 | 基于 `pyproject.toml` 的 Python 包 |

## 目录结构

```text
backend/
|- main.py
|- pyproject.toml
|- src/
|  |- core/                      # 应用工厂、中间件、数据库、安全
|  |- engines/                   # 引擎层：纯逻辑组件，零 feature/setting/core 依赖
|  |  |- agent/                  # Agent 引擎（ReAct 循环、工具、记忆、MCP）
|  |  |- deep_research/          # 深度研究引擎
|  |  |- document/               # 文档处理引擎（pipeline/splitters/converters/media/deepdoc）
|  |  |- eval/                   # 评测引擎（检索/生成/embedding/claim 评估器）
|  |  |- rag/                    # RAG 引擎（检索引擎、Grade→Retry）
|  |  `- resume/                 # 简历解析引擎
|  |- features/                  # 领域模块
|  |  |- agent/
|  |  |- app/
|  |  |- deep_research/
|  |  |- evaluation/
|  |  |- knowledge_space/
|  |  |- notification/
|  |  |- qa/
|  |  |- skill/
|  |  `- user/
|  |- setting/                   # YAML 配置加载（单 default.yaml：凭据走 .env、连接参数带本地基线）
|  `- shared/                    # 共享基础设施（storage/ai_models/cache/mq/prompts/document）
`- tests/                        # 测试按被测对象分层（见 tests/README.md）
```

典型模块布局：

```text
src/features/{module}/
|- api/
|- services/
|- repository/
|- models/
`- schemas/
```

## 知识处理代码布局

知识相关业务编排位于：

- `src/features/knowledge_space/`

文档处理引擎实现位于：

- `src/engines/document/pipeline/`（DocumentLoader / DocumentProcessor / DocumentRegistry）
- `src/engines/document/splitters/`（recursive / semantic / fixed / markdown）
- `src/engines/document/converters/`
- `src/engines/document/media/`（audio / video / vlm / OCR）
- `src/engines/document/integrations/deepdoc/`（vendored，自包含）

跨 feature 复用的读取与校验位于：

- `src/shared/document/readers/`（PDF / DOCX / TXT / HTML / MD）
- `src/shared/document/validation/`

相关文档入口：

- [`../docs/knowledge-space/README.md`](../docs/knowledge-space/README.md)
- [`../docs/knowledge-space/current/README.md`](../docs/knowledge-space/current/README.md)
- [`../docs/knowledge-space/current/knowledge-architecture-navigation.md`](../docs/knowledge-space/current/knowledge-architecture-navigation.md)
- [`../docs/deepdoc/deepdoc-integration.md`](../docs/deepdoc/deepdoc-integration.md)

## 本地开发

### 环境要求

- Python 3.12+
- MySQL 8.4+ 或兼容版本
- Redis 7+
- Elasticsearch 9.3+
- MinIO

如果你希望更快完成全栈启动，而不是手动只跑后端，优先使用仓库根目录的部署脚本，见 [`../README.md`](../README.md)。

### 安装

```bash
cd backend

# 项目统一用 uv（不用 pip/poetry）；uv.lock 已入库，安装可复现。
# core 依赖即覆盖全部运行时（含 DeepDoc full 模式）；test/dev 为开发测试 extras。
uv sync --extra test --extra dev

# 后续命令
uv run python main.py --reload
uv run pytest
```

### 准备配置

配置文件只有一个：`src/setting/yaml_config/yaml/default.yaml`。

本地开发常用准备方式：

```bash
cd backend/src/setting/yaml_config/yaml
cp default.example default.yaml
```

两层配置模型：

- `default.yaml`：唯一后端配置文件——结构与占位符引用。凭据类（`${SECRET_KEY}` 等）无默认值，缺失解析为 `None` 显性报错；连接参数（`${DB_HOST:127.0.0.1}` 等）占位符内带本地基线，本地开发零配置
- 仓库根 `.env`：只存账户密码/凭据；loader 启动自动加载，进程环境变量优先。Docker 的连接值（容器名/生产桶名/ES 免认证）由 docker-compose.yml 的 `app.environment` 块注入（优先级高于 env_file）

历史上的 `development.yaml` / `production.yaml` / `local.yaml` 覆盖层与环境名概念（`--config` 参数 / `ENVIRONMENT` 变量 / `config.environment` 门控）已于 2026-10 全部移除——单一配置文件 + 环境变量占位符，无任何环境分支。

单一模式的防护分工：`/docs` 永远开放，但公网部署由 nginx 不反代 `/docs` 挡在入口层；HTTP 响应永远不含内部错误详情（全量在日志）；启动期安全诊断（弱密钥/占位符/通配 CORS）只告警不阻断。可选调优旋钮（`CORS_ORIGINS` / `MINIO_SECURE`）见 `.env.example`。

### 启动

```bash
cd backend
python main.py --reload
```

常见变体：

```bash
python main.py
python main.py --workers 4
```

默认本地地址：

- Swagger UI：`http://localhost:8100/docs`
- ReDoc：`http://localhost:8100/redoc`
- 健康检查：`http://localhost:8100/health`

## 测试

后端测试使用 `pytest`。

```bash
cd backend
pytest
pytest -m unit
pytest -m "not slow"
```

测试文件放在 `backend/tests/`，按**被测对象所在分层**分子目录摆放（`architecture/` 全局门禁与契约、`core/`、`shared/`、`engines/<x>/`、`features/<x>/`、`integration/` 需运行服务），详见 [`tests/README.md`](tests/README.md)。

## API 范围

后端对外暴露的主要接口包括：

- `/api/v1/user` — 认证、用户管理、RBAC 角色、模型配置、搜索配置、应用门禁
- `/api/v1/spaces` — 空间、成员、知识库、文档、任务、检索、深度研究、评测
- `/api/v1/qa` — 基于知识库的问答
- `/api/v1/ai-chat` — 流式对话和附件交互
- `/api/v1/agent` — Agent、MCP Server、工具
- `/api/v1/skills` — 技能广场
- `/api/v1/apps` — 应用中心（简历挖掘）
- `/api/v1/notifications` — 站内通知和偏好设置

查看实时接口详情，请启动服务后访问：

- `http://localhost:8100/docs`

## 安全说明

- 不要提交真实 `.env` 密钥。
- `src/setting/yaml_config/yaml/` 下的示例配置应视为模板，不应保存生产密钥。
- 日志、上传产物和临时文件如需入库，必须先确认已脱敏或属于刻意保留的测试样例。

仓库级安全策略和漏洞披露方式见 [`../SECURITY.md`](../SECURITY.md)。

## 相关文档

- 项目总览：[`../README.md`](../README.md)
- 前端说明：[`../frontend/README.md`](../frontend/README.md)
- 文档总入口：[`../docs/README.md`](../docs/README.md)
- 贡献指南：[`../CONTRIBUTING.md`](../CONTRIBUTING.md)

## 许可证

See the repository root [LICENSE](../LICENSE).
