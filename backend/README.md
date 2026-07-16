# NovaMind 后端

NovaMind 后端是一个基于 FastAPI 的应用，负责整个平台的认证、知识空间、知识库、文档处理、RAG 问答、深度研究、Agent、技能广场、通知中心、应用中心和浏览器终端等能力。

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
- `ClawMate`：浏览器终端会话和 AI 辅助工作区接口

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
|  |- features/                  # 领域模块
|  |  |- agent/
|  |  |- app/
|  |  |- clawmate/
|  |  |- deep_research/
|  |  |- knowledge_space/
|  |  |- notification/
|  |  |- qa/
|  |  |- skill/
|  |  `- user/
|  |- setting/                   # YAML 配置加载与环境覆盖
|  `- shared/                    # 共享基础设施与知识处理运行时
`- tests/
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

共享运行时实现位于：

- `src/shared/knowledge/document_processing/`
- `src/shared/knowledge/media_processing/`
- `src/shared/knowledge/integrations/deepdoc/`

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
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install .
```

### 准备配置

配置文件位于 `src/setting/yaml_config/yaml/`。

本地开发常用准备方式：

```bash
cd backend/src/setting/yaml_config/yaml
cp default.example default.yaml
cp development.example development.yaml
```

主要配置层：

- `default.yaml`：共享基线配置
- `development.yaml`：开发环境覆盖
- `testing.yaml`：测试配置
- `production.yaml`：生产环境覆盖

加载器支持深度合并和 `${VAR_NAME}` 环境变量展开。

### 启动

```bash
cd backend
python main.py --config development --reload
```

常见变体：

```bash
python main.py --reload
python main.py --config development
python main.py --config production --workers 4
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

测试文件放在 `backend/tests/`，命名建议例如：

- `test_knowledge_space_api.py`
- `test_document_task_retry_count.py`
- `test_knowledge_config_runtime.py`

## API 范围

后端对外暴露的主要接口包括：

- `/api/v1/user`
- `/api/v1/spaces`
- `/api/v1/qa`
- `/api/v1/ai-chat`
- `/api/v1/agent`
- `/api/v1/apps`
- `/api/v1/notifications`
- `/api/v1/clawmate`

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
