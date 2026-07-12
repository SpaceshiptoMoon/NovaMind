# CLAUDE.md - Frontend

## Overview

The frontend is a Vue 3 + TypeScript application.

Its job is to present workspace, knowledge-base, agent, and multimodal configuration flows clearly while staying aligned with backend API contracts.

## Directory Structure

- `src/api/`: typed API access by domain
- `src/components/`: reusable UI components by domain
- `src/views/`: route-level pages
- `src/stores/`: Pinia stores
- `src/router/`: route definitions
- `src/layouts/`: app shells and structural layouts
- `src/types/`: shared frontend types
- `src/utils/`: frontend-only helpers

## Domain Grouping Rules

Keep domain code together.

Knowledge-base related UI should primarily live in:

- `src/api/knowledge/`
- `src/components/knowledge/`
- `src/views/space/`

Do not scatter knowledge-base form logic across unrelated generic folders if it can stay inside the knowledge domain.

## Component Boundaries

- Views orchestrate data loading, page state, and route context
- Domain components render reusable business UI
- Generic base components should stay presentation-focused
- Stores manage shared client state, not page-local temporary UI state unless reused

## Coding Rules

- TypeScript only for new logic
- 2-space indentation
- `PascalCase` for Vue SFC names
- `camelCase` for composables, stores, utilities
- Prefer strongly typed API responses and form models
- Keep watchers and side effects readable and local

## UI and UX Rules

- Preserve the existing design language unless a redesign is intentional
- Knowledge-base config pages should make structure and processing flow obvious
- Complex forms should group by user intent, not backend implementation detail
- Use labels and helper text to explain mutually exclusive options and fallback behavior

## API Alignment Rules

- Frontend config models must match backend schema shape
- If backend config nesting changes, update:
  - API types
  - form state
  - submit transform
  - display logic
  - docs if needed
- Do not silently rename fields on the frontend without confirming backend compatibility

## Validation Workflow

Run locally when relevant:

- `npm run dev`
- `npm run type-check`
- `npm run lint`
- `npm run format`
- `npm run build`

If existing unrelated type errors already exist, state that clearly and still verify the touched area as far as possible.

## When Editing Frontend Code

- Check whether a change belongs in `view`, `component`, `store`, or `api`
- Prefer extending existing domain components before adding duplicates
- Keep forms understandable for both users and future developers
- When changing backend-facing config screens, verify the payload shape being submitted
