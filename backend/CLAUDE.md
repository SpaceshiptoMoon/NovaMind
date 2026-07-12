# CLAUDE.md - Backend

## Overview

The backend is a FastAPI application using a feature-oriented, DDD-leaning structure.

Entry points:

- `main.py`
- `src/core/middleware/app_factory.py`
- `src/core/middleware/router_manager.py`
- `src/core/middleware/startup_manager.py`

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
- `shared/knowledge/`: knowledge-processing implementation

If code is only used by one feature and expresses domain behavior, keep it in that feature instead of moving it into `shared/`.

## Knowledge-Base Architecture

Canonical homes:

- `src/features/knowledge_space/`: domain layer for documents, KB config, tasks, chunk lifecycle, APIs
- `src/shared/knowledge/document_processing/`: text/document parsing implementation
- `src/shared/knowledge/media_processing/`: audio/video/image multimodal processing
- `src/shared/knowledge/integrations/deepdoc/`: DeepDoc-specific implementation

Do not duplicate parsing logic under both `shared/utils/` and `shared/knowledge/`.

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
