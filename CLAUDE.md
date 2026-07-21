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

## Parallel Multi-Agent Development

When running multiple agent windows (or developers) on this repo concurrently, isolate each in its own git worktree on its own branch. Never let multiple agents edit the same working directory — overlapping edits get silently overwritten at the filesystem level before git can intervene, and cannot be recovered or attributed.

- **One agent = one worktree = one branch.** Create on startup: `git worktree add ../intelligent-<scope> -b feat/<scope>-<desc>`, then work inside it; or let Claude Code create a worktree via its built-in command.
- **Place worktrees outside the repo** (not inside `src/`, `backend/`, or other scanned source dirs). Branch from a clean base (`main` or the current trunk) — uncommitted changes from another working directory do not carry over, which is the point of the isolation.
- **Divide tasks by feature boundary** (`backend/src/features/<domain>/`). Single-point shared files may be edited by only one agent at a time; queue the rest:
  - `backend/src/shared/prompts/` (prompt registry)
  - `backend/src/core/middleware/router_manager.py` (route registration)
  - `backend/src/core/middleware/startup_manager.py` (module init registration)
  - `*.example` config templates, `CLAUDE.md`, `docs/` architecture docs, DB models
- **Commit frequently and atomically.** Do not sit on uncommitted changes overnight; commit or stash before stopping.
- **Merge back from a clean trunk:** `git checkout main` → `git merge feat/<scope>-<desc>`. Run the relevant tests after each merge before starting the next.
- **Clean up after merge:** `git worktree remove ../intelligent-<scope>` + `git branch -d feat/<scope>-<desc>` + `git worktree prune`.
- **Keep the main working directory for integration merges and trunk sync**, not as any agent's dev workspace.

Full workflow and conflict-resolution guidance: see `docs/multi-agent-parallel-development-workflow.md`.

## Backend Structure

Main backend areas:

- `backend/main.py`: backend entry point
- `backend/src/core/`: app factory, middleware, lifecycle, database, security, shared runtime infrastructure
- `backend/src/features/`: feature-oriented domain modules
- `backend/src/setting/`: configuration loading and YAML config assets
- `backend/src/shared/`: reusable shared capabilities, including `ai_models/`, `cache/`, `clients/`, `mq/`, `repository/`, `storage/`, `prompts/`, `utils/`, `knowledge/`

### `novamind` import root (compatibility shim)

`backend/src/novamind/__init__.py` is a compatibility package that extends `__path__` so that `novamind.core.*`, `novamind.features.*`, `novamind.shared.*`, `novamind.setting.*` resolve to `backend/src/core/`, `backend/src/features/`, `backend/src/shared/`, `backend/src/setting/` respectively. There is no real code under `backend/src/novamind/` — always import via the `novamind.<area>...` absolute path, and look for the actual implementation under `backend/src/<area>/`.

Feature modules should stay organized as:

- `api/`: FastAPI route layer. Also hosts feature-local helpers that are wiring, not business logic: `startup.py` (registers the feature via `register_feature_initializer`), `exceptions.py` (feature-specific `BaseAPIError` subclasses), `dependencies.py` (FastAPI dependencies). Keep business logic out of these files.
- `services/`: business workflows and orchestration
- `repository/`: database access
- `models/`: ORM models
- `schemas/`: request/response and internal Pydantic models
- `prompts/` (optional): feature-local prompt templates. Use `shared/prompts/` for cross-feature reusable prompts; use a feature-local `prompts/` (or a top-level `<feature>_prompts.py`) only when the prompt is specific to that feature and not expected to be reused elsewhere.

## Frontend Structure

Main frontend areas:

- `frontend/src/api/`: API clients grouped by domain
- `frontend/src/components/`: reusable UI components grouped by domain
- `frontend/src/views/`: route-level pages
- `frontend/src/stores/`: Pinia stores
- `frontend/src/router/`: route registration
- `frontend/src/layouts/`: application shells
- `frontend/src/composables/`: reusable Composition API composables
- `frontend/src/utils/`: generic front-end helpers
- `frontend/src/types/`: shared TS types

Knowledge-base UI should stay concentrated in:

- `frontend/src/api/knowledge/`
- `frontend/src/components/knowledge/`
- `frontend/src/views/space/`

## Knowledge-Base Canonical Homes

Knowledge-base related code should use these canonical locations:

- `backend/src/features/knowledge_space/`: knowledge-base domain behavior, tasks, APIs, schemas, repositories
- `backend/src/shared/knowledge/document_processing/`: text and document parsing pipeline
- `backend/src/shared/knowledge/media_processing/`: audio, video, OCR, VLM, and multimodal processing. Note: `media_processing/image/` is currently a placeholder (only `__init__.py`); actual image understanding lives in `media_processing/vlm/` and DeepDoc's `integrations/deepdoc/vision/`, and image embedding goes through VLM description + text embedding (see multimodal-embedding memory). Do not assume `image/` contains image processing logic.
- `backend/src/shared/knowledge/integrations/deepdoc/`: DeepDoc integration only

Generic helpers that are not knowledge-specific belong under:

- `backend/src/shared/utils/`

`shared/utils/` should only contain generic utilities such as time, crypto, redact, heartbeat, and truly generic text helpers. It should not become a second home for parser logic, media workflows, or vendor integrations.

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

- 安装依赖：`cd backend && uv pip install .`（项目统一用 uv，不用 pip/poetry）
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

## Hard Rules

These are non-negotiable. They override convenience and override anything softer in the sections above.

### Prohibited Actions

- **Do not commit secrets.** `.env`, `*.yaml` config files, API keys, and passwords must not be committed to Git.
- **Never bypass Git hooks with `--no-verify`.** If a hook fails, fix the underlying issue.
- **No weak passwords or wildcard CORS** in production config.
- **No hardcoded credentials.** All config goes through YAML + environment variables.

### Backend Coding Rules

- **Exceptions:** all business exceptions extend `BaseAPIError` and are registered in the module `startup.py`. Never `raise HTTPException` directly.
- **Database writes:** repository write operations must use `begin_nested()` (SAVEPOINT). Never commit directly.
- **API key storage:** use `encrypt_api_key_async` / `decrypt_api_key_async`. Never store plaintext.
- **Password hashing:** use `verify_password_async` / `get_password_hash_async`. Never block the event loop with sync hashing.
- **Pydantic schemas:** prefer the layering `*Base → *Create/*Update → *Response` for new schemas, and `*Response` must set `from_attributes=True`. Legacy schemas are not fully aligned with this pattern — e.g. `knowledge_space` schemas (`SpaceCreate`, `DocumentResponse`, `ChunkResponse`) inherit directly from `BaseModel` without a `*Base`. When touching those files you may align them locally, but do not treat the absence of `*Base` in legacy schemas as a violation requiring a sweeping refactor.
- **Route registration:** new routes must be registered manually in `router_manager.py`. There is no auto-discovery.
- **Module init:** new modules must register `register_feature_initializer` in `startup_manager.py`.
- **Config files:** all `*.yaml` are gitignored; commit only `*.example` templates.

### Frontend Coding Rules

- **Components:** always use `<script setup lang="ts">` + Composition API.
- **API calls:** use typed methods like `request.get<T>()`. No bare `axios` calls.
- **SSE streaming:** use `createSSEStream()` + `AbortController`. Do not use Axios for SSE.
- **State management:** use Pinia stores. Do not manage cross-component state inside components.
- **Types:** put all API types in `api/types.ts`, re-exported via `types/index.ts`.
- **View naming:** `PascalCase` + `View` suffix, under `views/{domain}/`.

### Security Rules

- **Auth:** all authenticated routes use `Depends(get_current_user)`; admin routes add `Depends(require_admin)`.
- **Token management:** JWT blacklist lives in Redis. On logout / disable / delete user, purge all associated tokens.
- **Input validation:** validate all user input via Pydantic schemas. No manual validation in the route layer.
- **File uploads:** validate type and magic number via `FileValidator`. Do not rely on extension alone.
- **SQL injection:** use parameterized SQLAlchemy ORM queries. Never concatenate SQL strings.

## Important Documentation

- `docs/project-structure-navigation.md`
- `docs/knowledge-space/current/knowledge-architecture-navigation.md`
- `docs/knowledge-space/current/knowledge-config-structure-design.md`
- `docs/plans/active/repository-structure-cleanup-plan.md`
- `docs/multi-agent-parallel-development-workflow.md`
- `docs/transaction-boundary-conventions.md` — authoritative source for the `begin_nested()` SAVEPOINT rule used by repository write operations