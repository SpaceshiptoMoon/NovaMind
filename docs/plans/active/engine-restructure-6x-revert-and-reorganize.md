# 引擎抽库方案变更：从独立 pip 包到 engines/ 目录分层

## 概述

本文档记录 NovaMind 引擎抽库重构的**方案变更**：废弃 `packages/` 独立 pip 包方案，改为 `backend/src/engines/` 内部目录分层。包含变更动机、6x 批次回退+重组的完整执行记录、最终架构、以及未来各子引擎迁移路线。

## 变更动机

### 原方案（批次 6b/6c，已回退）

引擎组件抽成独立 pip 包放在 `packages/` 下，经由 uv workspace 管理，host 通过 shim 挂回旧 `novamind.*` 路径：

```
packages/
  novamind-engine-core/        # pip 包: ai_models, storage, prompts, 端口
  novamind-rag-engine/         # pip 包: retrieval_engine, retrieval_port
backend/
  src/novamind/__init__.py     # shim: sys.modules 别名挂回
```

### 问题

1. **复杂度膨胀**：每个引擎需要独立 `pyproject.toml`、独立构建、独立版本管理——但引擎之间紧密耦合（如 `novamind-rag-engine` 依赖 `novamind-engine-core`），实际是内部模块而非可独立发布的库。
2. **shim 脆弱**：通过 `sys.modules` + `setattr` 别名保持双路径兼容，一旦出现模块加载顺序问题，`isinstance`/Protocol/ORM 枚举身份断裂，调试成本极高。
3. **开发体验差**：每次改动需要在 host 和 engine 包之间切换、`uv pip install -e` 重装、workspace 配置同步。
4. **用户判断**：「这些组件本质上还是项目内部的东西，不是真正的独立可发布产品，没必要上独立包那套重型基础设施。」

### 新方案（Option B）

引擎组件放在 `backend/src/engines/` 下，作为 `novamind.engines.*` 命名空间内的普通 Python 包：

- 无独立 `pyproject.toml`，共享 host 的构建配置
- 无 shim，`novamind.engines.rag` 直接经 `__path__` 扩展解析
- 依赖方向：`features → engines → shared`
- 引擎层只依赖 `shared`（ai_models/storage/prompts/端口），零 `features`/`setting`/`core` 导入

## 6x 批次执行记录

### 6x-1：回退 6b（novamind-engine-core 独立包）

**原始改动（commit `4559c58`）**：
- 创建 `packages/novamind-engine-core/`：独立 `pyproject.toml`、`src/novamind_engine_core/` 子包
- `git mv` 40+ 文件从 `backend/src/shared/` → `packages/novamind-engine-core/src/novamind_engine_core/`
- ~140 文件 import 前缀互换：`novamind.shared.{ai_models,storage,prompts,ports,utils.*}` → `novamind_engine_core.<同尾>`
- 新增 `novamind/__init__.py` shim（`_ENGINE_CORE_TAILS` + `_install_engine_core_aliases()`）
- 新增根 `pyproject.toml`（`[tool.uv.workspace] members=["backend","packages/*"]`）
- `backend/pyproject.toml` 新增 `"novamind-engine-core"` 依赖

**回退操作**：

| 步骤 | 操作 | 影响文件 |
|------|------|----------|
| 1 | 删除 `packages/novamind-engine-core/` | 整个目录树（~50 文件） |
| 2 | 删除根 `pyproject.toml` | uv workspace 配置 |
| 3 | 移除 `backend/pyproject.toml` 中 `novamind-engine-core` 依赖 | 1 行 |
| 4 | 复制 engine-core 文件回 `backend/src/shared/` | ai_models/、storage/、prompts/、10 端口、5 utils 叶 |
| 5 | 全仓 import 回退（binary-safe bytes.replace） | 141 个 .py 文件：`novamind_engine_core` → `novamind.shared` |
| 6 | 重写 `novamind/__init__.py` 为最小 `__path__` 扩展 | 移除所有 shim 代码 |
| 7 | 删除 `shared/utils/README.md`（6b 新增文档） | 1 文件 |

### 6x-2：回退 6c（novamind-rag-engine 独立包）

**原始改动（commit `1fd9f12`）**：
- 创建 `packages/novamind-rag-engine/`：独立 `pyproject.toml`、`src/novamind_rag/`
- `git mv` `retrieval_engine.py` + `retrieval_port.py` 从 `features/knowledge_space/services/` → `packages/`
- 9 文件 import 改写：`from novamind.features.*.retrieval_*` → `from novamind_rag import ...`
- `novamind/__init__.py` 新增 `_install_rag_engine_aliases()` shim
- 根 `pyproject.toml` 新增 `novamind-rag-engine` source
- `backend/pyproject.toml` 新增 `"novamind-rag-engine"` 依赖

**回退操作**：

| 步骤 | 操作 | 影响文件 |
|------|------|----------|
| 1 | 删除 `packages/novamind-rag-engine/` | 整个目录树 |
| 2 | 移除根 `pyproject.toml` 中 `novamind-rag-engine` source | 1 行 |
| 3 | 移除 `backend/pyproject.toml` 中 `novamind-rag-engine` 依赖 | 1 行 |
| 4 | 复制 `retrieval_engine.py` / `retrieval_port.py` 回 `features/knowledge_space/services/` | 2 文件 |
| 5 | 回退 9 个 host 文件 import 为原路径 | 6 src + 3 tests |
| 6 | 移除 `novamind/__init__.py` 中 rag shim 代码 | `_RAG_ENGINE_TAILS` + `_install_rag_engine_aliases()` |

### 6x-3：创建 engines/rag/ 并迁入 RAG 引擎

**新建文件**：

```
backend/src/engines/
  __init__.py               # 引擎层入口，规划注释（未来子引擎）
  rag/
    __init__.py              # 公共面导出：RetrievalEngine, RetrievalQuery, RetrievalResult, RetrievalPort
    retrieval_engine.py      # 纯检索引擎（从 features/knowledge_space/services/ 迁入）
    retrieval_port.py        # 检索端口协议（从 features/knowledge_space/services/ 迁入）
```

**engines/__init__.py** 内容：
```python
"""NovaMind 引擎——纯逻辑组件，不依赖宿主业务（鉴权/多租户/持久化/API 契约）。

引擎通过端口（Port）从宿主注入依赖，自身零 ``features`` / ``setting`` / ``core`` 导入。

目录规划：
  rag/          检索引擎（RetrievalEngine + RetrievalPort）
  agent/        Agent 引擎（未来）
  eval/         测评引擎（未来）
  knowledge/    知识处理引擎（未来）
  search/       外部搜索引擎（未来）
  resume/       简历解析引擎（未来）
  skill/        技能审查引擎（未来）
"""
```

**engines/rag/__init__.py** 内容：
```python
"""RAG 检索引擎——纯检索能力，通过端口从宿主注入依赖。

公共面：
  - ``RetrievalEngine`` — 纯检索引擎（``retrieve_raw``）
  - ``RetrievalQuery`` — 检索请求中立体（17 字段 slots dataclass）
  - ``RetrievalResult`` — 检索结果（results + cached）
  - ``RetrievalPort`` — 检索服务端口（消费方依赖此抽象）
"""
from novamind.engines.rag.retrieval_engine import (
    RetrievalEngine,
    RetrievalQuery,
    RetrievalResult,
)
from novamind.engines.rag.retrieval_port import RetrievalPort

__all__ = [
    "RetrievalEngine",
    "RetrievalQuery",
    "RetrievalResult",
    "RetrievalPort",
]
```

**Host 层 import 更新**（9 个文件）：

| 文件 | 旧 import | 新 import |
|------|-----------|-----------|
| `features/knowledge_space/services/search_service.py` | `from novamind.features.knowledge_space.services.retrieval_engine import ...` | `from novamind.engines.rag import RetrievalEngine, RetrievalQuery` |
| `features/knowledge_space/adapters/retrieval_adapter.py` | `from novamind.features.knowledge_space.services.retrieval_port import ...` | `from novamind.engines.rag import RetrievalPort` |
| `features/qa/services/ai_chat_service.py` | 同上（TYPE_CHECKING） | 同上 |
| `features/deep_research/services/deep_research_service.py` | 同上 | 同上 |
| `features/evaluation/services/evaluation_service.py` | 同上 | 同上 |
| `features/evaluation/api/dependencies.py` | 同上 | 同上 |
| `tests/test_retrieval_engine_seam.py` | 双路径各 import | `from novamind.engines.rag import ...` |
| `tests/test_search_cache_key_and_sanitize.py` | 旧路径 | 同上 |
| `tests/test_batch6a_seam_completion.py` | 旧路径 + 新增 `engines/rag/` 候选目录 | 同上 |

**测试适配**（`test_batch6a_seam_completion.py`）：
- `ENGINE_CANDIDATE_DIRS` 新增 `SRC / "engines" / "rag"`（确保 retrieval_engine/port 纳入候选扫描）
- `test_6a2_retrieval_engine_has_no_feature_exceptions_import` 路径改为 `SRC / "engines" / "rag" / "retrieval_engine.py"`
- `test_6a3_retrieval_port_has_no_search_schema_import` 路径改为 `SRC / "engines" / "rag" / "retrieval_port.py"`
- `test_6a3_retrieval_port_search_request_param_is_opaque` 同上
- `_own_feature` 恢复为原始版本（只处理 `features/<X>/` 前缀，engines/ 返回 None——正确，引擎不属于任何 feature）

## 最终架构

```
backend/src/
├── novamind/
│   └── __init__.py          # __path__ 扩展到 backend/src/，使 novamind.* 解析到各子目录
│
├── engines/                 # ★ 引擎层：纯逻辑组件，零 feature/setting/core 导入
│   ├── __init__.py           #   规划注释
│   └── rag/                 #   RAG 检索引擎
│       ├── __init__.py       #   公共面重导出
│       ├── retrieval_engine.py  # RetrievalEngine + RetrievalQuery + RetrievalResult
│       └── retrieval_port.py    # RetrievalPort (Protocol)
│
├── features/                # 宿主业务层：鉴权/多租户/持久化/API 契约
│   ├── knowledge_space/
│   │   ├── services/
│   │   │   └── search_service.py    # from novamind.engines.rag import ...
│   │   └── adapters/
│   │       └── retrieval_adapter.py # from novamind.engines.rag import ...
│   ├── qa/                  # 同上，消费 RetrievalPort
│   ├── deep_research/       # 同上
│   └── evaluation/          # 同上
│
└── shared/                  # 共享底座：被 engines 和 features 共同依赖
    ├── ai_models/           # BaseLLM/BaseEmbedding/BaseRerank + 具体实现
    ├── storage/             # ElasticsearchClient/MinioClient/IndexSchema/PathStrategy
    ├── prompts/             # PromptManager/PromptTemplate/sanitize
    ├── utils/               # 通用工具（crypto 留 host，heartbeat/redact 等迁入引擎）
    ├── engine_ports.py      # Logger/PromptProvider 协议
    ├── engine_config.py     # AudioConfig/DuckDuckGoSearchConfig/...
    ├── engine_logging.py    # StdLogger（stdlib logging 包装）
    ├── model_config_ports.py    # ModelConfigPort + ModelCredentials
    ├── knowledge_space_info_ports.py  # KnowledgeSpaceInfoPort
    ├── search_ports.py      # WebSearchPort/WebSearchResult
    ├── registry_ports.py    # AgentRegistryPort
    ├── cache_ports.py       # CachePort
    ├── rag_errors.py        # RagError/EmbeddingError/SearchError
    ├── skill_ports.py       # ReviewStatus
    ├── knowledge/           # 知识处理实现（document_processing/media_processing/deepdoc）
    ├── cache/               # 缓存（留 host）
    ├── clients/             # ClientFactory（留 host 做装配）
    └── mq/                  # 异步任务运行时（留 host）
```

### 依赖方向

```
┌────────────┐
│  features  │  ← 宿主业务（鉴权/多租户/API/编排/装配）
└─────┬──────┘
      │ depends on
      ▼
┌────────────┐
│  engines   │  ← 引擎（纯逻辑，端口注入）
└─────┬──────┘
      │ depends on
      ▼
┌────────────┐
│  shared    │  ← 共享底座（AI 模型/存储/端口协议/工具）
└────────────┘
```

关键规则：
- `engines/` 只 import `novamind.shared.*`，零 `novamind.features.*` / `novamind.setting.*` / `novamind.core.middleware.*`
- `features/` import `novamind.engines.*`（消费引擎）和 `novamind.shared.*`（消费底座）
- 装配/注入在 `features/*/api/dependencies.py` 完成——这是唯一允许构造具体类的位置

## 当前接缝状态

### 已完成的接缝（批次 0-5b，不受 6x 影响）

| 批次 | 接缝 | 状态 |
|------|------|------|
| 0 | PromptManager 注册表、PromptTemplate→字符串 | ✅ |
| 1 | Feature Manifest 系统（拓扑路由注册） | ✅ |
| 2 | RetrievalPort 切分（search_service → RetrievalEngine） | ✅ |
| 3 | Agent 引擎端口化（WebSearch/KnowledgeSearch/MemoryStore ports） | ✅ |
| 4 | StoragePort 配置注入（IndexSchema/PathStrategy/AudioConfig） | ✅ |
| 5a | eval/resume/skill/research 端口化铺开 | ✅ |
| 5b | ModelConfigPort 全量 DI + KnowledgeSpaceInfoPort | ✅ |
| 6a | Logger 注入 / CachePort / rag_errors / RetrievalPort 去 schema / skill 枚举下沉 / audio_utils 去 ClientFactory | ✅ |

### 已有的 125 接缝测试

| 测试文件 | 数量 | 守护不变式 |
|----------|------|-----------|
| `test_batch6a_seam_completion.py` | 14 | 6a-1~6a-5：零 structured_logging/redis_client/clients + 异常隔离/端口协议/审计枚举/audio_utils 注入 + 零跨 feature import |
| `test_retrieval_engine_seam.py` | 5 | session 隔离/缓存懒解析/协议满足 |
| `test_search_cache_key_and_sanitize.py` | 8 | 缓存键完整/无污染/prompt sanitize |
| `test_agent_engine_ports_seam.py` | 15 | Agent 工具端口注入/缺端口降级 |
| `test_batch4_storage_seam.py` | 11 | IndexSchema/PathStrategy/AudioConfig 零 setting import |
| `test_batch5_evaluation_seam.py` | 9 | 三 evaluator + claim_decomposer 零禁止 import |
| `test_batch5_resume_seam.py` | 13 | resume_parser/analyzer/probing 端口注入 |
| `test_batch5_skill_seam.py` | 12 | skill_checker/parser 端口注入 + AgentRegistryPort |
| `test_batch5b_model_config_seam.py` | 52 | ModelConfigPort 8 方法覆盖 / 13 服务层不 import 具体类 / 装配白名单 |

## 验证记录

### 6x-3 验证结果

| 阶段 | 命令/方法 | 结果 |
|------|-----------|------|
| py_compile | `py_compile` 全量 `src/*.py` | 531/531 通过 |
| lint | `ruff --select F --line-length 100` 改动的文件 | All checks passed |
| 接缝测试 | `pytest tests/test_*seam*.py` | **125 passed** |
| 单元测试 | `pytest --ignore=tests/test_*_api.py --ignore=tests/test_deepdoc_runtime.py` | **222 passed**, 10 failed 全预存（deepdoc CLI 路径、媒体样本缺失、ASR executor） |
| 启动冒烟 | `create_app()` + `app.openapi()` | **190 routes, 145 OpenAPI paths**——零路由变更，前端契约逐字不变 |

### 预存失败（非本批引入，已验证）

| 测试 | 原因 |
|------|------|
| `test_user_api.py`（19 error） | 需 PG/Redis 运行中服务器 |
| `test_ai_chat_db.py`（2 error） | 同上 |
| `test_evaluation_api.py`（部分 fail） | 同上 |
| `test_deep_research_api.py` | 同上 |
| `test_qa_api.py` | 同上 |
| `test_deepdoc_runtime.py` | pandas 未安装 |
| `test_deepdoc_cli.py` | deepdoc CLI 不在 PATH |
| `test_media_utils.py`（4 fail） | 媒体样本文件缺失 |
| `test_asr_executor_isolation.py`（1 fail） | MIN_AUDIO_SIZE 守卫致 32-byte fixture 被拒（已知 bug） |

## 未来计划

### 引擎迁移优先级

按依赖拓扑和业务重要性排列：

```
优先级 1（核心能力，最快迁移）:
  engines/agent/      ← features/agent/core/* + features/agent/mcp/*
                         已有完整的端口化（batch 3），AgentEngine/MemoryManager/Tools 均经端口注入
                         迁移代价：文件移动 + import 改写，内部零改动

优先级 2（搜索与知识处理）:
  engines/search/      ← features/deep_research/services/{duckduckgo,serpapi,tavily,external_search}_service.py
                         WebSearchPort 多实现，batch 5a 已配置注入
  engines/knowledge/   ← shared/knowledge/* (document_processing/media_processing/deepdoc)
                         ~20k 行最大子树，已有 logging_compat 兜底

优先级 3（测评与解析）:
  engines/eval/        ← features/evaluation/services/*_evaluator + claim_decomposer + test_set_parser
                         batch 5a 已端口注入
  engines/resume/      ← features/app/services/{resume_parser,resume_analyzer,resume_probing}.py
                         batch 5a 已端口注入
  engines/skill/       ← features/skill/services/{skill_parser,skill_checker}.py
                         batch 5a 已端口注入

优先級 4（共享底座收尾）:
  engines/shared/ (或留在 shared/)
    决定：shared/ 中的 ai_models/storage/prompts/utils 是否需要迁入 engines/
    还是保持现状（engines 和 features 共同依赖 shared）
    倾向：保持现状——shared 已是干净的底座层，无需二次迁移
```

### 每个子引擎迁移模板

以 `engines/rag/` 为范本，每个子引擎按以下步骤：

1. **创建目录**：`backend/src/engines/<name>/`
2. **创建 `__init__.py`**：重导出公共面
3. **移动文件**：从 feature 或 shared 迁入
4. **更新 host 层 import**：`from novamind.engines.<name> import ...`
5. **更新测试路径**：接缝测试 + 单元测试
6. **验证**：py_compile → ruff → pytest → create_app() openapi diff

### 不迁移的（永远留 host）

- `features/*/api/`（路由层）
- `features/*/repository/`（数据库访问）
- `features/*/models/`（ORM 模型）
- `features/*/schemas/`（请求/响应 Pydantic schema）
- `features/*/adapters/`（端口实现，桥接 host 与引擎）
- `shared/cache/`（缓存实现，host 装配）
- `shared/storage/`（ClientFactory，host 装配）
- `shared/mq/`（异步任务运行时）
- `core/`（框架/中间件/启动/数据库）
- `setting/`（配置系统）

## 关键教训

1. **Windows CRLF 陷阱**：`read_text()`/`write_text()` 在 Windows 下自动转换行尾符，导致全文件被 Git 标记改动（假 diff）。6b 和 6x 都用 `read_bytes()`/`write_bytes()` 做 `bytes.replace()` 解决。
2. **Edit 工具行尾符**：Edit 工具在 Windows 输出 LF，写入 CRLF 文件后整文件被标记改动。需要逐文件核对 HEAD blob 行尾并转换。
3. **接缝测试是生命线**：125 个接缝测试在回退 141 文件 import 改写中提供了即时反馈——任何 import 路径错误都能立刻定位。没有这层守护，6x 回退的可靠性和速度会大幅降低。
4. **openapi 生成是循环导入冒烟**：`create_app().openapi()` 会触发全部 import 链，是比 py_compile 更强的装配正确性验证，必须保留。

## 相关文档

- 引擎抽库原始计划：`C:\Users\xl\.claude\plans\refactored-dreaming-matsumoto.md`
- 进度记忆：`engine-extract-progress.md`
- 接缝测试：`backend/tests/test_*seam*.py`（8 个文件，125 测试）
- 引擎目录：`backend/src/engines/`
