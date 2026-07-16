# NovaMind

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![CI](https://github.com/SpaceshiptoMoon/NovaMind/actions/workflows/ci.yml/badge.svg)](https://github.com/SpaceshiptoMoon/NovaMind/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./backend/pyproject.toml)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](./docker-compose.yml)

English | [简体中文](./README.md)

NovaMind is an intelligent knowledge platform for teams and individuals, built around knowledge-base construction, retrieval-augmented QA, deep research, agent tool-calling, skill extensions, and effect evaluation. It is built with `FastAPI + Vue 3`, supports one-command Docker deployment, and also works as a decoupled local development setup.

<p align="center">
  <img src="./assets/home.png" alt="NovaMind Home" width="720">
</p>
<p align="center">
  <img src="./assets/features.png" alt="NovaMind Features" width="720">
</p>

<details open>
<summary><b>📕 Table of Contents</b></summary>

- [What it is](#what-it-is)
- [Core capabilities](#core-capabilities)
- [Who it's for](#whos-it-for)
- [Tech stack](#tech-stack)
- [Quick start](#quick-start)
- [Access points](#access-points)
- [Repository layout](#repository-layout)
- [Architecture overview](#architecture-overview)
- [Project status](#project-status)
- [Modules](#modules)
- [Configuration](#configuration)
- [Model integration](#model-integration)
- [Testing & quality checks](#testing--quality-checks)
- [Documentation](#documentation)
- [Resources & collaboration](#resources--collaboration)
- [Open-source collaboration](#open-source-collaboration)
- [License](#license)

</details>

## What it is

Many knowledge-base projects only cover the "upload a document and chat" segment of the workflow. NovaMind tries to cover a more complete pipeline:

- From spaces, knowledge bases, and document upload to parsing, splitting, vectorization, and indexing
- From retrieval to RAG QA, and on to deep-research report generation
- From plain chat to agents with tool-calling, MCP extensions, and a skill marketplace
- From building capabilities to evaluation test sets, manual review, and result export

If you want to build more than a chat window — a system that can organize knowledge, execute tasks, and evaluate results — NovaMind is closer to a full workbench.

## Core capabilities

- `Knowledge spaces & knowledge bases`: multi-space isolation, member collaboration, access control, KB configuration, full document lifecycle
- `Hybrid retrieval`: vector search, BM25, hybrid search, rerank, query rewriting, and fallback strategies
- `RAG QA`: multi-turn QA over knowledge bases, with session config and context compression
- `Deep research`: combines internal KBs with external search, generates step-by-step research reports
- `Agent`: supports MCP servers, tool calling, an in-browser terminal, and skill extensions
- `Skill marketplace`: skill upload, review, install, and distribution
- `KB evaluation`: test sets, automated evaluation, manual scoring, and result export
- `App center`: scenario-packaged AI capabilities

## Who it's for

NovaMind is a better fit for teams or individuals who:

- Need to manage multiple spaces and KBs, not just maintain a single QA bot
- Want to chain document processing, retrieval, QA, research, agents, and evaluation into one workflow
- Need traceability of config, processing, and effect verification
- Want both Docker self-hosting and local secondary development

If your goal is just a minimal chat demo, this repo will feel heavy; if you want a long-evolvable knowledge workbench, it fits.

## Tech stack

| Category | Tech |
| --- | --- |
| Backend | FastAPI, Python 3.12, SQLAlchemy, Pydantic |
| Frontend | Vue 3, TypeScript, Vite, Pinia, Vue Router, Element Plus |
| Database | MySQL 8.4 |
| Cache / Queue | Redis 7, ARQ |
| Search engine | Elasticsearch 9.3 |
| Object storage | MinIO |
| Extension protocol | MCP |
| Deployment | Docker Compose, Nginx, Supervisord |

## Quick start

### Option 1: one-command deploy

Recommended for a first run.

```bash
git clone git@github.com:SpaceshiptoMoon/NovaMind.git
cd NovaMind

# Linux / macOS / Git Bash
bash deploy.sh

# Windows PowerShell
.\deploy.ps1
```

The deploy script will automatically:

- Check the Docker and Docker Compose environment
- Generate `.env` from `.env.example`
- Generate random passwords, secrets, and the initial admin password
- Create `docker/configs/docker.yaml`
- Create `backend/src/setting/yaml_config/yaml/default.yaml`
- Build and start the full stack
- Poll `http://localhost/health` for a health check

After deploy, the initial admin password is in `ADMIN_PASSWORD` in the root `.env`.

Requirements:

- Docker 20.10+
- Docker Compose V2+
- At least 2 CPU cores / 4 GB RAM / 20 GB disk (Elasticsearch uses a 512MB JVM heap by default; tune via `ES_JAVA_OPTS` in `.env`)

> [!IMPORTANT]
> **On Linux self-hosting you must set `vm.max_map_count`**. Elasticsearch requires `vm.max_map_count >= 262144`; most Linux distributions default to 65530, which makes the ES container exit immediately on boot (log: `max virtual memory areas vm.max_map_count [...] is too low`).
>
> ```bash
> sudo sysctl -w vm.max_map_count=262144              # temporary (lost on reboot)
> echo 'vm.max_map_count=262144' | sudo tee -a /etc/sysctl.conf  # permanent
> ```
>
> Docker Desktop (macOS / Windows) already handles this inside its Linux VM — no action needed.

Common commands:

```bash
bash deploy.sh status
bash deploy.sh logs
bash deploy.sh update
bash deploy.sh stop
bash deploy.sh clean
```

```powershell
.\deploy.ps1 status
.\deploy.ps1 logs
.\deploy.ps1 update
.\deploy.ps1 stop
.\deploy.ps1 clean
```

### Option 2: manual Docker deploy

If you prefer to control config files and passwords yourself:

```bash
git clone git@github.com:SpaceshiptoMoon/NovaMind.git
cd NovaMind

cp .env.example .env
cp docker/configs/docker.example docker/configs/docker.yaml
cp backend/src/setting/yaml_config/yaml/default.example backend/src/setting/yaml_config/yaml/default.yaml

docker compose up -d --build
```

Notes:

- `.env` holds infrastructure passwords and backend secrets
- `docker/configs/docker.yaml` is the Docker runtime mount config
- `default.yaml` holds base backend config; sensitive values are usually overridden by env vars

### Option 3: local development

For frontend/backend co-development or secondary development.

1. Prepare backend config

```bash
cd backend/src/setting/yaml_config/yaml
cp default.example default.yaml
cp development.example development.yaml
```

2. Start the backend

```bash
cd backend
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install .
python main.py --config development --reload
```

Default backend address: `http://localhost:8100`

3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Default frontend address: `http://localhost:5173`

## Access points

Docker deploy:

| Service | Address |
| --- | --- |
| Frontend | `http://localhost` |
| Backend API docs | `http://localhost/docs` |
| Health check | `http://localhost/health` |
| MinIO console | `http://localhost:9001` |
| Elasticsearch | `http://localhost:9200` |

Local dev:

| Service | Address |
| --- | --- |
| Frontend dev server | `http://localhost:5173` |
| Backend API docs | `http://localhost:8100/docs` |
| Backend health check | `http://localhost:8100/health` |

## Repository layout

```text
NovaMind/
|- backend/                         # FastAPI backend
|  |- main.py
|  |- pyproject.toml
|  |- src/
|  |  |- core/                     # app factory, middleware, lifecycle, security
|  |  |- features/                 # domain modules
|  |  |- setting/                  # YAML config loading
|  |  `- shared/                   # shared knowledge-processing infra
|  `- tests/
|- frontend/                       # Vue 3 + TypeScript frontend
|  |- src/
|  |  |- api/
|  |  |- components/
|  |  |- router/
|  |  |- stores/
|  |  `- views/
|- docker/                         # Dockerfile, Nginx, Supervisord, config templates
|- docs/                           # design docs and navigation docs
|- test_data/                      # sample data and upload fixtures
|- docker-compose.yml
|- deploy.ps1
|- deploy.sh
`- README.md
```

## Architecture overview

The default Docker form is "single app container + multiple infra containers":

- The `app` container runs `Nginx + frontend static assets + FastAPI`
- `mysql`, `redis`, `minio`, `elasticsearch` run as separate services; infra ports are bound to `127.0.0.1`, not exposed publicly
- Nginx exposes port `80` and routes by path to static assets or FastAPI
- FastAPI listens on `8100` inside the container, reachable only by Nginx

```text
Browser
  │  :80
  ▼
┌──────────────────────────────────────────────────────┐
│ app container (single container)                     │
│   Nginx ── /         ─▶ Vue static assets              │
│        ── /api/*     ─▶ FastAPI (:8100)               │
│        ── /health    ─▶ FastAPI health endpoint        │
└──────┬───────────────────────────────────────────────┘
       │  only Nginx exposes 80; FastAPI is in-container only
       │
       ├──▶ MySQL 8.4         ORM persistence: users / spaces / KBs / doc tasks
       ├──▶ Redis 7           cache / ARQ async task queue
       ├──▶ MinIO             document originals, parse results, attachment objects
       └──▶ Elasticsearch 9.3 vector recall + BM25 full-text hybrid retrieval index
```

The backend uses a domain-oriented directory layout. A typical module:

```text
src/features/{module}/
|- api/
|- services/
|- repository/
|- models/
`- schemas/
```

## Project status

The repo has completed the baseline entry-point work needed for a public release. The focus going forward is:

- Continue stabilizing the KB main pipeline and task model
- Add real business tests for the frontend, beyond a minimal baseline
- Keep the boundary between formal design docs and historical process docs clear

See [`ROADMAP.md`](./ROADMAP.md) for concrete phase goals.

## Modules

| Module | Route prefix | Notes |
| --- | --- | --- |
| User & model config | `/api/v1/user` | auth, user management, model config, model testing |
| Knowledge spaces | `/api/v1/spaces` | space management, members, permission isolation |
| Knowledge bases | `/api/v1/spaces/{space_id}/knowledge-bases` | KB create, config, document management |
| Knowledge retrieval | `/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/search` | search modes, retrieval, rerank |
| QA | `/api/v1/qa` | multi-turn QA over KBs |
| AI chat | `/api/v1/ai-chat` | streaming chat and attachments |
| Deep research | `/api/v1/spaces/{space_id}/deep-research` | multi-source search and research reports |
| KB evaluation | `/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation` | test sets, eval tasks, export |
| Agent | `/api/v1/agent` | agent, MCP servers, tool calling |
| Skill marketplace | `/api/v1/skills` | skill upload, review, install, browse |
| App center | `/api/v1/apps` | scenario AI apps |
| Notifications | `/api/v1/notifications` | in-app notifications and preferences |
| ClawMate | `/api/v1/clawmate` | in-browser terminal and AI-assisted workspace |

## Configuration

### `.env`

Holds infrastructure passwords and backend security keys.

| Variable | Description |
| --- | --- |
| `MYSQL_ROOT_PASSWORD` | MySQL root password |
| `MYSQL_DATABASE` | Default database name |
| `MINIO_ROOT_USER` | MinIO access account |
| `MINIO_ROOT_PASSWORD` | MinIO access password |
| `ES_JAVA_OPTS` | Elasticsearch JVM args |
| `SECRET_KEY` | JWT signing key |
| `ENCRYPTION_KEY` | Encryption key |
| `ADMIN_PASSWORD` | Initial admin password |

### YAML config

Config files live in `backend/src/setting/yaml_config/yaml/`:

- `default.yaml`: base config
- `development.yaml`: dev overrides
- `production.yaml`: prod overrides
- `testing.yaml`: test config
- `docker.yaml`: Docker runtime附加 config, mounted from `docker/configs/docker.yaml`

Loading logic:

- `default.yaml` is the baseline
- Pick an environment via `python main.py --config development` or `--config production`
- The loader deep-merges configs
- `${VAR_NAME}` placeholders are resolved from environment variables

## Model integration

NovaMind is not hard-bound to any model provider — anything that speaks an OpenAI-compatible API can plug into most of the capability chain.

Plan for at least three model types:

- `LLM`: QA, agent chat, research summarization
- `Embedding`: vectorization and recall
- `Rerank`: result re-ranking for retrieval quality

If your use case is Chinese-heavy, multi-tool, or long-context, prioritize models that are stable on those dimensions.

## Testing & quality checks

Backend:

```bash
cd backend
pytest
pytest -m unit
pytest -m "not slow"
```

Frontend:

```bash
cd frontend
npm run type-check
npm run test:unit
npm run lint
npm run format
```

## Documentation

- Docs entry: [`docs/README.md`](./docs/README.md)
- Public roadmap: [`ROADMAP.md`](./ROADMAP.md)
- Repo structure navigation: [`docs/project-structure-navigation.md`](./docs/project-structure-navigation.md)
- Backend notes: [`backend/README.md`](./backend/README.md)
- Frontend notes: [`frontend/README.md`](./frontend/README.md)
- Contributing: [`CONTRIBUTING.md`](./CONTRIBUTING.md)
- Security policy: [`SECURITY.md`](./SECURITY.md)
- Support: [`SUPPORT.md`](./SUPPORT.md)

## Resources & collaboration

- Docs entry: [`docs/README.md`](./docs/README.md)
- Current KB formal design: [`docs/knowledge-space/current/README.md`](./docs/knowledge-space/current/README.md)
- Historical plans & migration material: [`docs/plans/README.md`](./docs/plans/README.md)
- Handover & historical context: [`docs/handover/README.md`](./docs/handover/README.md)
- Contributing: [`CONTRIBUTING.md`](./CONTRIBUTING.md)
- Code of conduct: [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)
- Security reports: [`SECURITY.md`](./SECURITY.md)
- Support channels: [`SUPPORT.md`](./SUPPORT.md)

## Open-source collaboration

As a public repo, start from:

- Use the root README for first-time setup and environment prep
- Use `ROADMAP.md` to understand current focus areas
- Use `docs/README.md` to find architecture, KB, and frontend design docs
- Run relevant tests, type checks, and lint before opening a PR
- For config, docs, screenshot, or ops-flow changes, update the matching docs too
- Feedback & discussion: open an issue on [GitHub Issues](https://github.com/SpaceshiptoMoon/NovaMind/issues); the repo ships bug / feature / documentation issue templates

## License

This repository is released under the [MIT License](./LICENSE).