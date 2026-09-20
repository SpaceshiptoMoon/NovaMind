# CLAUDE.md - Backend

## Overview

The backend is a FastAPI application using a feature-oriented, DDD-leaning structure.

Entry points:

- `main.py`
- `src/core/middleware/app_factory.py`
- `src/core/middleware/router_manager.py`
- `src/core/middleware/startup_manager.py`

## Parallel Multi-Agent Development

When multiple agent windows work on this repo concurrently, each must run in its own git worktree on its own branch — never in a shared working directory. See the root `CLAUDE.md` and `docs/multi-agent-parallel-development-workflow.md` for the full workflow.

Backend-specific notes:

- Branch by feature boundary (`src/features/<domain>/`); one agent owns one feature.
- Single-point shared files — `src/shared/prompts/`, `src/core/middleware/router_manager.py`, `src/core/middleware/startup_manager.py`, `*.example` configs, DB models — are edited by only one agent at a time.
- Run `pytest` (or targeted tests) in the worktree before merging back to the trunk.

## Directory Structure

- `src/core/`: framework/runtime layer
- `src/features/`: feature modules
- `src/setting/`: config system and YAML assets
- `src/shared/`: reusable shared capabilities
- `tests/`: backend tests

## Feature Module Contract

Each feature should follow this structure where applicable:

- `api/`: HTTP layer only
- `services/`: business logic and orchestration
- `repository/`: persistence access
- `models/`: SQLAlchemy models
- `schemas/`: Pydantic schemas

Rules:

- Keep request validation in `schemas/`
- Keep route handlers thin
- Keep transaction-sensitive logic in services
- Keep persistence queries in repository classes, not scattered through services

## Core Layer Rules

`src/core/` is for application runtime concerns only:

- middleware
- auth and security
- app startup/shutdown
- db session management
- cross-cutting infrastructure

Do not place feature business logic in `core/`.

## Shared Layer Rules

`src/shared/` is for reusable capabilities across features, not a dumping ground.

Allowed categories:

- `shared/storage/`: external service clients (ES/MinIO/Redis, via `client_factory/`)
- `shared/search/`: external search vendor clients (tavily/serpapi/duckduckgo)
- `shared/cache/`: cache access
- `shared/mq/`: async task runtime
- `shared/prompts/`: shared prompts
- `shared/utils/`: truly generic helpers
- `shared/document/`: cross-feature document readers & validation (truly reusable across features)

If code is only used by one feature and expresses domain behavior, keep it in that feature instead of moving it into `shared/`.

## Knowledge-Base Architecture

Canonical homes:

- `src/features/knowledge_space/`: domain layer for documents, KB config, tasks, chunk lifecycle, APIs (business logic; parsing/chunking/multimodal engines live in `engines/document/`)
- `src/engines/document/pipeline/`: document parsing pipeline (DocumentLoader/DocumentProcessor/DocumentRegistry) — reusable engines-layer component
- `src/engines/document/splitters/`: chunk splitters (recursive/semantic/fixed/markdown)
- `src/engines/document/converters/`: document format converters
- `src/engines/document/media/`: audio/video/image multimodal processing (VLM/OCR/audio/video)
- `src/engines/document/integrations/deepdoc/`: DeepDoc-specific implementation (vendored, self-contained)
- `src/shared/document/readers/`: cross-feature document readers (PDF/DOCX/TXT/HTML/MD) — reused by app/qa/knowledge_space
- `src/shared/document/validation/`: cross-feature file validation (FileInfo/FileValidator) — reused by qa/knowledge_space

Do not duplicate parsing logic under both `shared/document/` and `engines/document/`. Document-processing engines (pipeline/splitters/converters/media/deepdoc) live in `engines/document/` as reusable components any feature may import (`features → engines` allowed); `features/knowledge_space/` retains only business logic and orchestrates them via ports. Only truly cross-feature readers & validation stay in `shared/document/`.

## Import Rules

- Prefer absolute imports from `novamind...`
- Avoid relative imports in cross-module shared code
- Keep `__init__.py` exports minimal and intentional
- Do not rely on path hacks when normal package imports can solve it

## Coding Rules

- Python 3.12+
- 4-space indentation
- Add type hints for service boundaries and shared-layer code
- Keep async code async end-to-end where reasonable
- Raise domain-meaningful errors instead of generic `Exception`
- Log enough context for task failures, especially in parsing and MQ workflows

## import 依赖规则（硬规则，ragflow 务实单体风格）

R1–R6（详版见 `docs/plans/active/REFACTOR-ragflow-style-migration.md` §1）：

- **R1 import 无环**：`features`/`engines`/`shared`/`setting`/`core` 之间允许任意方向 import（含 engines→features、core→features），但整个 `src/` 模块级 import 图（含函数内懒 import）必须无环。机器门禁：`tests/architecture/test_import_acyclic_gate.py`（AST 全图收集 + Tarjan SCC）。
- **R2 跨 feature 走公共面**：允许 import 对方 `services/` 公共类、`schemas/`、`models/` 中显式导出的枚举与行级只读访问；不 import 对方 `repository/` 内部、不下划线私有成员（机器门禁：`tests/architecture/test_no_cross_module_private_imports.py`）。**防环细则**：需要对方数据但对方 service 已依赖自己时，import 对方 `models/` 直查，不 import 对方 `services/`（典型：user ↔ knowledge_space）。
- **R3 全局中心清单**（只进不改，热点文件串行编辑）：`setting/` 的 `get_config()`、`shared/prompts/prompt_manager.py` 的 PromptManager、`shared/ai_models/` 模型客户端工厂、`shared/storage/client_factory.py`（ES/MinIO/Redis 单例）、`shared/search/external_search_service.py`（web 搜索唯一工厂）、`shared/mq/`。
- **R4 引擎不定义 Protocol 端口**：引擎需要宿主能力时直接收具体类实例（PromptManager/ModelConfigService 等）或普通参数传值；引擎 import features 具体类在 R1 下合法。
- **R5 工厂自注册**：模型客户端（llm/embedding/rerank/asr）与 web 搜索源用 `_FACTORY_NAME` 属性 + 模块扫描注册，消灭 if-else 供应商分支链。
- **R6 安全硬规则全部保留**：BaseAPIError 体系、`begin_nested()` SAVEPOINT、密钥加密、异步密码哈希、JWT 黑名单、FileValidator 魔数校验、参数化查询、路由手动注册、模块 init 注册。

## Testing Rules

Run:

- `pytest`
- `pytest -m unit`
- `pytest -m "not slow"`

Guidelines:

- Put tests in `backend/tests/`, organized by tested target (see `tests/README.md`):
  - `tests/architecture/`: global structural gates & API contract snapshots
  - `tests/core/` / `tests/shared/` / `tests/engines/<x>/` / `tests/features/<x>/`: mirror the `src/` layer of the tested module
  - `tests/integration/`: tests marked `integration` that need a running :8100 service
- Add focused regression tests for parsing bugs
- Multimodal sample files: repo-root `test_data/` if it exists locally (untracked convention, may not exist); otherwise put fixtures in `tests/fixtures/`
- When fixing pipeline issues, prefer at least one test that reproduces the original failure mode

## Knowledge Processing Notes

- Document parsing config and runtime config conversion must stay aligned
- Media parsing should degrade gracefully when metadata is incomplete
- External integrations like DeepDoc should be isolated behind shared adapters

## When Editing Backend Code

- Check whether the target code belongs to `feature` or `shared`
- Check for duplicate implementations before adding new helpers
- Update docs if you change canonical paths or architecture guidance
- If you touch imports, verify there is no second stale import path left behind
