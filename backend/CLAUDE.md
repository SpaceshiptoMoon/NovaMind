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

- `shared/clients/`: external service clients
- `shared/cache/`: cache access
- `shared/mq/`: async task runtime
- `shared/prompts/`: shared prompts
- `shared/utils/`: truly generic helpers
- `shared/document/`: cross-feature document readers & validation (truly reusable across features)

If code is only used by one feature and expresses domain behavior, keep it in that feature instead of moving it into `shared/`.

## Knowledge-Base Architecture

Canonical homes:

- `src/features/knowledge_space/`: domain layer for documents, KB config, tasks, chunk lifecycle, APIs
- `src/features/knowledge_space/pipeline/`: document parsing pipeline (DocumentLoader/DocumentProcessor/DocumentRegistry)
- `src/features/knowledge_space/splitters/`: chunk splitters (recursive/semantic/fixed/markdown)
- `src/features/knowledge_space/converters/`: document format converters
- `src/features/knowledge_space/media/`: audio/video/image multimodal processing (VLM/OCR/audio/video)
- `src/features/knowledge_space/integrations/deepdoc/`: DeepDoc-specific implementation (vendored, self-contained)
- `src/shared/document/readers/`: cross-feature document readers (PDF/DOCX/TXT/HTML/MD) — reused by app/qa/knowledge_space
- `src/shared/document/validation/`: cross-feature file validation (FileInfo/FileValidator) — reused by qa/knowledge_space

Do not duplicate parsing logic under both `shared/document/` and `features/knowledge_space/`. Knowledge-base-specific parsing (pipeline/splitters/converters/media/deepdoc) lives in `features/knowledge_space/`; only truly cross-feature readers & validation stay in `shared/document/`.

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

## 单向依赖铁律（硬规则）

分层为 `features → engines → shared`，单向不可逆。

- `engines/` 与 `shared/` 严禁 import `novamind.features.*`、`novamind.setting.*`、任何 SQLAlchemy ORM 模型、`core.database` ORM 会话。所有持久化/配置/多租户/外部资源必须经端口在 `features/` 装配点注入。端口归属：engine 专属端口（`engines/ports.py`、`engines/search_ports.py`、`engines/agent/ports.py`、`engines/rag/cache_port.py`、`engines/rag/errors.py`）归 `engines/`；feature 间公共端口（`shared/model_config_ports.py`、`shared/registry_ports.py`）留 `shared/` 中立位置；单 feature 内部端口（如 `features/user/ports.py`、`features/skill/ports.py`）下沉对应 feature。
- `engines/` 是纯逻辑层；`shared/` 是中立能力层；业务编排归属 `features/`。`shared/` 不得反向依赖 `features/` 或 `setting/`。
- 结构门禁测试 `tests/test_unidirectional_dependency_gate.py` 以 AST 扫描强制此规则，新增违规会被测试拦截。收口已完成，白名单已清空。

## Testing Rules

Run:

- `pytest`
- `pytest -m unit`
- `pytest -m "not slow"`

Guidelines:

- Put tests in `backend/tests/`
- Add focused regression tests for parsing bugs
- Use `test_data/` fixtures when validating multimodal handling
- When fixing pipeline issues, prefer at least one test that reproduces the original failure mode

## Knowledge Processing Notes

- Document parsing config and runtime config conversion must stay aligned
- Media parsing should degrade gracefully when metadata is incomplete
- External integrations like DeepDoc should be isolated behind shared adapters
- Sample files under `test_data/output/` should remain usable for local verification

## When Editing Backend Code

- Check whether the target code belongs to `feature` or `shared`
- Check for duplicate implementations before adding new helpers
- Update docs if you change canonical paths or architecture guidance
- If you touch imports, verify there is no second stale import path left behind
