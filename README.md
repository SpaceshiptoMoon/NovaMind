# 智能知识库系统

基于 FastAPI + Vue 3 构建的智能知识库管理系统，支持文档管理、向量检索、多模型智能问答、深度研究等功能。

## 技术栈

| 类别 | 技术 |
|------|------|
| 后端框架 | FastAPI + Python 3.12 |
| 前端框架 | Vue 3 + TypeScript + Vite |
| 数据库 | MySQL 8.0 |
| 缓存 | Redis 7 |
| 搜索引擎 | Elasticsearch 8.15 |
| 对象存储 | MinIO |
| AI 模型 | OpenAI 兼容接口（通义千问等） |
| 认证 | JWT + Argon2 |

## 功能模块

| 模块 | 说明 |
|------|------|
| 用户管理 | JWT 认证、角色权限控制 |
| 知识空间 | 文档管理、向量检索、多策略搜索 |
| 智能问答 | 多模型对话、会话管理 |
| AI 聊天 | 实时 AI 对话 |
| 深度研究 | 多源搜索、研究报告生成 |
| 知识库测评 | 测试集管理、自动化测评、人工评分 |

## 项目结构

```
intelligent/
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
│       └── docker.yaml        # Docker 环境后端配置
├── docker-compose.yml          # 一键部署
└── README.md
```

## Docker 一键部署

### 部署架构

前端、后端和 Nginx 部署在同一个容器中，通过 supervisord 管理。Nginx 对外暴露 80 端口，同时提供前端静态文件服务和 API 反向代理。

```
Docker Compose
├── app 容器 (:80)
│   ├── Nginx (监听 80)
│   │   ├── /           → 前端静态文件
│   │   └── /api/*      → 反向代理 → 127.0.0.1:8100 (FastAPI)
│   └── FastAPI (监听 8100，容器内部)
│       ├── MySQL :3306
│       ├── Redis :6379
│       ├── Elasticsearch :9200
│       └── MinIO :9005
├── MySQL 8.0
├── Redis 7
├── MinIO
└── Elasticsearch 8.15
```

### 环境要求

- Docker 20.10+
- Docker Compose V2+
- 内存 >= 4GB（Elasticsearch 需要）

### 启动服务

```bash
# 构建并启动所有服务（首次需要约 5-10 分钟）
docker compose up -d --build

# 查看服务状态
docker compose ps

# 查看应用日志（前端 + 后端）
docker compose logs -f app

# 查看所有服务日志
docker compose logs -f
```

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端页面 | http://localhost |
| 后端 API 文档 | http://localhost/api/v1/docs（通过 Nginx 代理） |
| MinIO 控制台 | http://localhost:9001 |
| Elasticsearch | http://localhost:9200 |

### 默认账号

| 服务 | 用户名 | 密码 |
|------|--------|------|
| 系统管理员 | admin | ***REMOVED*** |
| MinIO | ***REMOVED*** | ***REMOVED*** |
| MySQL root | root | ***REMOVED*** |

### 常用命令

```bash
# 停止所有服务（数据保留）
docker compose down

# 停止并清除所有数据卷
docker compose down -v

# 重新构建并启动
docker compose up -d --build

# 仅重建应用容器（代码更新后）
docker compose up -d --build app

# 进入应用容器调试
docker compose exec app bash

# 查看 Nginx 日志
docker compose exec app cat /var/log/supervisor/nginx-error.log

# 查看后端日志
docker compose exec app cat /var/log/supervisor/backend-error.log
```

### 服务启动顺序

Docker Compose 会自动处理依赖关系，按以下顺序启动：

1. MySQL → 等待健康检查通过
2. Redis → 等待健康检查通过
3. Elasticsearch → 等待健康检查通过
4. App（前端 + 后端 + Nginx）→ 依赖上述服务就绪后启动

## 本地开发

### 后端

```bash
cd backend

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install .

# 启动开发服务器
python main.py --config development --reload
```

后端运行在 http://localhost:8100

### 前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端运行在 http://localhost:5173，API 请求自动代理到后端。

## License

MIT
