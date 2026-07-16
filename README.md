# NovaMind

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![CI](https://github.com/SpaceshiptoMoon/NovaMind/actions/workflows/ci.yml/badge.svg)](https://github.com/SpaceshiptoMoon/NovaMind/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./backend/pyproject.toml)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](./docker-compose.yml)

[English](./README.en.md) | 简体中文

NovaMind 是一个面向团队与个人的智能知识平台，围绕知识库构建、检索增强问答、深度研究、Agent 工具调用、技能扩展和效果评测提供一体化能力。项目采用 `FastAPI + Vue 3` 构建，支持 Docker 一键部署，也支持前后端分离的本地开发模式。

<p align="center">
  <img src="./assets/home.png" alt="NovaMind Home" width="720">
</p>
<p align="center">
  <img src="./assets/features.png" alt="NovaMind Features" width="720">
</p>

<details open>
<summary><b>📕 目录</b></summary>

- [项目定位](#项目定位)
- [核心能力](#核心能力)
- [适合什么场景](#适合什么场景)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [访问入口](#访问入口)
- [仓库结构](#仓库结构)
- [架构概览](#架构概览)
- [项目状态](#项目状态)
- [主要模块](#主要模块)
- [配置说明](#配置说明)
- [模型接入建议](#模型接入建议)
- [测试与质量检查](#测试与质量检查)
- [文档导航](#文档导航)
- [资源与协作](#资源与协作)
- [开源协作](#开源协作)
- [许可证](#许可证)

</details>

## 项目定位

很多知识库项目只覆盖“上传文档并问答”这一段链路。NovaMind 试图覆盖更完整的工作流：

- 从空间、知识库、文档上传到解析、切分、向量化、索引
- 从检索到 RAG 问答，再到深度研究报告生成
- 从普通聊天到带工具调用、MCP 扩展和技能市场的 Agent
- 从能力搭建到测试集评测、人工复核和结果导出

如果你希望搭建的不只是一个聊天窗口，而是一套可组织知识、执行任务、评估效果的系统，NovaMind 更接近完整工作台。

## 核心能力

- `知识空间与知识库管理`：多空间隔离、成员协作、权限控制、知识库配置和文档全生命周期管理
- `混合检索`：向量检索、BM25、混合检索、Rerank、查询改写与降级策略
- `RAG 问答`：基于知识库进行多轮问答，支持会话配置和上下文压缩
- `深度研究`：联合内部知识库与外部搜索，分步骤生成研究结果和报告
- `Agent`：支持 MCP Server、工具调用、浏览器内终端和技能扩展
- `技能广场`：技能上传、审核、安装与市场化分发
- `知识库评测`：测试集、自动评测、人工打分和结果导出
- `应用中心`：面向具体业务场景封装 AI 能力

## 适合什么场景

NovaMind 更适合以下团队或个人：

- 需要管理多空间、多知识库，而不是只维护单一问答机器人
- 需要把文档处理、检索、问答、研究、Agent 和评测串成一个完整工作流
- 需要保留配置、处理过程和效果验证的可追溯性
- 需要既支持 Docker 自托管，也支持本地二次开发

如果你的目标只是快速搭一个最小聊天 Demo，这个仓库会显得偏重；如果你要的是一套长期可演进的知识工作台，它更合适。

## 技术栈

| 类别 | 技术 |
| --- | --- |
| 后端 | FastAPI, Python 3.12, SQLAlchemy, Pydantic |
| 前端 | Vue 3, TypeScript, Vite, Pinia, Vue Router, Element Plus |
| 数据存储 | MySQL 8.4 |
| 缓存 / 队列 | Redis 7, ARQ |
| 检索引擎 | Elasticsearch 9.3 |
| 对象存储 | MinIO |
| 扩展协议 | MCP |
| 部署 | Docker Compose, Nginx, Supervisord |

## 快速开始

### 方式一：一键部署

推荐第一次体验时使用。

```bash
git clone git@github.com:SpaceshiptoMoon/NovaMind.git
cd NovaMind

# Linux / macOS / Git Bash
bash deploy.sh

# Windows PowerShell
.\deploy.ps1
```

部署脚本会自动完成：

- 检查 Docker 和 Docker Compose 环境
- 从 `.env.example` 生成 `.env`
- 生成随机密码、密钥和管理员初始密码
- 创建 `docker/configs/docker.yaml`
- 创建 `backend/src/setting/yaml_config/yaml/default.yaml`
- 构建并启动完整服务栈
- 轮询 `http://localhost/health` 做健康检查

部署完成后，管理员初始密码可在根目录 `.env` 的 `ADMIN_PASSWORD` 中查看。

环境要求：

- Docker 20.10+
- Docker Compose V2+
- 最低 2 核 CPU / 4 GB 内存 / 20 GB 磁盘（Elasticsearch 默认占 512MB JVM 堆，可在 `.env` 的 `ES_JAVA_OPTS` 调整）

> [!IMPORTANT]
> **Linux 自托管必须设置 `vm.max_map_count`**：Elasticsearch 要求内核 `vm.max_map_count >= 262144`，多数 Linux 发行版默认 65530，会导致 ES 容器启动即退出（日志报 `max virtual memory areas vm.max_map_count [...] is too low`）。
>
> ```bash
> sudo sysctl -w vm.max_map_count=262144              # 临时生效（重启失效）
> echo 'vm.max_map_count=262144' | sudo tee -a /etc/sysctl.conf  # 永久生效
> ```
>
> Docker Desktop（macOS / Windows）在其 Linux VM 内已自动处理，无需此步。

常用命令：

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

### 方式二：手动 Docker 部署

如果你希望手动控制配置文件和密码：

```bash
git clone git@github.com:SpaceshiptoMoon/NovaMind.git
cd NovaMind

cp .env.example .env
cp docker/configs/docker.example docker/configs/docker.yaml
cp backend/src/setting/yaml_config/yaml/default.example backend/src/setting/yaml_config/yaml/default.yaml

docker compose up -d --build
```

说明：

- `.env` 管理基础设施密码和后端密钥
- `docker/configs/docker.yaml` 是 Docker 运行时挂载配置
- `default.yaml` 负责后端基础配置，敏感值通常由环境变量覆盖

### 方式三：本地开发

适合前后端联调或二次开发。

1. 准备后端配置文件

```bash
cd backend/src/setting/yaml_config/yaml
cp default.example default.yaml
cp development.example development.yaml
```

2. 启动后端

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

默认后端地址：`http://localhost:8100`

3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

默认前端地址：`http://localhost:5173`

## 访问入口

Docker 部署模式：

| 服务 | 地址 |
| --- | --- |
| 前端首页 | `http://localhost` |
| 后端 API 文档 | `http://localhost/docs` |
| 健康检查 | `http://localhost/health` |
| MinIO 控制台 | `http://localhost:9001` |
| Elasticsearch | `http://localhost:9200` |

本地开发模式：

| 服务 | 地址 |
| --- | --- |
| 前端开发服务器 | `http://localhost:5173` |
| 后端 API 文档 | `http://localhost:8100/docs` |
| 后端健康检查 | `http://localhost:8100/health` |

## 仓库结构

```text
NovaMind/
|- backend/                         # FastAPI 后端
|  |- main.py
|  |- pyproject.toml
|  |- src/
|  |  |- core/                     # 应用工厂、中间件、生命周期、安全
|  |  |- features/                 # 领域模块
|  |  |- setting/                  # YAML 配置加载
|  |  `- shared/                   # 共享知识处理基础设施
|  `- tests/
|- frontend/                       # Vue 3 + TypeScript 前端
|  |- src/
|  |  |- api/
|  |  |- components/
|  |  |- router/
|  |  |- stores/
|  |  `- views/
|- docker/                         # Dockerfile、Nginx、Supervisord、配置模板
|- docs/                           # 设计文档与导航文档
|- test_data/                      # 样例数据与上传样本
|- docker-compose.yml
|- deploy.ps1
|- deploy.sh
`- README.md
```

## 架构概览

默认 Docker 形态为“单应用容器 + 多基础设施容器”：

- `app` 容器内运行 `Nginx + 前端静态资源 + FastAPI`
- `mysql`、`redis`、`minio`、`elasticsearch` 以独立服务编排，基础设施端口绑定到 `127.0.0.1`，不对公网暴露
- `Nginx` 对外暴露 `80` 端口，按路径分发到静态资源或 FastAPI
- FastAPI 在容器内部监听 `8100`，仅 Nginx 可达

```text
Browser
  │  :80
  ▼
┌──────────────────────────────────────────────────────┐
│ app 容器（单容器）                                      │
│   Nginx ── /         ─▶ Vue 静态资源                    │
│        ── /api/*     ─▶ FastAPI (:8100)                │
│        ── /health    ─▶ FastAPI health endpoint         │
└──────┬───────────────────────────────────────────────┘
       │  仅 Nginx 对外暴露 80；FastAPI 仅容器内可达
       │
       ├──▶ MySQL 8.4         ORM 持久化：用户 / 空间 / 知识库 / 文档任务
       ├──▶ Redis 7           缓存 / ARQ 异步任务队列
       ├──▶ MinIO             文档原件、解析结果、附件对象存储
       └──▶ Elasticsearch 9.3 向量召回 + BM25 全文混合检索索引
```

后端采用按领域拆分的目录结构，典型模块形态如下：

```text
src/features/{module}/
|- api/
|- services/
|- repository/
|- models/
`- schemas/
```

## 项目状态

当前仓库已经完成公开开源所需的基础入口整理，后续重点在于：

- 继续稳定知识库主链路与任务模型
- 补齐前端真实业务测试，而不是只停留在最小基线
- 收敛正式设计文档与历史过程文档的边界

更具体的阶段目标见 [`ROADMAP.md`](./ROADMAP.md)。

## 主要模块

| 模块 | 路由前缀 | 说明 |
| --- | --- | --- |
| 用户与模型配置 | `/api/v1/user` | 认证、用户管理、模型配置、模型测试 |
| 知识空间 | `/api/v1/spaces` | 空间管理、成员管理、权限隔离 |
| 知识库管理 | `/api/v1/spaces/{space_id}/knowledge-bases` | 知识库创建、配置、文档管理 |
| 知识检索 | `/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/search` | 搜索模式、检索、Rerank |
| 智能问答 | `/api/v1/qa` | 基于知识库的多轮问答 |
| AI 聊天 | `/api/v1/ai-chat` | 流式对话和附件交互 |
| 深度研究 | `/api/v1/spaces/{space_id}/deep-research` | 多源搜索和研究报告 |
| 知识库评测 | `/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation` | 测试集、评测任务、导出 |
| Agent | `/api/v1/agent` | Agent、MCP Server、工具调用 |
| 技能广场 | `/api/v1/skills` | 技能上传、审核、安装、浏览 |
| 应用中心 | `/api/v1/apps` | 场景化 AI 应用 |
| 通知中心 | `/api/v1/notifications` | 站内通知和偏好设置 |
| ClawMate | `/api/v1/clawmate` | 浏览器内终端和 AI 辅助工作区 |

## 配置说明

### `.env`

用于管理基础设施密码和后端安全密钥。

| 变量 | 说明 |
| --- | --- |
| `MYSQL_ROOT_PASSWORD` | MySQL root 密码 |
| `MYSQL_DATABASE` | 默认数据库名 |
| `MINIO_ROOT_USER` | MinIO 访问账号 |
| `MINIO_ROOT_PASSWORD` | MinIO 访问密码 |
| `ES_JAVA_OPTS` | Elasticsearch JVM 参数 |
| `SECRET_KEY` | JWT 签名密钥 |
| `ENCRYPTION_KEY` | 加密密钥 |
| `ADMIN_PASSWORD` | 管理员初始密码 |

### YAML 配置

配置文件位于 `backend/src/setting/yaml_config/yaml/`：

- `default.yaml`：基础配置
- `development.yaml`：开发环境覆盖配置
- `production.yaml`：生产环境覆盖配置
- `testing.yaml`：测试环境配置
- `docker.yaml`：Docker 运行时附加配置，挂载自 `docker/configs/docker.yaml`

加载逻辑：

- `default.yaml` 作为基线
- 通过 `python main.py --config development` 或 `--config production` 指定环境
- 加载器会对配置做深度合并
- `${VAR_NAME}` 形式的变量会从环境变量解析

## 模型接入建议

NovaMind 对模型供应方没有强绑定，只要实现 OpenAI 兼容接口，就可以接入大部分能力链路。

建议至少准备三类模型：

- `LLM`：负责问答、Agent 对话和研究总结
- `Embedding`：负责向量化和召回
- `Rerank`：负责结果重排，提高检索质量

如果你的场景偏中文、多工具调用或长上下文任务，优先选择在这些维度表现稳定的模型。

## 测试与质量检查

后端：

```bash
cd backend
pytest
pytest -m unit
pytest -m "not slow"
```

前端：

```bash
cd frontend
npm run type-check
npm run test:unit
npm run lint
npm run format
```

## 文档导航

- 总体文档入口：[`docs/README.md`](./docs/README.md)
- 公开路线图：[`ROADMAP.md`](./ROADMAP.md)
- 仓库结构导航：[`docs/project-structure-navigation.md`](./docs/project-structure-navigation.md)
- 后端说明：[`backend/README.md`](./backend/README.md)
- 前端说明：[`frontend/README.md`](./frontend/README.md)
- 贡献指南：[`CONTRIBUTING.md`](./CONTRIBUTING.md)
- 安全策略：[`SECURITY.md`](./SECURITY.md)
- 支持方式：[`SUPPORT.md`](./SUPPORT.md)

## 资源与协作

- 文档入口：[`docs/README.md`](./docs/README.md)
- 当前知识空间正式设计：[`docs/knowledge-space/current/README.md`](./docs/knowledge-space/current/README.md)
- 历史计划与重构材料：[`docs/plans/README.md`](./docs/plans/README.md)
- 交接与历史上下文：[`docs/handover/README.md`](./docs/handover/README.md)
- 贡献方式：[`CONTRIBUTING.md`](./CONTRIBUTING.md)
- 行为准则：[`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)
- 安全报告：[`SECURITY.md`](./SECURITY.md)
- 支持渠道：[`SUPPORT.md`](./SUPPORT.md)

## 开源协作

作为公开仓库，建议从以下入口开始：

- 使用根 README 完成首次启动和环境准备
- 使用 `ROADMAP.md` 了解当前阶段重点建设方向
- 使用 `docs/README.md` 找到架构、知识库和前端相关设计文档
- 提交 PR 前运行与改动相关的测试、类型检查和 lint
- 涉及配置、文档、截图或运维流程的改动，请一并更新对应文档
- 反馈与讨论：在 [GitHub Issues](https://github.com/SpaceshiptoMoon/NovaMind/issues) 提交问题，仓库已内置 bug / feature / 文档三类 Issue 模板

## 许可证

This repository is released under the [MIT License](./LICENSE).
