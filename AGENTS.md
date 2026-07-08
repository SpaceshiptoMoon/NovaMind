# Repository Guidelines

## Project Structure & Module Organization
This repository is split into `backend/` and `frontend/`. The backend is a FastAPI app rooted at `backend/main.py`, with domain code under `backend/src/features/<module>/` and shared infrastructure in `backend/src/core/`, `backend/src/shared/`, and `backend/src/setting/`. Backend tests live in `backend/tests/`, with sample evaluation data in `backend/test/`. The frontend is a Vue 3 + TypeScript app in `frontend/src/`, organized by `api/`, `components/`, `views/`, `stores/`, and `router/`. Deployment assets live in `docker/`, docs in `docs/`, and sample upload fixtures in `test_data/`.

## Build, Test, and Development Commands
Use the repo-level scripts for full-stack setup: `bash deploy.sh` or `.\deploy.ps1` starts the Docker stack. For local backend work: `cd backend && pip install . && python main.py --config development --reload`. For frontend work: `cd frontend && npm install && npm run dev`. Build the frontend with `npm run build`, preview it with `npm run preview`, and validate types with `npm run type-check`.

## Coding Style & Naming Conventions
Python targets 3.12+ and follows the existing DDD layout: keep routes in `api/`, business logic in `services/`, persistence in `repository/`, ORM models in `models/`, and Pydantic schemas in `schemas/`. Use 4-space indentation, `snake_case` for Python modules/functions, and `PascalCase` for classes. Frontend code uses TypeScript, Vue SFCs, and 2-space indentation; name components and views in `PascalCase` such as `KnowledgeBaseView.vue`, and stores as short `camelCase` files like `space.ts`. Run `npm run lint` and `npm run format` before submitting frontend changes.

## Testing Guidelines
Backend tests use `pytest` with discovery patterns `test_*.py` and `*_test.py`. Run all backend tests with `cd backend && pytest`, or target markers such as `pytest -m unit` and `pytest -m "not slow"`. Frontend unit tests use Vitest in `jsdom`; run them with `cd frontend && npm run test:unit`. Add tests next to the feature area they cover and prefer explicit names like `test_knowledge_space_api.py`.

## Commit & Pull Request Guidelines
Recent history follows Conventional Commits with optional scopes, for example `feat(knowledge): ...`, `fix: ...`, and `docs: ...`. Keep commit subjects imperative and focused on one change. Pull requests should include a concise summary, impacted areas (`backend`, `frontend`, `docker`, config), linked issues when applicable, and screenshots or API examples for UI or contract changes. Call out new env vars, schema changes, or migration steps explicitly.

## Security & Configuration Tips
Do not commit real secrets from `.env`; start from `.env.example` and the YAML examples under `backend/src/setting/yaml_config/yaml/`. Treat `logs/` and `test_data/output/` as generated artifacts, and scrub any sensitive sample data before adding fixtures.
