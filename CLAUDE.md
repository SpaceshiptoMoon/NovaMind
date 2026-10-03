# CLAUDE.md

## 项目概述

NovaMind 是全栈智能知识库平台。

- `backend/`：FastAPI 后端，领域服务、解析管道、检索、AI 集成
- `frontend/`：Vue 3 + TypeScript 前端，工作台 UI、知识库 UI、智能体 UI
- `docs/`：架构、设计决策、重构计划、交接笔记
- `docker/`：容器构建与运行时资产

注意：`test_data/`（仓库根的文本/图像/音频/视频样例夹具目录）是一个约定，
不是被跟踪的目录——当前并不存在。添加大样例文件时在本地创建；
从 `backend/tests/` 经 `parents[N]` 引用它。

## 仓库布局

```text
backend/
frontend/
docs/
docker/
deploy.ps1
deploy.sh
docker-compose.yml
```

## 核心开发原则

- 模块归属清晰优先于顺手的 import。
- 业务逻辑放 feature services 内，不放路由处理器。
- 跨 feature 的共享能力放 `backend/src/shared/`，但仅限真正可复用的。
- 知识库解析、媒体处理、外部解析器集成统一归入 `backend/src/engines/document/`（pipeline/splitters/converters/media/integrations/deepdoc），作为可复用的引擎层组件；`features/knowledge_space/` 只保留业务逻辑（services/api/models/schemas/repository/tasks/adapters），经端口编排引擎。只有真正跨 feature 的文档读取器与校验留在 `backend/src/shared/document/`。
- 避免造重复的工具层。某能力已有权威归属时，扩展该归属，不在别处加第二套实现。
- 改 API 契约时，后端 schema、前端类型、文档三处同步更新。

## 通用补丁原则（用户硬性要求）

补丁必须是**通用性修复**，不得针对特定错误样例做特例化改动，也不得隐含当前 Windows 开发机（8GB 内存）的资源假设：

- **生产目标是 Linux + 资源充足的服务器**。开发机的低内存只是临时约束，禁止把它焊进代码：内存上限、zoom/DPI/尺寸降档、批大小、线程数等资源类决策不得为"省开发机内存"而硬编码降质。确需保守默认值时必须环境变量/YAML 配置化，并在 `.env.example` 或 YAML 模板中暴露。
- **判据从第一性原理出发**（几何/统计/语义通用规则：面积比、密度阈值、坐标系不变量、排版常识），实测案例（doc5xx 等）只能当**验证**，不能当判据来源。magic number 要么有上游同款依据，要么在注释里写明推导或量级依据。
- **失败方向必须安全**：修复路径的退化行为优先选择"能力缺失"（无坐标、不挂载、不合成、告警跳过）而非"错误结果"（误删、错挂、内容丢失）。
- **平台通用**：不为 Windows 特有行为（GBK 控制台、路径分隔符、Docker Desktop 挂载权限）写无兜底的平台分支；涉及编码、路径、权限的代码在 Linux 生产语义下必须正确，开发机行为不得反向污染生产路径。
- **国内网络便利不得变默认耦合**：镜像源、时区等只允许出现在部署配置（`.env.example`/deploy 脚本/compose 注入），功能代码零硬编码；默认值面向通用环境。
- 每次修复优先补一条**正反两用例**的回归测试（触发场景 + 相邻正常场景不误伤），防止案例特例化漂移。

## 多 Agent 并行开发

多个 agent 窗口（或开发者）并发操作本仓库时，每个隔离在自己的 git worktree、自己的分支里。绝不让多个 agent 编辑同一工作目录——重叠修改会在 git 介入之前就被文件系统层静默覆盖，且无法恢复或归因。

- **一个 agent = 一个 worktree = 一个分支。** 启动时创建：`git worktree add ../intelligent-<scope> -b feat/<scope>-<desc>`，然后在其内工作；或让 Claude Code 用内置命令创建 worktree。
- **worktree 放在仓库外**（不要放 `src/`、`backend/` 或其他被扫描的源码目录内）。从干净基线（`main` 或当前主干）拉分支——另一工作目录的未提交修改不会带过来，这正是隔离的意义。
- **按 feature 边界**（`backend/src/features/<domain>/`）划分任务。单点共享文件同一时间只能由一个 agent 编辑；其余排队：
  - `backend/src/shared/prompts/`（prompt 注册表）
  - `backend/src/features/*/manifest.py`（feature 路由/init/依赖声明，见硬规则）
  - `backend/src/core/middleware/router_manager.py` 与 `startup_manager.py`（manifest 聚合与启动编排）
  - `*.example` 配置模板、`CLAUDE.md`、`docs/` 架构文档、DB 模型
- **频繁且原子地提交。** 不要把未提交修改留过夜；停工前 commit 或 stash。
- **从干净主干合并回来：** `git checkout main` → `git merge feat/<scope>-<desc>`。每次合并后、开始下一项前跑相关测试。
- **合并后清理：** `git worktree remove ../intelligent-<scope>` + `git branch -d feat/<scope>-<desc>` + `git worktree prune`。
- **主工作目录只用于集成合并与主干同步**，不作为任何 agent 的开发工作区。

完整工作流与冲突解决指引见 `docs/multi-agent-parallel-development-workflow.md`。

## 后端结构

后端主要区域：

- `backend/main.py`：后端入口
- `backend/src/core/`：应用工厂、中间件、生命周期、数据库、安全、共享运行时基础设施
- `backend/src/features/`：面向 feature 的领域模块
- `backend/src/setting/`：配置加载与 YAML 配置资产
- `backend/src/shared/`：可复用共享能力，包括 `ai_models/`、`cache/`、`mq/`、`storage/`（含 `client_factory/`：ES/MinIO/Redis 客户端工厂）, `prompts/`, `utils/`, `document/`

### `novamind` import 根（兼容性垫片）

`backend/src/novamind/__init__.py` 是兼容性包，通过扩展 `__path__` 使 `novamind.core.*`、`novamind.features.*`、`novamind.shared.*`、`novamind.setting.*` 分别解析到 `backend/src/core/`、`backend/src/features/`、`backend/src/shared/`、`backend/src/setting/`。`backend/src/novamind/` 下没有真实代码——始终用 `novamind.<area>...` 绝对路径 import，实际实现去 `backend/src/<area>/` 下找。

feature 模块按以下结构组织：

- `api/`：FastAPI 路由层。也承载 feature 本地的接线类（非业务逻辑）辅助文件：`../manifest.py`（feature 的路由/init/依赖声明，`RouterSpec` + `init_hook` + `models_loader`）、`exception_handlers.py`（经 `register_module_exceptions` 注册 feature 专属异常处理器）、`dependencies.py`（FastAPI 依赖）；部分 feature 另有 `startup.py`（由 manifest 的 `init_hook` 调用的组件装配函数）。feature 专属 `BaseAPIError` 子类放 feature 顶层 `exceptions.py`。业务逻辑不进这些文件。
- `services/`：业务工作流与编排
- `repository/`：数据库访问
- `models/`：ORM 模型
- `schemas/`：请求/响应与内部 Pydantic 模型
- `prompts/`（可选）：feature 本地 prompt 模板。跨 feature 可复用的 prompt 用 `shared/prompts/`；只有当 prompt 为该 feature 专属、不预期被别处复用时，才用 feature 本地 `prompts/`（或顶层 `<feature>_prompts.py`）。

## 前端结构

前端主要区域：

- `frontend/src/api/`：按领域分组的 API 客户端
- `frontend/src/components/`：按领域分组的可复用 UI 组件
- `frontend/src/views/`：路由级页面
- `frontend/src/stores/`：Pinia store
- `frontend/src/router/`：路由注册
- `frontend/src/layouts/`：应用外壳
- `frontend/src/composables/`：可复用的组合式 API composable
- `frontend/src/utils/`：前端通用辅助函数
- `frontend/src/types/`：共享 TS 类型

知识库 UI 应集中在：

- `frontend/src/api/knowledge/`
- `frontend/src/components/knowledge/`
- `frontend/src/views/space/`

## 知识库权威归属

知识库相关代码使用以下权威位置：

- `backend/src/features/knowledge_space/`：知识库领域行为、任务、API、schema、repository
- `backend/src/engines/document/pipeline/`：文本与文档解析管道（DocumentLoader/DocumentProcessor）——可复用的文档处理引擎
- `backend/src/engines/document/splitters/`：分块切分器
- `backend/src/engines/document/converters/`：文档格式转换器
- `backend/src/engines/document/media/`：音频、视频、OCR、VLM 与多模态处理。注意：`media/image/` 目前是占位（只有 `__init__.py`）；实际图像理解在 `media/vlm/` 与 DeepDoc 的 `integrations/deepdoc/vision/`，图像 embedding 走 VLM 描述 + 文本 embedding（见 multimodal-embedding 记忆）。不要假设 `image/` 里有图像处理逻辑。
- `backend/src/engines/document/integrations/deepdoc/`：仅 DeepDoc 集成（vendored，自包含）
- `backend/src/shared/document/readers/`：跨 feature 文档读取器（PDF/DOCX/TXT/HTML/MD）——被 app/qa/knowledge_space 复用
- `backend/src/shared/document/validation/`：跨 feature 文件校验——被 qa/knowledge_space 复用

非知识库专属的通用辅助函数归属：

`backend/src/shared/utils/`

`shared/utils/` 只放真正通用的工具：时间、加解密、脱敏、心跳、真正通用的文本辅助等。不应成为解析器逻辑、媒体工作流、厂商集成的第二归宿。

## 编码规范

### Python

- Python 3.12+
- 4 空格缩进
- 函数、模块、变量用 `snake_case`
- 类用 `PascalCase`
- async 边界保持显式
- 优先 `novamind...` 绝对 import
- 不要把副作用藏进工具函数

### 注释与文档字符串规范（PEP 257 / PEP 8 / Google 风格）

注释、docstring 一律用中文；标识符、关键字用英文。存量代码 reST（`:param:`）与 Google（`Args:`）两套方言混用，**存量不动，新代码统一 Google 风格**。

**模块 docstring**（文件第一条语句）：一句话定位（是什么层/组件）+ 可选的关键约束（调用前提、不做什么、格式契约），三行以内最理想。简短模块单行即可。禁止写入 `# -*- coding: utf-8 -*-`（Py3 默认）、`@author`/`Created on`/`@version`（归属和时间是 git 的职责）、复述文件路径。范例：

```python
"""
AES 加解密工具

当前版本：AES-256-GCM + HKDF-SHA256 密钥派生（v2）。
向后兼容：可解密旧版 AES-256-CBC + SHA-256 派生加密的数据（无前缀旧格式）。
"""
```

**函数/类 docstring**（Google 风格）：第一行单句祈使式摘要、句号结尾；签名有类型标注时 docstring 不重复类型；参数说明写业务含义与约束，不复述参数名；`Raises:` 列业务异常类名；私有方法（`_` 前缀）一行摘要即可。范例：

```python
def merge(self, chunks: list[Chunk], min_size: int = 200) -> list[Chunk]:
    """合并过小的相邻分块。

    Args:
        chunks: 待合并的分块列表，须已按阅读顺序排列。
        min_size: 最小块大小阈值，0 表示禁用合并。

    Returns:
        合并后的分块列表，doc_id 按新顺序重新编号。

    Raises:
        ValueError: 当存在页码缺失的分块时。
    """
```

**行内 `#` 注释**：只解释「为什么」（代码看不出的动机、坑、约束），不复述代码在做什么；注释与代码矛盾比没有注释更糟，改代码必须同步改注释。

**TypeScript/Vue**：用 TSDoc（`/** ... */` + `@param`/`@returns`），类型写在签名里不重复。

### TypeScript / Vue

- 2 空格缩进
- Vue 组件与路由页面用 `PascalCase`
- store、composable、辅助函数用 `camelCase`
- API 类型靠近 API 模块
- props 与 emit 事件优先显式类型
- 页面编排放 view，可复用展示放 component

## 验证工作流

### 后端

- 安装依赖：`cd backend && uv sync --extra test --extra dev`（项目统一用 uv，不用 pip/poetry；core 运行时依赖齐全，test/dev 为开发测试 extras。公式模型 INT8 量化等部署增强见 pyproject `deepdoc-vision` extra）
- 开发服务器：`python main.py --reload`
- 跑测试：`pytest`
- 触碰解析、文档任务、检索或共享基础设施时，优先跑针对性测试

### 前端

- 安装：`cd frontend && npm install`
- 开发服务器：`npm run dev`
- 类型检查：`npm run type-check`
- Lint：`npm run lint`
- 格式化：`npm run format`
- 构建：`npm run build`

## 变更规则

- 不随意移动文件；除非确有结构性修复，保持稳定的 import 边界。
- 没有充分理由不新增顶层目录。
- 重组目录时，文档与 import 路径在同一变更中更新。
- 解析管道改动，运行时代码与样例夹具都要验证（仓库根 `test_data/` 存在则用之，否则 `backend/tests/fixtures/`）。
- 知识库配置改动，后端 schema、前端表单、持久化配置结构三者保持对齐。

## 硬规则

以下为不可协商项，优先级高于便利性，也高于上文任何较软的规则。

### 禁止事项

- **禁止提交密钥。** `.env`、`*.yaml` 配置文件、API key、密码不得提交进 Git。
- **禁止用 `--no-verify` 绕过 Git hook。** hook 失败就修根因。
- **部署密码禁止弱值。** deploy 脚本随机生成四类字符密码；启动期安全诊断（弱密钥/占位符/通配 CORS）只告警不阻断——单一模式，无环境名门控（2026-10 起）。
- **禁止硬编码凭据。** 一切配置走 YAML + 环境变量。

### 后端编码规则

- **异常：** 所有业务异常继承 `BaseAPIError` 并在 feature 的 `api/exception_handlers.py` 经 `register_module_exceptions` 注册（异常类本体放 feature 顶层 `exceptions.py`）。绝不直接 `raise HTTPException`。HTTP 状态码解析只认异常类**自身** `__dict__` 里显式声明的 `http_status_code`（`__dict__.get` 不沿 MRO 查找），未声明时按 `status_map` 注册值或 error_code 后缀映射兜底——不要依赖 getattr 继承链（会命中基类 500 遮蔽 status_map，历史三次同根因 bug：6a0bd00、fa794b8、cbba9f9；门禁 `tests/core/test_error_handler_status_map.py`）。
- **数据库写入：** repository 写操作必须用 `begin_nested()`（SAVEPOINT）。绝不直接 commit。
- **API key 存储：** 用 `encrypt_api_key_async` / `decrypt_api_key_async`。绝不存明文。
- **密码哈希：** 用 `verify_password_async` / `get_password_hash_async`。绝不用同步哈希阻塞事件循环。
- **Pydantic schema：** 新 schema 优先 `*Base → *Create/*Update → *Response` 分层，且 `*Response` 必须设 `from_attributes=True`。存量 schema 未完全对齐该模式——例如 `knowledge_space` 的 schema（`SpaceCreate`、`DocumentResponse`、`ChunkResponse`）直接继承 `BaseModel`，没有 `*Base`。触碰这些文件时可局部对齐，但不要把存量缺 `*Base` 当成必须全量重构的违规。
- **路由注册：** 新路由在所属 feature 的 `manifest.py` 里以 `RouterSpec` 声明（含前缀与 `route_order`）；`manifest_loader` 自动扫描 `features/*/manifest.py`，`router_manager.py` 按声明聚合挂载——不存在也不需要 router_manager 手动登记。
- **模块 init：** 新模块建 `manifest.py` 提供 `manifest()`（`FeatureManifest`：routers/`depends_on`/`init_hook`/`models_loader`）；ORM 建表经 `models_loader` 导入模型，启动钩子经 `init_hook`，由 `startup_manager` 按 `get_sorted_manifests()` 顺序驱动。
- **配置文件：** 所有 `*.yaml` 都被 gitignore；只提交 `*.example` 模板。
- **import 依赖规则（ragflow 务实单体风格）：** 分层间允许任意方向 import（含 engines→features、core→features），硬约束是整个 `src/` import 图**无环**（Tarjan SCC 门禁 `test_import_acyclic_gate.py`）+ 跨 feature 只走对方公共面（services 公共类/schemas/models，禁 repository 内部与下划线私有，门禁 `test_no_cross_module_private_imports.py`）。防环细则：需要对方数据但对方 service 已依赖自己时，import 对方 models 直查而非 services。规则全文 R1–R6 见 `backend/CLAUDE.md`。

### 前端编码规则

- **组件：** 一律 `<script setup lang="ts">` + 组合式 API。
- **API 调用：** 用 `request.get<T>()` 这类带类型方法。禁止裸 `axios` 调用。
- **SSE 流式：** 用 `createSSEStream()` + `AbortController`。SSE 不用 Axios。
- **状态管理：** 用 Pinia store。跨组件状态不放组件内管理。
- **类型：** API 类型统一放 `api/types.ts`，经 `types/index.ts` 再导出。
- **View 命名：** `PascalCase` + `View` 后缀，放 `views/{domain}/` 下。

### 安全规则

- **认证：** 所有需认证路由用 `Depends(get_current_user)`；管理路由加 `Depends(require_admin)`。
- **Token 管理：** JWT 黑名单放 Redis。登出/禁用/删除用户时清掉全部关联 token。
- **输入校验：** 用户输入一律经 Pydantic schema 校验。路由层不做手工校验。
- **文件上传：** 类型与魔数经 `FileValidator` 校验。不只依赖扩展名。
- **SQL 注入：** 用参数化 SQLAlchemy ORM 查询。绝不拼接 SQL 字符串。

## 重要文档

- `docs/project-structure-navigation.md`
- `docs/knowledge-space/current/knowledge-architecture-navigation.md`
- `docs/knowledge-space/current/knowledge-config-structure-design.md`
- `docs/knowledge-space/current/wiki-architecture.md`
- `docs/multi-agent-parallel-development-workflow.md`
- `docs/transaction-boundary-conventions.md` — repository 写操作 `begin_nested()` SAVEPOINT 规则的权威出处
