# Docker 开发环境

使用 Docker Compose 一键启动所有服务，快速搭建开发环境。

## 服务清单

| 服务 | 端口 | 说明 |
|------|------|------|
| **app** | 8100 | FastAPI 应用 |
| **mysql** | 3306 | MySQL 8.0，字符集 utf8mb4 |
| **redis** | 6379 | Redis 7，无密码 |
| **minio** | 9005 / 9001 | MinIO 对象存储（9001 为控制台，账号见 `.env` 的 `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`） |
| **elasticsearch** | 9200 | ES 8.15，单节点，已禁用安全认证 |

## 快速开始

```bash
# 启动所有服务
docker compose up -d

# 查看服务状态
docker compose ps

# 查看应用日志
docker compose logs -f app
```

启动完成后访问：
- API 文档：http://localhost:8100/docs
- MinIO 控制台：http://localhost:9001（账号见 `.env`）
- Elasticsearch：http://localhost:9200

**首次启动**会自动创建数据库表和管理员账户（账号/密码见 `.env` 的 `ADMIN_USERNAME`/`ADMIN_PASSWORD`），无需手动操作。

## 常用命令

```bash
# 停止所有服务（保留数据）
docker compose down

# 停止并清除所有数据
docker compose down -v

# 代码变更后重建应用镜像
docker compose up -d --build app

# 重建所有镜像
docker compose up -d --build

# 进入应用容器
docker compose exec app bash

# 查看 MySQL 数据
docker compose exec mysql mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" novamind_db

# 查看 Redis 状态
docker compose exec redis redis-cli ping
```

## 服务依赖与启动顺序

应用依赖 MySQL、Redis、Elasticsearch 三个服务就绪后才会启动。Docker Compose 通过健康检查机制确保启动顺序：

1. MySQL、Redis、Elasticsearch 并行启动
2. 健康检查通过后，app 服务启动
3. app 启动时自动创建数据库表和管理员账户

## 数据持久化

所有数据存储在 Docker 命名卷中，`docker compose down` 不会丢失数据：

| 卷名 | 用途 |
|------|------|
| `mysql-data` | MySQL 数据 |
| `redis-data` | Redis 数据 |
| `minio-data` | MinIO 对象存储 |
| `es-data` | Elasticsearch 索引 |

清除所有数据：`docker compose down -v`

## 配置说明

开发环境配置文件为 `src/setting/yaml_config/yaml/development.yaml`，已将服务地址配置为 Docker 内部服务名：

- `database.host: mysql`
- `redis.host: redis`
- `minio.endpoint: minio:9005`
- `elasticsearch.hosts: http://elasticsearch:9200`

修改配置后需要重建应用镜像：`docker compose up -d --build app`

## 不使用 Docker 运行

如果只使用部分 Docker 服务（如只用 MySQL 和 Redis），可以将 `development.yaml` 中的主机名改回 `localhost`，然后单独启动需要的服务：

```bash
# 只启动 MySQL 和 Redis
docker compose up -d mysql redis

# 本地运行应用
python main.py --config development
```

## 故障排查

**应用启动失败**
```bash
# 查看详细日志
docker compose logs app

# 检查依赖服务是否就绪
docker compose ps
```

**MySQL 连接被拒绝**
```bash
# 等待 MySQL 完全启动（约 30 秒），检查健康状态
docker compose ps mysql
```

**Elasticsearch 内存不足**
修改 `docker-compose.yml` 中 `ES_JAVA_OPTS` 的内存配置，如 `-Xms256m -Xmx256m`。
