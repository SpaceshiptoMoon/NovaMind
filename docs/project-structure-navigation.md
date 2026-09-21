# 项目结构导航

## 总览

本仓库主要由以下部分组成：

- `backend/`：FastAPI 后端与领域业务代码
- `frontend/`：Vue 3 + TypeScript 前端
- `docs/`：设计文档、架构说明和历史记录
- `docker/`：Dockerfile、Nginx、Supervisord 和运行时配置模板
- `test_data/`：上传样例和测试数据

如果你是第一次阅读本项目，建议先看根目录 `README.md`，再回到本页定位代码。

## 顶层入口

| 路径 | 用途 |
| --- | --- |
| `README.md` | 项目总览、部署方式、模块地图 |
| `ROADMAP.md` | 当前阶段重点建设方向 |
| `backend/README.md` | 后端说明、运行方式、代码布局 |
| `frontend/README.md` | 前端说明、开发方式、页面结构 |
| `docs/README.md` | 文档导航和阅读顺序 |
| `docker-compose.yml` | 本地 Docker 编排入口 |
| `deploy.sh` / `deploy.ps1` | 一键部署脚本 |

## 后端

### 主要区域

- `backend/main.py`：后端入口
- `backend/src/core/`：应用工厂、生命周期、中间件、数据库、安全
- `backend/src/setting/`：YAML 配置加载和环境覆盖
- `backend/src/features/`：按领域拆分的业务模块
- `backend/src/engines/`：引擎层可复用组件（ragflow 风格：import 无环门禁 + 跨模块走公共面，无单向分层限制）
- `backend/src/shared/`：共享基础设施
- `backend/tests/`：后端自动化测试（按被测对象分层，见 `backend/tests/README.md`）

### 典型模块结构

大多数后端领域模块采用以下结构：

```text
api/
services/
repository/
models/
schemas/
```

### 重点后端领域

| 路径 | 内容 |
| --- | --- |
| `backend/src/features/user/` | 认证、用户、模型配置、RBAC、应用门禁 |
| `backend/src/features/knowledge_space/` | 空间、知识库、文档、成员、Wiki 生成与浏览 |
| `backend/src/features/evaluation/` | 知识库评测（测试集、评估任务、导出） |
| `backend/src/features/qa/` | 聊天和问答流程 |
| `backend/src/features/deep_research/` | 深度研究和报告生成 |
| `backend/src/features/agent/` | Agent、MCP 集成、工具编排 |
| `backend/src/features/skill/` | 技能广场和审核 |
| `backend/src/features/app/` | 应用中心（简历挖掘） |
| `backend/src/features/notification/` | 通知和偏好设置 |

### 引擎层（engines/）

R1/R4 下的可复用组件：可直接 import setting 配置与 feature 公共面，
features 直接收具体类实例（不再经端口装配）：

| 路径 | 内容 |
| --- | --- |
| `backend/src/engines/agent/` | Agent 引擎（ReAct 循环、工具、记忆、MCP、审批） |
| `backend/src/engines/document/` | 文档处理引擎（pipeline / splitters / converters / media / deepdoc） |
| `backend/src/engines/deep_research/` | 深度研究引擎 |
| `backend/src/engines/eval/` | 评测引擎（retrieval / generation / embedding / claim 评估器） |
| `backend/src/engines/rag/` | RAG 引擎（检索引擎、Grade→Retry） |
| `backend/src/engines/resume/` | 简历解析引擎 |

### 知识处理运行时代码

如果你在处理文档解析、切分、向量化或索引，优先看这里：

- `backend/src/features/knowledge_space/services/`：业务编排（管道入口、任务编排）
- `backend/src/engines/document/pipeline/`：解析管道（DocumentLoader / DocumentProcessor）
- `backend/src/engines/document/splitters/`：切分器
- `backend/src/engines/document/media/`：音频、视频、VLM、OCR 处理
- `backend/src/engines/document/integrations/deepdoc/`：DeepDoc（vendored，自包含）
- `backend/src/shared/document/`：跨 feature 读取器与文件校验
- `backend/src/shared/utils/`：通用工具

## 前端

### 主要区域

- `frontend/src/api/`：API 封装和请求辅助
- `frontend/src/components/`：复用 UI 组件
- `frontend/src/views/`：路由级页面
- `frontend/src/stores/`：Pinia 状态管理
- `frontend/src/router/`：路由定义和守卫
- `frontend/src/layouts/`：共享布局
- `frontend/src/utils/`：工具函数

### 按业务划分的前端区域

| 路径 | 内容 |
| --- | --- |
| `frontend/src/views/auth/` | 登录、忘记密码、重置密码 |
| `frontend/src/views/space/` | 空间、知识库、文档和配置流程 |
| `frontend/src/views/chat/` | 聊天工作区 |
| `frontend/src/views/agent/` | Agent 列表与聊天 |
| `frontend/src/views/research/` | 深度研究页面 |
| `frontend/src/views/skill/` | 技能广场和管理审核 |
| `frontend/src/views/app/` | 应用中心 |
| `frontend/src/views/user/` | 个人资料、模型、通知、用户管理 |

知识库相关 UI 主要集中在：

- `frontend/src/api/knowledge/`
- `frontend/src/components/knowledge/`
- `frontend/src/views/space/`

## 文档

文档树建议按以下方式理解：

- `docs/README.md`：文档总入口
- `docs/knowledge-space/`：知识空间文档，已区分 `current/` 和 `process/`
- `docs/knowledge-space/current/wiki-architecture.md`：Wiki 自动生成与浏览架构
- `docs/deepdoc/`：DeepDoc 集成说明
- `docs/notification-architecture.md`：通知系统架构（NotificationPort / WS 推送 / 轮询兜底）
- `docs/permission-architecture.md`：权限体系架构（认证 / 三级全局身份 / 应用门禁 / 空间角色）
- `docs/handover/`：交接记录，均已归档至 `historical/`
- `docs/plans/`：执行计划和重构方案，已区分 active / historical 阅读方式

如果你是公开仓库读者，优先从 `README.md` 和 `docs/README.md` 开始，而不是直接进入历史计划目录。
