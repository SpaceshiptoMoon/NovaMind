# novamind-engine-core

NovaMind 引擎共享底座——从 NovaMind 后端抽出的可嵌入独立库。

本包承载引擎层共享能力，**零宿主依赖**（不 import `novamind.setting` / `novamind.features.*` /
`novamind.core.middleware`），只依赖自定端口协议与第三方库。宿主 NovaMind 在上层包业务
（鉴权、多租户、持久化、API 契约），通过实现端口协议把能力注入引擎。

## 内容

- `ai_models/`：LLM / Embedding / Rerank 多协议客户端（OpenAI 兼容 / Anthropic / Ollama /
  Transformers）与基类 `BaseLLM` / `BaseEmbedding` / `BaseRerank`。
- `storage/`：Elasticsearch 与 MinIO 客户端封装 + `IndexSchema` / `PathStrategy` 端口。
- `prompts/`：纯注册表 `PromptManager` + 模板枚举 `PromptTemplate` + 消毒器。
- `utils/`：通用工具（`heartbeat` / `redact` / `ansi_strip` / `time_utils` / `text_utils`）。
  注：`crypto`（依赖宿主 `setting`）不在此包，留宿主。
- 端口协议：`engine_ports`（`Logger` / `PromptProvider` / `FallbackLLMProvider`）、
  `model_config_ports`、`knowledge_space_info_ports`、`search_ports`、`registry_ports`、
  `cache_ports`、`rag_errors`、`skill_ports`、`engine_config`、`engine_logging`。

## 嵌入

```python
from novamind_engine_core import (
    BaseLLM,
    Logger,
    ModelConfigPort,
    get_logger,
    ReviewStatus,
    MinioClient,
    PromptManager,
)
```

引擎库用 stdlib `logging`（经 `engine_logging.get_logger`，structlog 可用时优先），由嵌入方
配置 handler；不依赖宿主日志框架。