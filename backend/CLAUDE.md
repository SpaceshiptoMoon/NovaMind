# CLAUDE.md

本文件为 Claude Code 提供项目指导。

---

## 项目背景

- 当前处于**开发阶段**，数据库尚未正式建立
- 不存在生产数据，不需要数据库迁移脚本
- ORM 模型变更直接修改代码即可，无需 Alembic 迁移
- 无需考虑数据兼容性、ID 跳号等生产环境问题

---

## 开发流程

严格遵守以下流程，**不可跳步，不可省略任何环节**：

### 第一步：需求分析

- 收到用户需求后，**禁止直接写代码**
- 仔细分析需求的背景、目标和约束条件
- 如有不清楚的地方，主动向用户提问确认，不要猜测
- 确认需求的边界：哪些要做、哪些不做、优先级如何

### 第二步：制定开发计划

- 基于需求分析，编写详细的开发计划
- 计划内容必须包括：
  - **需求概述**：用简明的语言复述需求目标
  - **实现方案**：具体的技术方案和设计思路
  - **涉及文件**：列出需要新增或修改的文件清单
  - **开发步骤**：按顺序列出每一步要做什么，步骤要细化到具体的代码改动
  - **风险评估**：可能遇到的问题和应对方案（如有）
- 使用 Plan 模式编写计划，生成计划文档供用户审阅

### 第三步：提交审阅

- 计划完成后，提交给用户审阅
- **等待用户明确反馈**，不要催促，不要自行推进

### 第四步：修改计划（循环）

- 用户反馈"不对"或提出修改意见 → 根据意见修改计划 → 再次提交审阅
- 用户反馈"部分可以" → 保留认可的部分，修改有问题的部分 → 再次提交审阅
- **此步骤会循环多次，直到用户完全认可为止**
- 每次修改后都必须重新提交完整的计划文档，不要只发修改片段

### 第五步：用户确认后开始开发

- **只有当用户明确说"同意按照计划文档开发"或同等含义的确认话语后，才能开始写代码**
- 没有用户确认 = 不写一行代码
- 开发过程中严格按照计划执行，不擅自添加计划之外的功能
- 如开发中发现计划有问题，**停下来向用户说明情况**，等待用户指示

### 第六步：开发完成后的核对

- 开发完成后，**主动核对**实现是否满足原始需求
- 逐项检查计划中的每个步骤是否都已落实
- 如有遗漏或偏差，主动修复，不要等用户指出

---

## 语言规范

**标准开发语言：中文**

- 所有注释、文档、提交信息、代码说明使用中文
- 变量名、函数名、类名使用英文（遵循 Python 命名规范）
- API 文档和接口说明使用中文

---

## 项目概述

基于 FastAPI 构建的智能知识库后端系统，采用领域驱动设计（DDD）架构。

| 功能模块 | 路由前缀 | 描述 |
|---------|---------|------|
| 用户管理 | `/api/v1/user` | JWT 认证、角色权限控制 |
| 発识空间 | `/api/v1/spaces` | 文档管理、向量检索、多策略搜索 |
| 智能问答 | `/api/v1/qa` | 多模型对话、会话管理 |
| AI 聊天 | `/api/v1/ai-chat` | 实时 AI 对话 |
| 深度研究 | `/api/v1/deep-research` | 多源搜索、研究报告生成 |
| 会话配置 | `/api/v1/qa/session-configs` | 会话配置管理 |
| 知识库管理 | `/api/v1/spaces/{space_id}/knowledge-bases` | 琜索知识库文档 |
 `/api/v1/spaces/{space_id}/search` | 搜索接口（含 kb_id 校验) |
| 文档管理 | `/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/documents` | 文档上传下载 |
| 成员管理 | `/api/v1/spaces/{space_id}/members` | 琜索接口(含 kb_id 校验) |
| 知识库测评 | `/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation` | 测试集管理、自动化测评、人工评分 |
| Agent 智能体 | `/api/v1/agent` | MCP Server 扩展、代码沙箱、多轮工具调用 |
| 技能广场 | `/api/v1/skills` | 技能上传、审核、安装、市场浏览 |
| 应用中心 | `/api/v1/apps` | AI 应用（简历挖掘等） |

---

## 技术栈

| 类别 | 技术 |
|-----|------|
| **框架** | FastAPI 0.128+, Python 3.12+ |
| **ORM** | SQLAlchemy 2.0 (async) |
| **数据库** | MySQL/MariaDB (aiomysql) |
| **缓存** | Redis (支持哨兵/集群模式) |
| **搜索** | Elasticsearch |
| **存储** | MinIO |
| **向量存储** | Elasticsearch (向量检索) |
| **LLM** | OpenAI 兼容接口（智谱AI、阿里云等） |
| **认证** | JWT + Argon2 密码哈希 |
| **日志** | structlog |
| **验证** | Pydantic v2 |

---

## 项目结构

```
src/
├── core/                    # 核心基础设施
│   ├── auth/               # 认证与安全
│   ├── database/           # 数据库配置
│   ├── middleware/         # 中间件、应用工厂、异常处理
│   └── security/           # 安全配置验证
│
├── features/               # 业务领域模块（DDD）
│   ├── user/               # 用户管理
│   ├── knowledge_space/    # 知识空间
│   ├── qa/                 # 智能问答
│   ├── deep_research/      # 深度研究
│   ├── evaluation/         # 知识库测评
│   ├── agent/              # Agent 智能体
│   ├── skill/              # 技能广场
│   └── app/                # 应用中心
│
├── setting/                # 配置管理
│   └── yaml_config/        # YAML 多环境配置
│
└── shared/                 # 跨领域共享组件
    ├── ai_models/          # LLM/Embedding 客户端
    ├── cache/              # Redis 缓存服务
    ├── clients/            # 客户端单例工厂
    ├── prompts/            # LLM 提示词模板
    ├── storage/            # MinIO、Elasticsearch 客户端
    └── utils/              # 文档处理、BM25 等工具
```

### 模块内部结构（DDD 分层）

```
src/features/{module}/
├── api/
│   ├── routes.py           # API 路由
│   ├── dependencies.py     # 依赖注入
│   ├── exceptions.py       # 异常类定义 ⚠️ 必须在此
│   ├── exception_handlers.py  # 异常处理器
│   └── startup.py          # 模块启动初始化
├── services/               # 业务逻辑层
├── repository/             # 数据访问层
├── models/                 # SQLAlchemy ORM 模型
└── schemas/                # Pydantic 数据模型
```

---

## 代码规范

### 命名规范

```python
# 类名：大驼峰
class UserService:

# 函数/方法：蛇形命名
async def get_user_by_id(user_id: int) -> User:

# 常量：全大写蛇形
MAX_RETRY_COUNT = 3

# 私有方法：单下划线前缀
def _validate_token(token: str) -> bool:
```

### 异步规范

```python
# 所有 I/O 操作必须使用 async/await
async def get_user(user_id: int) -> User:
    async with session.begin():
        user = await repository.find_by_id(user_id)
    return user
```

### 类型注解（必须）

```python
from typing import Optional, List

async def create_user(
    username: str,
    email: str,
    role: Optional[str] = None
) -> User:
    pass
```

### 异常处理

**异常类必须定义在 `api/exceptions.py` 中**：

```python
# api/exceptions.py

class ModuleError(Exception):
    """模块基础异常"""
    def __init__(self, message: str, code: str = "UNKNOWN_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class ResourceNotFoundError(ModuleError):
    """资源不存在"""
    def __init__(self, resource_id: int):
        super().__init__(
            message=f"资源 {resource_id} 不存在",
            code="RESOURCE_NOT_FOUND",
        )
        self.resource_id = resource_id
```

**异常命名规范**：

| 类型 | 格式 | 示例 |
|-----|------|------|
| 资源不存在 | `{Resource}NotFoundError` | `SpaceNotFoundError` |
| 资源已存在 | `{Resource}AlreadyExistsError` | `DocumentAlreadyExistsError` |
| 访问被拒绝 | `{Resource}AccessDeniedError` | `SpaceAccessDeniedError` |
| 操作无效 | `Cannot{Action}Error` | `CannotRemoveLastAdminError` |

### 日志规范

```python
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# 结构化日志
logger.info("用户登录成功", user_id=user.id, username=user.username)
logger.error("数据库连接失败", error=str(e))
```

---

## 配置管理

### 环境配置

配置文件位于 `src/setting/yaml_config/yaml/`：

- `default.yaml` - 默认配置（硬编码默认值，便于开发）
- `development.yaml` - 开发环境（硬编码覆盖）
- `production.yaml` - 生产环境（使用环境变量占位符）
- `testing.yaml` - 测试环境（硬编码覆盖）

### YAML 配置规范

**⚠️ 所有 YAML 配置文件（default/development/testing/production）中的值必须硬编码，严禁使用 `${VAR}` 环境变量占位符。**

- 所有配置值直接写在 YAML 文件中，不依赖 `.env` 或环境变量：
  ```yaml
  # ✅ 正确：硬编码
  api_key: "sk-xxxxx"
  password: "139790"
  host: localhost

  # ❌ 错误：环境变量占位符
  api_key: "${LLM_API_KEY}"
  password: "${DB_PASSWORD}"
  host: "${DB_HOST:localhost}"
  ```
- 新增配置项时，必须在 `default.yaml` 中提供硬编码默认值
- 不同环境的差异通过对应环境文件覆盖（如 `development.yaml` 覆盖 `default.yaml`）

### 启动方式

```bash
# 开发环境（默认）
python main.py

# 指定环境
python main.py --config production

# 完整参数
python main.py --config development --host 0.0.0.0 --port 8100 --reload
```

---

## 依赖注入

### 客户端单例工厂

```python
from src.shared.clients import (
    get_minio_client,
    get_elasticsearch_client,
    get_redis_client_async,
    get_embedding_client,
)

# 使用示例
minio = get_minio_client()
es = get_elasticsearch_client()
redis = await get_redis_client_async()
embedding = get_embedding_client()
```

### 服务层依赖注入

```python
# api/dependencies.py
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.features.knowledge_space.services.space_service import SpaceService

async def get_space_service(
    db: AsyncSession = Depends(get_db)
) -> SpaceService:
    return SpaceService(db)
```

---

## 安全规范

- 密码使用 Argon2 哈希
- JWT Token 有效期 30 分钟
- Token 黑名单存储在 Redis（支持多实例）
- 生产环境 MinIO 强制 SSL
- 所有用户输入必须通过 Pydantic 验证
