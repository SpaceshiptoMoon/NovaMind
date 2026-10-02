# CLAUDE.md — 后端

## 概述

后端是 FastAPI 应用，采用面向 feature、偏 DDD（领域驱动设计）的结构。

入口：

- `main.py`
- `src/core/middleware/app_factory.py`
- `src/core/middleware/router_manager.py`
- `src/core/middleware/startup_manager.py`

## 多 Agent 并行开发

多个 agent 窗口并发操作本仓库时，每个必须在自己的 git worktree、自己的分支里运行——绝不在共享工作目录中工作。完整工作流见根 `CLAUDE.md` 与 `docs/multi-agent-parallel-development-workflow.md`。

后端专属要点：

- 按 feature 边界（`src/features/<domain>/`）拉分支；一个 agent 拥有一个 feature。
- 单点共享文件——`src/shared/prompts/`、`src/core/middleware/router_manager.py`、`src/core/middleware/startup_manager.py`、`*.example` 配置、DB 模型——同一时间只由一个 agent 编辑。
- 合并回主干前，先在 worktree 里跑 `pytest`（或针对性测试）。

## 目录结构

- `src/core/`：框架/运行时层
- `src/features/`：feature 模块
- `src/setting/`：配置系统与 YAML 资产
- `src/shared/`：可复用共享能力
- `tests/`：后端测试

## feature 模块契约

每个 feature 在适用处遵循以下结构：

- `api/`：仅 HTTP 层
- `services/`：业务逻辑与编排
- `repository/`：持久化访问
- `models/`：SQLAlchemy 模型
- `schemas/`：Pydantic schema

规则：

- 请求校验放 `schemas/`
- 路由处理器保持轻薄
- 事务敏感逻辑放 services
- 持久化查询放 repository 类，不散落在 services 里

## core 层规则

`src/core/` 只放应用运行时关注点：

- 中间件
- 认证与安全
- 应用启动/关闭
- db session 管理
- 横切基础设施

不要把 feature 业务逻辑放进 `core/`。

## shared 层规则

`src/shared/` 放跨 feature 可复用能力，不是杂物堆。

允许的类别：

- `shared/storage/`：外部服务客户端（ES/MinIO/Redis，经 `client_factory/`）
- `shared/search/`：外部搜索厂商客户端（tavily/serpapi/duckduckgo）
- `shared/cache/`：缓存访问
- `shared/mq/`：异步任务运行时
- `shared/prompts/`：共享 prompt
- `shared/utils/`：真正的通用辅助函数
- `shared/document/`：跨 feature 文档读取器与校验（真正跨 feature 复用）

只被一个 feature 使用、表达领域行为的代码，留在该 feature 内，不搬进 `shared/`。

## 知识库架构

权威归属：

- `src/features/knowledge_space/`：文档、KB 配置、任务、chunk 生命周期、API 的领域层（业务逻辑；解析/切分/多模态引擎在 `engines/document/`）
- `src/engines/document/pipeline/`：文档解析管道（DocumentLoader/DocumentProcessor/DocumentRegistry）——可复用的引擎层组件
- `src/engines/document/splitters/`：分块切分器（recursive/semantic/fixed/markdown）
- `src/engines/document/converters/`：文档格式转换器
- `src/engines/document/media/`：音频/视频/图像多模态处理（VLM/OCR/audio/video）
- `src/engines/document/integrations/deepdoc/`：DeepDoc 专有实现（vendored，自包含）
- `src/shared/document/readers/`：跨 feature 文档读取器（PDF/DOCX/TXT/HTML/MD）——被 app/qa/knowledge_space 复用
- `src/shared/document/validation/`：跨 feature 文件校验（FileInfo/FileValidator）——被 qa/knowledge_space 复用

不要在 `shared/document/` 与 `engines/document/` 两处重复实现解析逻辑。文档处理引擎（pipeline/splitters/converters/media/deepdoc）位于 `engines/document/`，是任何 feature 都可 import 的可复用组件（允许 `features → engines`）；`features/knowledge_space/` 只保留业务逻辑并通过端口编排引擎。只有真正跨 feature 的读取器与校验留在 `shared/document/`。

## import 规则

- 优先 `novamind...` 绝对 import
- 跨模块共享代码避免相对 import
- `__init__.py` 导出保持最少且有明确意图
- 常规包 import 能解决时，不依赖路径 hack

## 编码规则

- Python 3.12+
- 4 空格缩进
- 服务边界与共享层代码加类型标注
- 合理之处保持 async 代码端到端 async
- 抛领域语义的错误，而非泛化的 `Exception`
- 任务失败时（尤其解析与 MQ 工作流）记录足够的日志上下文

## import 依赖规则（硬规则，ragflow 务实单体风格）

R1–R6（详版见 `docs/plans/historical/REFACTOR-ragflow-style-migration.md` §1）：

- **R1 import 无环**：`features`/`engines`/`shared`/`setting`/`core` 之间允许任意方向 import（含 engines→features、core→features），但整个 `src/` 模块级 import 图（含函数内懒 import）必须无环。机器门禁：`tests/architecture/test_import_acyclic_gate.py`（AST 全图收集 + Tarjan SCC）。
- **R2 跨 feature 走公共面**：允许 import 对方 `services/` 公共类、`schemas/`、`models/` 中显式导出的枚举与行级只读访问；不 import 对方 `repository/` 内部、不下划线私有成员（机器门禁：`tests/architecture/test_no_cross_module_private_imports.py`）。**防环细则**：需要对方数据但对方 service 已依赖自己时，import 对方 `models/` 直查，不 import 对方 `services/`（典型：user ↔ knowledge_space）。
- **R3 全局中心清单**（只进不改，热点文件串行编辑）：`setting/` 的 `get_config()`、`shared/prompts/prompt_manager.py` 的 PromptManager、`shared/ai_models/` 模型客户端工厂、`shared/storage/client_factory.py`（ES/MinIO/Redis 单例）、`shared/search/external_search_service.py`（web 搜索唯一工厂）、`shared/mq/`。
- **R4 引擎不定义 Protocol 端口**：引擎需要宿主能力时直接收具体类实例（PromptManager/ModelConfigService 等）或普通参数传值；引擎 import features 具体类在 R1 下合法。
- **R5 工厂自注册**：模型客户端（llm/embedding/rerank/asr）与 web 搜索源用 `_FACTORY_NAME` 属性 + 模块扫描注册，消灭 if-else 供应商分支链。
- **R6 安全硬规则全部保留**：BaseAPIError 体系、`begin_nested()` SAVEPOINT、密钥加密、异步密码哈希、JWT 黑名单、FileValidator 魔数校验、参数化查询、路由手动注册、模块 init 注册。

## 测试规则

运行：

- `pytest`
- `pytest -m unit`
- `pytest -m "not slow"`

指引：

- 测试放 `backend/tests/`，按被测对象组织（见 `tests/README.md`）：
  - `tests/architecture/`：全局结构门禁与 API 契约快照
  - `tests/core/` / `tests/shared/` / `tests/engines/<x>/` / `tests/features/<x>/`：镜像被测模块所在的 `src/` 层
  - `tests/integration/`：标记 `integration`、需要 :8100 服务在跑的测试
- 为解析 bug 补针对性的回归测试
- 多模态样例文件：仓库根 `test_data/` 若本地存在（未跟踪约定，可能不存在）；否则夹具放 `tests/fixtures/`
- 修管道问题时，至少补一个能复现原始失败模式的测试

## 知识处理注意事项

- 文档解析配置与运行时配置的转换必须保持对齐
- 元数据不完整时，媒体解析应优雅降级
- DeepDoc 这类外部集成应隔离在共享适配层之后

## 修改后端代码时

- 先确认目标代码属于 `feature` 还是 `shared`
- 新增辅助函数前先查有无重复实现
- 改动了权威路径或架构指引时，同步更新文档
- 动了 import 就确认没留下第二条过期的 import 路径
