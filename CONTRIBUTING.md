# Contributing to NovaMind

Thanks for contributing to NovaMind.

## Before You Start

- Check existing issues and pull requests before starting large work.
- For non-trivial changes, open an issue or discussion first so the scope is clear.
- Keep changes focused. Avoid mixing refactors, feature work, and formatting-only edits in one pull request.

## Development Setup

### Backend

```bash
cd backend
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1
pip install .
pytest
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Docker

```bash
cp .env.example .env
cp docker/configs/docker.example docker/configs/docker.yaml
cp backend/src/setting/yaml_config/yaml/default.example backend/src/setting/yaml_config/yaml/default.yaml
docker compose up -d --build
```

## Branches and Commits

- Prefer small pull requests that solve one problem.
- Use Conventional Commits when possible.
- Good examples:
  - `feat(knowledge): add document retry status filter`
  - `fix(agent): guard missing tool call payload`
  - `docs: update docker setup guide`

## Pull Request Checklist

Before opening a pull request, make sure you have:

- Run backend tests relevant to your change.
- Run frontend type check and lint for frontend changes.
- Updated docs or examples if behavior changed.
- Called out new environment variables, schema changes, or migration steps.
- Added screenshots or API examples when UI or contract behavior changes.

## Code Style

### Python

- Target Python 3.12+.
- Follow the existing DDD layout under `backend/src/features/`.
- Keep routes in `api/`, business logic in `services/`, persistence in `repository/`, ORM models in `models/`, and DTOs in `schemas/`.

### Frontend

- Use Vue 3 + TypeScript.
- Keep components and views in `PascalCase`.
- Keep stores as short `camelCase` files.
- Run:

```bash
cd frontend
npm run type-check
npm run lint
npm run format
```

## Tests

Recommended local checks:

```bash
cd backend
pytest
pytest -m unit
pytest -m "not slow"
```

```bash
cd frontend
npm run type-check
npm run test:unit -- --run
npm run lint
```

## Reporting Bugs

When filing a bug, include:

- What you expected to happen
- What actually happened
- Exact steps to reproduce
- Logs, screenshots, or request/response samples when relevant
- Your environment details: OS, Python, Node, Docker, database, and browser

## Security

Do not open public issues for undisclosed security vulnerabilities. See [SECURITY.md](./SECURITY.md).
