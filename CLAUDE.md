# CLAUDE.md

## Project Overview

NovaMind is a full-stack intelligent knowledge-base platform.

- `backend/`: FastAPI backend, domain services, parsing pipeline, retrieval, AI integrations
- `frontend/`: Vue 3 + TypeScript frontend, workspace UI, knowledge-base UI, agent UI
- `docs/`: architecture, design decisions, restructuring plans, handover notes
- `docker/`: container build and runtime assets
- `test_data/`: local fixtures for text, image, audio, and video processing

## Repository Layout

```text
backend/
frontend/
docs/
docker/
test_data/
deploy.ps1
deploy.sh
docker-compose.yml
```

## Core Development Principles

- Prefer clear module ownership over convenience imports.
- Keep business logic inside feature services, not route handlers.
- Put shared cross-feature capabilities into `backend/src/shared/`, but only when they are truly reusable.
- Keep knowledge-base parsing, media processing, and external parser integration grouped under `backend/src/shared/knowledge/`.
- Avoid creating duplicate utility layers. If a capability already has a canonical home, extend that home instead of adding a second implementation elsewhere.
- When changing API contracts, update backend schema, frontend types, and docs together.

## Backend Structure

Main backend areas:

- `backend/main.py`: backend entry point
- `backend/src/core/`: app factory, middleware, lifecycle, database, security, shared runtime infrastructure
- `backend/src/features/`: feature-oriented domain modules
- `backend/src/setting/`: configuration loading and YAML config assets
- `backend/src/shared/`: reusable shared capabilities

Feature modules should stay organized as:

- `api/`: FastAPI route layer only
- `services/`: business workflows and orchestration
- `repository/`: database access
- `models/`: ORM models
- `schemas/`: request/response and internal Pydantic models

## Knowledge-Base Canonical Homes

Knowledge-base related code should use these canonical locations:

- `backend/src/features/knowledge_space/`: knowledge-base domain behavior, tasks, APIs, schemas, repositories
- `backend/src/shared/knowledge/document_processing/`: text and document parsing pipeline
- `backend/src/shared/knowledge/media_processing/`: audio, video, OCR, VLM, and multimodal processing
- `backend/src/shared/knowledge/integrations/deepdoc/`: DeepDoc integration only

Generic helpers that are not knowledge-specific belong under:

- `backend/src/shared/utils/`

`shared/utils/` should only contain generic utilities such as time, crypto, redact, heartbeat, and truly generic text helpers. It should not become a second home for parser logic, media workflows, or vendor integrations.

## Frontend Structure

Main frontend areas:

- `frontend/src/api/`: API clients grouped by domain
- `frontend/src/components/`: reusable UI components grouped by domain
- `frontend/src/views/`: route-level pages
- `frontend/src/stores/`: Pinia stores
- `frontend/src/router/`: route registration
- `frontend/src/layouts/`: application shells
- `frontend/src/types/`: shared TS types

Knowledge-base UI should stay concentrated in:

- `frontend/src/api/knowledge/`
- `frontend/src/components/knowledge/`
- `frontend/src/views/space/`

## Coding Conventions

### Python

- Python 3.12+
- 4-space indentation
- `snake_case` for functions, modules, variables
- `PascalCase` for classes
- Keep async boundaries explicit
- Prefer absolute imports from `novamind...`
- Do not hide side effects inside utility functions

### TypeScript / Vue

- 2-space indentation
- `PascalCase` for Vue components and route views
- `camelCase` for stores, composables, and helpers
- Keep API types close to API modules
- Prefer explicit props and emitted event typing
- Keep page orchestration in views, reusable presentation in components

## Validation Workflow

### Backend

- Install: `cd backend && pip install .`
- Run dev server: `python main.py --config development --reload`
- Run tests: `pytest`
- Prefer targeted tests when touching parsing, document tasks, retrieval, or shared infra

### Frontend

- Install: `cd frontend && npm install`
- Run dev server: `npm run dev`
- Type check: `npm run type-check`
- Lint: `npm run lint`
- Format: `npm run format`
- Build: `npm run build`

## Change Rules

- Do not move files casually; preserve stable import boundaries unless there is a real structure fix.
- Do not add new top-level folders without a strong reason.
- When reorganizing folders, update docs and import paths in the same change.
- For parsing pipeline changes, verify both runtime code and sample fixtures in `test_data/`.
- For knowledge-base config changes, keep backend schema, frontend forms, and persisted config structure aligned.

## Important Documentation

- `docs/project-structure-navigation.md`
- `docs/knowledge-space/knowledge-architecture-navigation.md`
- `docs/knowledge-space/knowledge-config-structure-design.md`
- `docs/plans/repository-structure-cleanup-plan.md`
## 二、开发步骤

严格遵守以下流程，**不可跳步，不可省略任何环节**：

### 第一步：需求分析

- 收到用户需求后，**禁止直接写代码**
- 仔细分析需求的背景、目标和约束条件
- 如有不清楚的地方，主动向用户提问确认，不要猜测
- 确认需求的边界：哪些要做、哪些不做、优先级如何

### 第二步：制定开发计划

- 基于需求分析，编写详细的开发计划
- 计划内容必须包括：
  - **需求概述**：用简明的语言复述需求目标
  - **实现方案**：具体的技术方案和设计思路
  - **涉及文件**：列出需要新增或修改的文件清单
  - **开发步骤**：按顺序列出每一步要做什么，步骤要细化到具体的代码改动
  - **风险评估**：可能遇到的问题和应对方案（如有）
- 使用 Plan 模式编写计划，生成计划文档供用户审阅

### 第三步：提交审阅

- 计划完成后，提交给用户审阅
- **等待用户明确反馈**，不要催促，不要自行推进

### 第四步：修改计划（循环）

- 用户反馈"不对"或提出修改意见 → 根据意见修改计划 → 再次提交审阅
- 用户反馈"部分可以" → 保留认可的部分，修改有问题的部分 → 再次提交审阅
- **此步骤会循环多次，直到用户完全认可为止**
- 每次修改后都必须重新提交完整的计划文档，不要只发修改片段

### 第五步：用户确认后开始开发

- **只有当用户明确说"同意按照计划文档开发"或同等含义的确认话语后，才能开始写代码**
- 没有用户确认 = 不写一行代码
- 开发过程中严格按照计划执行，不擅自添加计划之外的功能
- 如开发中发现计划有问题，**停下来向用户说明情况**，等待用户指示

### 第六步：开发完成后的核对

- 开发完成后，**主动核对**实现是否满足原始需求
- 逐项检查计划中的每个步骤是否都已落实
- 如有遗漏或偏差，主动修复，不要等用户指出

---

## 三、验证流程和验证命令

### 环境启动

```bash
# 后端 (需要先配置 yaml，见下方规则)
cd backend
source .venv/bin/activate                             # Windows: .venv\Scripts\activate
python main.py                                        # http://localhost:8100

# 前端
cd frontend
npm install
npm run dev                                          # http://localhost:5173 (代理 /api → :8100)
```

### 后端验证

```bash
cd backend

# 单元测试
pytest tests/ -m unit

# 集成测试 — 对对应接口进行 HTTP 测试 (需要运行中的后端服务)
pytest tests/ -m integration
```

**接口测试：** 集成测试通过 `pytest tests/ -m integration` 对实际运行的 API 端点发送 HTTP 请求，验证响应状态码、返回结构和业务逻辑。每个测试文件对应一个模块：

| 测试文件 | 测试模块 | 验证的接口 |
|---------|---------|-----------|
| `tests/test_user_api.py` | 用户模块 | 登录、注册、CRUD、Token 刷新 |
| `tests/test_knowledge_space_api.py` | 知识空间 | 空间/知识库/文档 CRUD、上传、搜索 |
| `tests/test_qa_api.py` | 智能问答 | 消息 CRUD、会话管理 |
| `tests/test_ai_chat_db.py` | AI 对话 | 对话流程、附件处理 |
| `tests/test_deep_research_api.py` | 深度研究 | 研究 流程、历史查询 |
| `tests/test_evaluation_api.py` | 评估 | 测试集上传、评估任务、报告 |
| `tests/test_rag_pipeline.py` | RAG 管道 | 文档处理→切片→向量化→检索全链路 |

### 前端验证

```bash
cd frontend

# 类型检查 (无输出 = 通过)
npm run type-check

# Lint 检查 (无输出 = 通过)
npm run lint

# 格式检查
npm run format

# 单元测试
npm run test:unit

# 构建验证 (构建成功 = 通过)
npm run build-only
```

### Docker 部署验证

```bash
# 配置
cp docker/configs/docker.example docker/configs/docker.yaml  # 填入凭据

# 启动
docker compose up -d --build              # 全栈 :80
docker compose logs -f app                # 查看日志

# 验证
curl http://localhost/health              # 健康检查
curl http://localhost/                    # 前端页面

# 重建单个容器
docker compose up -d --build app

# 停止并清理
docker compose down -v
```

### 功能变更验证清单

**后端 API 变更后：**
1. 启动后端 `python main.py --config development --reload`
2. 确认启动无报错 (日志级别 INFO)
3. 调用 `GET /health/detailed` 确认所有依赖正常
4. 使用 Swagger 文档 `http://localhost:8100/docs` 手动测试新端点
5. 运行相关测试 `pytest tests/ -m integration`

**前端变更后：**
1. 启动前端 `npm run dev`
2. 浏览器访问对应页面路由
3. 检查浏览器控制台无错误
4. 验证功能正常路径 + 边界情况
5. 运行 `npm run type-check` 确认类型无误
6. 运行 `npm run build-only` 确认构建通过

**SSE 流式功能变更后：**
1. 前端确认 `AbortController` 取消功能正常
2. 后端确认 SSE 心跳 (`: heartbeat`) 正常发送
3. Nginx 确认无缓冲 (`X-Accel-Buffering: no`)
4. 长时间运行无断连

**数据库模型变更后：**
1. 确认 `BaseModel` 子类定义正确
2. 启动后端确认自动建表成功 (查看日志)
3. 验证 `to_dict()` 序列化正常
4. 检查 Repository 的查询是否适配新字段

---

## 四、规则

### 禁止事项

- **禁止未经确认直接写代码** — 必须先完成需求分析和计划
- **禁止跳步** — 开发流程的六个步骤不可省略
- **禁止擅自添加功能** — 严格按照确认后的计划执行
- **禁止提交敏感信息** — `.env`、`*.yaml` 配置文件、API Key、密码不得提交到 Git
- **禁止使用 `--no-verify` 跳过 Git 钩子** — 如钩子失败，先修复问题
- **禁止在生产配置中使用弱密码或通配符 CORS**
- **禁止硬编码凭据** — 所有配置走 YAML + 环境变量

### 后端编码规则

- **异常处理：** 所有业务异常继承 `BaseAPIError`，在模块 `startup.py` 注册，不要直接 `raise HTTPException`
- **数据库写入：** Repository 中写操作必须使用 `begin_nested()` (SAVEPOINT)，不要直接 commit
- **API Key 存储：** 使用 `encrypt_api_key_async` / `decrypt_api_key_async`，禁止明文存储
- **密码哈希：** 使用 `verify_password_async` / `get_password_hash_async`，禁止同步阻塞事件循环
- **Pydantic Schema：** 严格分层 `*Base → *Create/*Update → *Response`，Response 必须 `from_attributes=True`
- **路由注册：** 新路由必须在 `router_manager.py` 中手动注册，不会自动发现
- **模块初始化：** 新模块必须在 `startup_manager.py` 中注册 `register_feature_initializer`
- **配置文件：** 所有 `*.yaml` 已 gitignore，只提交 `*.example` 模板

### 前端编码规则

- **组件风格：** 统一使用 `<script setup lang="ts">` + Composition API
- **API 调用：** 使用 `request.get<T>()` 等类型安全方法，禁止裸 `axios` 调用
- **SSE 流式：** 使用 `createSSEStream()` + `AbortController`，不要用 Axios 处理 SSE
- **状态管理：** 使用 Pinia Store，不要在组件中直接管理跨组件状态
- **类型定义：** 所有 API 类型放在 `api/types.ts`，通过 `types/index.ts` 重导出
- **视图命名：** PascalCase + `View` 后缀，放在 `views/{domain}/` 目录下

### 安全规则

- **认证链路：** 所有需认证路由使用 `Depends(get_current_user)`，管理员路由加 `Depends(require_admin)`
- **Token 管理：** JWT 黑名单存 Redis，登出/禁用/删除用户时必须清理所有关联 Token
- **输入验证：** 所有用户输入通过 Pydantic Schema 验证，不要在路由层手动校验
- **文件上传：** 使用 `FileValidator` 校验类型和 Magic Number，不要只依赖扩展名
- **SQL 注入：** 使用 SQLAlchemy ORM 参数化查询，禁止拼接 SQL 字符串
