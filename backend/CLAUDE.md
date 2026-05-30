# CLAUDE.md — Backend

## 一、功能模块

NovaMind 后端采用 DDD 分层架构，每个功能模块位于 `src/features/{module}/`，统一遵循 `api → services → repository → models → schemas` 结构。

| 模块 | 路由前缀 | 功能 | 关键文件 |
|------|---------|------|---------|
| **user** | `/api/v1/user` | JWT 认证、Argon2 密码、角色管理、模型凭证 (AES-256 加密) | `user_routes.py`, `model_config_routes.py`, `auth_service.py` |
| **knowledge_space** | `/api/v1/spaces` | Space→KB→Document 三级层次、RBAC (VIEWER/EDITOR/ADMIN)、文档处理管道、9种搜索 (BM25/向量/混合)、Rerank、假设问题生成 | `space_router.py`, `document_routes.py`, `search_routes.py`, `search_service.py` |
| **qa** | `/api/v1/ai-chat`, `/api/v1/qa` | 多模型 SSE 流式对话、会话压缩 (summary/sliding_window/truncate)、多级缓存 (L1 LRU + L2 Redis)、文件附件 | `ai_chat_routes.py`, `ai_chat_service.py`, `qa_service.py` |
| **deep_research** | `/api/v1/spaces/{id}/deep-research` | 查询分析→任务分解→多源搜索 (Tavily/SerpAPI/DuckDuckGo)→报告综合 | `routes.py`, `deep_research_service.py` |
| **evaluation** | `/api/v1/spaces/{id}/knowledge-bases/{kb_id}/evaluation` | 测试集管理、异步批量评估 (检索+生成+端到端)、人工评分、JSON/CSV 导出 | `routes.py`, `evaluation_service.py`, `generation_evaluator.py` |
| **agent** | `/api/v1/agent` | ReAct 循环引擎、三层记忆 (短期+长期+工作)、MCP 协议外部工具、Docker 沙盒代码执行、工具注册中心 | `routes.py`, `core/engine.py`, `services/chat_service.py` |
| **skill** | `/api/v1/skills` | 技能上传/发布/安装、规则+LLM 双重安全审查、评分系统 | `routes.py`, `skill_marketplace_service.py`, `skill_checker.py` |
| **app** | `/api/v1/apps` | 简历挖掘 S1-S12 管道 (解析→分析→追问→评估) | `routes.py`, `resume_parser.py`, `resume_analyzer.py`, `resume_probing.py` |

> 每个模块的完整 API 端点清单见根目录 [项目结构导航.md](../项目结构导航.md)。

## 二、结构导航

### 目录结构

```
src/
├── core/                          # 核心基础设施
│   ├── middleware/
│   │   ├── app_factory.py         # create_app() 组装中间件、路由、限流
│   │   ├── router_manager.py      # 所有 Router 懒加载注册到 /api/v1
│   │   ├── startup_manager.py     # 生命周期: Redis→建表→模块初始化→arq Worker
│   │   ├── base_exception_handler.py  # BaseAPIError + 自动 HTTP 状态码映射
│   │   ├── trace_middleware.py     # ASGI 中间件, 每请求 trace_id
│   │   ├── rate_limit.py          # slowapi 限流 (登录5/min、注册3/min 等)
│   │   └── health_check.py        # /health 系列端点
│   ├── database/
│   │   ├── base.py                # BaseModel (id/created_at/updated_at)
│   │   └── database.py            # get_db() 异步会话管理
│   ├── auth/hashing.py            # Argon2 密码哈希
│   └── security/config_validator.py  # 生产环境安全检查
│
├── features/{module}/             # 8 个业务模块 (DDD 分层)
│   ├── api/
│   │   ├── routes.py              # FastAPI 路由端点
│   │   ├── dependencies.py        # Depends() 服务工厂注入
│   │   ├── exceptions.py          # 异常类 (继承 BaseAPIError)
│   │   ├── exception_handlers.py  # (可选) 自定义异常处理器
│   │   └── startup.py             # 模块初始化 + 异常注册
│   ├── models/                    # SQLAlchemy ORM (继承 BaseModel)
│   ├── schemas/                   # Pydantic v2 (*Base → *Create/*Update → *Response)
│   ├── services/                  # 业务逻辑
│   └── repository/                # 数据访问 (SQLAlchemy async)
│
├── setting/yaml_config/
│   ├── config.py                  # 27 个 dataclass: AppConfig 聚合所有子配置
│   └── loader.py                  # YAML 多层叠加 + ${ENV_VAR} 替换 + get_config() 单例
│
└── shared/
    ├── ai_models/                 # BaseLLM / BaseEmbedding / BaseRerank 抽象
    │   ├── llm/                   # OpenAI / Anthropic / Ollama / Transformers
    │   ├── embedding/             # OpenAI / Ollama / Transformers
    │   └── rerank/                # OpenAI / Transformers
    ├── cache/                     # Redis + LRU + 装饰器
    ├── storage/                   # Elasticsearch (9种搜索+RRF) + MinIO
    ├── mq/                        # arq Worker 文档处理 + 任务追踪
    ├── prompts/templates.py       # PromptTemplate 枚举 45+ 模板
    └── utils/
        ├── document_readers/      # 5 种 Reader + 4 种 Splitter
        ├── text_processing/       # 文本压缩 + Token 计数
        ├── crypto.py              # AES-256-CBC API Key 加密
        ├── file_validator.py      # Magic Number + MIME + 危险扩展名
        ├── heartbeat.py           # SSE 心跳保活
        └── time_utils.py          # 中国时区 now_china()
```

### 数据流

```
Route → Depends(service_factory) → Service → Repository → DB (get_db())
                                                         → ES (搜索)
                                                         → MinIO (文件)
                                                         → Redis (缓存)
                                                         → LLM (AI调用)
```

### 关键约定

- **路由注册:** 新路由必须在 `router_manager.py` 手动注册
- **模块初始化:** 新模块必须在 `startup_manager.py` 注册 `register_feature_initializer`
- **异常处理:** 所有业务异常继承 `BaseAPIError`，在 `startup.py` 注册
- **数据库写入:** Repository 写操作用 `begin_nested()` (SAVEPOINT)
- **配置文件:** `*.yaml` 已 gitignore，只提交 `*.example`

## 三、测试步骤

### 环境准备

```bash
cd backend
source .venv/bin/activate                # Windows: .venv\Scripts\activate
```

### 单元测试

```bash
pytest tests/ -m unit
```

### 集成测试（接口测试）

集成测试对实际运行的 API 端点发送 HTTP 请求，验证状态码、返回结构和业务逻辑。**需要先启动后端服务** (`python main.py`)。

```bash
pytest tests/ -m integration
```

| 测试文件 | 测试模块 | 验证内容 |
|---------|---------|---------|
| `tests/test_user_api.py` | user | 登录、注册、CRUD、Token 刷新、状态切换 |
| `tests/test_knowledge_space_api.py` | knowledge_space | 空间/知识库/文档 CRUD、上传、搜索 |
| `tests/test_qa_api.py` | qa | 消息 CRUD、会话管理 |
| `tests/test_ai_chat_db.py` | qa (AI 对话) | 对话流程、附件处理 |
| `tests/test_deep_research_api.py` | deep_research | 研究流程、历史查询 |
| `tests/test_evaluation_api.py` | evaluation | 测试集上传、评估任务、报告 |
| `tests/test_rag_pipeline.py` | knowledge_space (RAG) | 文档处理→切片→向量化→检索全链路 |

### 开发中的快速验证

```bash
# 启动后端
python main.py

# 健康检查 (确认所有依赖正常)
curl http://localhost:8100/health/detailed

# Swagger 文档 (手动测试接口)
# 浏览器打开 http://localhost:8100/docs
```

### 新增功能的测试检查项

1. 新路由已注册到 `router_manager.py`
2. 新异常已在 `startup.py` 注册
3. `pytest tests/ -m integration` 通过
4. Swagger 文档中接口可正常调用
5. 响应格式符合 `{"error": {"code": "...", "message": "..."}, "timestamp": "...", "request_id": "..."}`
