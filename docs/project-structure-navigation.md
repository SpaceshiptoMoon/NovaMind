# Project Structure Navigation

> Repository-level navigation guide for the current backend, frontend, and knowledge-base domain structure.

---

## Overview

This repository is organized as a full-stack project with:

- `backend/`: FastAPI backend and domain services
- `frontend/`: Vue 3 + TypeScript frontend
- `docs/`: formal design notes, cleanup plans, and navigation documents
- `docker/`: deployment assets
- `test_data/`: sample fixtures and upload data

The most important structural principle is domain grouping:

- backend business logic is grouped under `backend/src/features/`
- backend shared infrastructure lives under `backend/src/core/`, `backend/src/shared/`, and `backend/src/setting/`
- frontend knowledge-base code is grouped under dedicated knowledge-domain paths

## Top-Level Directory Guide

| Path | Purpose |
| --- | --- |
| `backend/` | FastAPI app, domain modules, tests, and config |
| `frontend/` | Vue frontend, API clients, stores, layouts, and views |
| `docs/` | official design docs, plans, migration notes, and navigation |
| `docker/` | Dockerfiles and related deployment assets |
| `test_data/` | upload samples and test fixtures |
| `logs/` | generated runtime logs |

## Backend Structure

### Application Entry

| Path | Purpose |
| --- | --- |
| `backend/main.py` | backend startup entry |
| `backend/src/core/` | app factory, middleware, lifecycle, framework-level plumbing |
| `backend/src/setting/` | YAML configuration and config models |

### Domain Modules

Backend domain code is primarily grouped under:

```text
backend/src/features/
  knowledge_space/
  qa/
  agent/
  deep_research/
  evaluation/
  user/
  notification/
  app/
  skill/
```

Each domain generally follows a DDD-style layout:

```text
api/
services/
repository/
models/
schemas/
```

### Shared Infrastructure

| Path | Purpose |
| --- | --- |
| `backend/src/shared/ai_models/` | model integrations such as LLM, embedding, ASR, or VLM |
| `backend/src/shared/storage/` | storage adapters such as MinIO |
| `backend/src/shared/mq/` | async worker and task-tracking infrastructure |
| `backend/src/shared/utils/` | shared helpers, compatibility layers, and utility functions |

### Knowledge-Base Backend Focus

Knowledge-base backend logic is centered in:

```text
backend/src/features/knowledge_space/
```

Key areas:

- `api/`: knowledge base, document, search, and related routes
- `services/`: knowledge base and document processing logic
- `repository/`: persistence and query access
- `models/`: ORM models
- `schemas/`: API schemas and config structures

## Frontend Structure

### Core Frontend Areas

| Path | Purpose |
| --- | --- |
| `frontend/src/api/` | typed API clients |
| `frontend/src/components/` | reusable and domain-oriented UI components |
| `frontend/src/views/` | route-level pages |
| `frontend/src/stores/` | Pinia stores |
| `frontend/src/router/` | route registration |
| `frontend/src/layouts/` | high-level application layouts |

### Knowledge-Base Frontend Grouping

Knowledge-base frontend code has been regrouped into clearer domain paths:

```text
frontend/src/api/knowledge/
frontend/src/components/knowledge/
frontend/src/views/space/
```

Important files:

| Path | Purpose |
| --- | --- |
| `frontend/src/api/knowledge/knowledgeBase.ts` | knowledge base CRUD and config APIs |
| `frontend/src/api/knowledge/document.ts` | document upload, processing, detail, and chunk APIs |
| `frontend/src/api/knowledge/search.ts` | knowledge search APIs |
| `frontend/src/api/knowledge/evaluation.ts` | evaluation-related APIs |
| `frontend/src/components/knowledge/KbSidebar.vue` | knowledge-base section sidebar |
| `frontend/src/components/knowledge/KbTextParsingSection.vue` | text parsing config UI |
| `frontend/src/components/knowledge/KbMultimodalParsingSection.vue` | image/video/audio parsing UI |
| `frontend/src/components/knowledge/KbSplittingSection.vue` | chunk splitting config UI |
| `frontend/src/components/knowledge/KbQuestionGenerationSection.vue` | question generation config UI |
| `frontend/src/components/knowledge/navigation.ts` | knowledge navigation helper |

### Knowledge-Base Views

Main knowledge-base pages remain under:

```text
frontend/src/views/space/
```

Representative pages:

- `KnowledgeBaseView.vue`
- `DocumentView.vue`
- `DocumentDetailView.vue`
- `DocumentTaskBatchView.vue`
- `SearchView.vue`
- `KbEvaluationView.vue`
- `KbConfigView.vue`
- `SpaceListView.vue`
- `SpaceSettingsView.vue`

## Documentation Structure

The repository now uses `docs/` as the canonical location for formal documents.

| Path | Purpose |
| --- | --- |
| `docs/frontend/` | frontend design and UI-related documentation |
| `docs/knowledge-space/` | knowledge-base design notes, migration summaries, and improvement docs |
| `docs/plans/` | cleanup plans, execution plans, and refactor guidance |
| `docs/project-structure-navigation.md` | canonical repository structure guide |

## Current Cleanup Direction

The repository cleanup effort is currently centered on:

1. making docs entrypoints stable and readable
2. grouping knowledge-base frontend code by domain
3. clarifying backend shared utility responsibilities
4. reducing confusing legacy or duplicated structural artifacts

## How To Use This Document

Use this file when you need to:

- onboard to the repository quickly
- find the canonical location for knowledge-base frontend code
- understand where backend domain logic lives
- locate the formal docs that describe ongoing structural cleanup

For detailed implementation sequencing, refer to the documents in `docs/plans/`.
