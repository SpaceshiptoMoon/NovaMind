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

## 规则

### 禁止事项

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
