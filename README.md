# NovaMind

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./backend/pyproject.toml)
[![Vue](https://img.shields.io/badge/Vue-3.5-4FC08D?logo=vue.js&logoColor=white)](./frontend/package.json)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](./frontend/package.json)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

NovaMind 是一个开源的智能知识库管理系统。基于 FastAPI + Vue 3 构建，支持文档管理、向量检索、多模型智能问答、深度研究和知识库测评。

<p align="center">
  <img src="./assets/home.png" alt="NovaMind Home" width="720">
</p>
<p align="center">
  <img src="./assets/features.png" alt="NovaMind Features" width="720">
</p>

## 目录

- [核心特性](#核心特性)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
  - [配置](#配置)
  - [方式一：Docker（推荐）](#方式一docker推荐)
  - [方式二：本地开发](#方式二本地开发)
- [项目结构](#项目结构)
- [架构概览](#架构概览)
- [功能模块](#功能模块)
- [推荐模型](#推荐模型)
- [许可证](#许可证)

## 核心特性

- **多策略知识检索** — 向量检索 + BM25 文本检索 + 混合检索，支持 Rerank 重排序
- **多模型智能问答** — 支持 OpenAI 兼容接口，会话级模型切换，上下文压缩
- **深度研究** — 多源搜索（Tavily / SerpAPI / DuckDuckGo），自动生成研究报告
- **知识库测评** — 测试集管理、自动化批量测评、人工评分
- **Agent 智能体** — MCP Server 扩展、代码沙箱执行、多轮工具调用
- **DDD 架构** — 领域驱动设计，模块解耦，易于扩展

## 技术栈

| 类别 | 技术 |
|------|------|
| 后端框架 | FastAPI + Python 3.12 |
| 前端框架 | Vue 3 + TypeScript + Vite |
| 数据库 | MySQL 8.0 |
| 缓存 | Redis 7 |
| 搜索引擎 | Elasticsearch 8.15 |
| 对象存储 | MinIO |
| AI 模型 | OpenAI 兼容接口（通义千问、智谱 AI 等） |
| 认证 | JWT + Argon2 |

## 快速开始

### 配置

配置文件包含敏感信息（API Key、数据库密码等），未上传到 GitHub。使用前需从 `.example` 模板创建并填入真实值。

### 方式一：Docker（推荐）

```bash
# 1. 克隆项目
git clone git@github.com:SpaceshiptoMoon/NovaMind.git
cd NovaMind

# 2. 创建配置文件
cp docker/configs/docker.example docker/configs/docker.yaml
# 编辑 docker/configs/docker.yaml，填入数据库密码、ES 密码等

# 3. 启动所有服务（首次约 5-10 分钟）
docker compose up -d --build
```

> Docker 部署会自动创建数据库、建表、创建管理员账户，无需手动操作。

**访问地址：**

| 服务 | 地址 |
|------|------|
| 前端页面 | http://localhost |
| 后端 API 文档 | http://localhost/api/v1/docs |
| MinIO 控制台 | http://localhost:9001 |
| Elasticsearch | http://localhost:9200 |

**常用命令：**

```bash
docker compose ps                    # 查看服务状态
docker compose logs -f app           # 查看应用日志
docker compose down                  # 停止（保留数据）
docker compose down -v               # 停止并清除数据卷
docker compose up -d --build app     # 仅重建应用容器
```

**环境要求：** Docker 20.10+、Docker Compose V2+、内存 >= 4GB

### 方式二：本地开发

```bash
# 1. 创建后端配置
cd backend/src/setting/yaml_config/yaml/
cp default.example default.yaml
# 编辑 default.yaml，填入本地数据库密码、API Key 等

# 2. 启动后端
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install .
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS novamind_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
python main.py --config development --reload
```

后端运行在 http://localhost:8100

```bash
# 3. 启动前端
cd frontend
npm install
npm run dev
```

前端运行在 http://localhost:5173，API 请求自动代理到后端。

> 配置加载机制：`default.yaml` 为基础配置，启动时通过 `--config` 参数指定环境覆盖文件（如 `docker.yaml`），两者深度合并。

## 项目结构

```
novamind/
├── backend/                    # 后端 (FastAPI)
│   ├── src/
│   │   ├── core/              # 核心基础设施（认证、数据库、中间件）
│   │   ├── features/          # 业务模块（DDD 架构）
│   │   ├── shared/            # 跨模块共享组件
│   │   └── setting/           # 多环境配置管理
│   ├── main.py                # 后端入口
│   └── pyproject.toml
├── frontend/                   # 前端 (Vue 3)
│   ├── src/
│   │   ├── api/               # API 请求封装
│   │   ├── components/        # 公共组件
│   │   ├── views/             # 页面
│   │   ├── stores/            # Pinia 状态管理
│   │   └── router/            # 路由
│   └── package.json
├── docker/                     # Docker 部署配置
│   ├── Dockerfile             # 一体化构建（前端 + 后端 + Nginx）
│   ├── nginx.conf             # Nginx 配置
│   ├── supervisord.conf       # 进程管理配置
│   └── configs/
│       └── docker.example     # Docker 环境配置模板
├── docker-compose.yml          # 一键部署
└── README.md
```

## 架构概览

Docker 部署时，前端、后端和 Nginx 运行在同一个容器中，通过 supervisord 管理。Nginx 对外暴露 80 端口，同时提供前端静态文件服务和 API 反向代理。

```
Docker Compose
├── app 容器 (:80)
│   ├── Nginx (监听 80)
│   │   ├── /           → 前端静态文件
│   │   └── /api/*      → 反向代理 → FastAPI (:8100)
│   └── FastAPI (监听 8100，容器内部)
├── MySQL 8.0
├── Redis 7
├── MinIO
└── Elasticsearch 8.15
```

后端采用 DDD 分层架构：

```
src/features/{module}/
├── api/            # 路由、依赖注入、异常处理
├── services/       # 业务逻辑层
├── repository/     # 数据访问层
├── models/         # SQLAlchemy ORM 模型
└── schemas/        # Pydantic 数据模型
```

## 功能模块

| 模块 | 路由前缀 | 说明 |
|------|---------|------|
| 用户管理 | `/api/v1/user` | JWT 认证、角色权限控制 |
| 知识空间 | `/api/v1/spaces` | 文档管理、向量检索、多策略搜索 |
| 智能问答 | `/api/v1/qa` | 多模型对话、会话管理 |
| AI 聊天 | `/api/v1/ai-chat` | 实时流式 AI 对话 |
| 深度研究 | `/api/v1/spaces/{id}/deep-research` | 多源搜索、研究报告生成 |
| 知识库测评 | `/api/v1/spaces/{id}/knowledge-bases/{kb_id}/evaluation` | 测试集管理、自动化测评 |
| Agent 智能体 | `/api/v1/agent` | MCP Server 扩展、代码沙箱 |

## 推荐模型

NovaMind 对模型没有强绑定，只要实现了 OpenAI 兼容 API 的模型都可以接入。以下能力更强的模型效果更好：

- **长上下文窗口**（100k+ tokens），适合深度研究和多步骤问答
- **稳定的 tool use 能力**，适合 Agent 工具调用和结构化输出
- **中文理解能力**，适合中文知识库场景

已在以下模型上验证：

| Provider | 模型 | 用途 |
|----------|------|------|
| 阿里云 | qwen3.5-plus | LLM 问答 |
| 阿里云 | text-embedding-v2/v3 | 文本向量化 |
| 阿里云 | qwen3-vl-rerank | 检索重排序 |
| 智谱 AI | glm-4 | LLM 问答 |

## 许可证

本项目采用 [MIT License](./LICENSE) 开源发布。
