# Project Structure Navigation

## Overview

This repository is organized into:

- `backend/`: FastAPI backend
- `frontend/`: Vue 3 + TypeScript frontend
- `docs/`: formal design and navigation docs
- `docker/`: deployment assets
- `test_data/`: fixtures

## Backend

### Core Areas

- `backend/main.py`: backend entry
- `backend/src/core/`: app factory, middleware, lifecycle, database, security
- `backend/src/setting/`: YAML configuration
- `backend/src/features/`: domain modules
- `backend/src/shared/`: shared infrastructure and knowledge-processing code

### Domain Layout

Feature modules usually follow:

```text
api/
services/
repository/
models/
schemas/
```

### Knowledge Base

Knowledge-base business logic lives in:

- `backend/src/features/knowledge_space/`

Knowledge-processing internals live in:

- `backend/src/shared/knowledge/document_processing/`
- `backend/src/shared/knowledge/media_processing/`
- `backend/src/shared/knowledge/integrations/deepdoc/`

Generic utilities live in:

- `backend/src/shared/utils/`

## Frontend

Frontend structure centers on:

- `frontend/src/api/`
- `frontend/src/components/`
- `frontend/src/views/`
- `frontend/src/stores/`
- `frontend/src/router/`
- `frontend/src/layouts/`

Knowledge UI is grouped under:

- `frontend/src/api/knowledge/`
- `frontend/src/components/knowledge/`
- `frontend/src/views/space/`

## Docs

Primary navigation and design docs:

- `docs/knowledge-space/knowledge-architecture-navigation.md`
- `docs/knowledge-space/knowledge-reorg-status.md`
- `docs/knowledge-space/knowledge-reorg-plan.md`
- `docs/plans/`
