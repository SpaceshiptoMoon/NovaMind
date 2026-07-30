"""novamind-engine-core —— NovaMind 引擎共享底座。

本包从 NovaMind 后端抽出，零宿主依赖（不 import `novamind.setting` / `novamind.features.*` /
`novamind.core.middleware`）。宿主 NovaMind 在上层包业务（鉴权、多租户、持久化、API 契约），
通过实现本包的端口协议把能力注入引擎。

公共面分组：
  - 端口协议：`Logger` / `PromptProvider` / `FallbackLLMProvider` / `ModelConfigPort` /
    `KnowledgeSpaceInfoPort` / `WebSearchPort` / `AgentRegistryPort` / `CachePort`
  - 引擎自用配置：`AudioConfig` / `DuckDuckGoSearchConfig` / `SerpApiSearchConfig` /
    `TavilySearchConfig`
  - 中立异常与枚举：`RagError` / `EmbeddingError` / `SearchError` / `ReviewStatus`
  - 日志：`get_logger` / `StdLogger`
  - AI 客户端：`BaseLLM` / `BaseEmbedding` / `BaseRerank` 及各协议具体实现 + 工厂
  - 存储：`MinioClient` / `ElasticsearchClient` / `IndexSchema` / `DefaultIndexSchema` /
    `PathStrategy` / `DefaultPathStrategy`
  - 提示词：`PromptManager` / `PromptTemplate` / `get_prompt` / `format_prompt`
  - 数据类：`ModelCredentials` / `SpaceEmbeddingUsage` / `WebSearchResult` / `AgentSummary`
"""
from __future__ import annotations

# ---- 端口协议与中立数据 ----
from novamind_engine_core.engine_ports import FallbackLLMProvider, Logger, PromptProvider
from novamind_engine_core.engine_config import (
    AudioConfig,
    DuckDuckGoSearchConfig,
    SerpApiSearchConfig,
    TavilySearchConfig,
)
from novamind_engine_core.engine_logging import StdLogger, get_logger
from novamind_engine_core.model_config_ports import ModelConfigPort, ModelCredentials
from novamind_engine_core.knowledge_space_info_ports import (
    KnowledgeSpaceInfoPort,
    SpaceEmbeddingUsage,
)
from novamind_engine_core.search_ports import WebSearchPort, WebSearchResult
from novamind_engine_core.registry_ports import AgentRegistryPort, AgentSummary
from novamind_engine_core.cache_ports import CachePort
from novamind_engine_core.rag_errors import EmbeddingError, RagError, SearchError
from novamind_engine_core.skill_ports import ReviewStatus

# ---- AI 客户端 ----
from novamind_engine_core.ai_models import (
    BaseEmbedding,
    BaseLLM,
    BaseRerank,
    OpenAICompatibleEmbedding,
    OpenAICompatibleLLM,
    AnthropicLLM,
    OllamaLLM,
    TransformersLLM,
    OllamaEmbedding,
    TransformersEmbedding,
    CompatibleRerankClient,
    TransformersRerankClient,
)
from novamind_engine_core.ai_models.llm import create_llm_client
from novamind_engine_core.ai_models.embedding import create_embedding_client
from novamind_engine_core.ai_models.rerank import create_rerank_client

# ---- 存储 ----
from novamind_engine_core.storage import ElasticsearchClient, MinioClient
from novamind_engine_core.storage.index_schema import (
    DefaultIndexSchema,
    IndexFieldNames,
    IndexSchema,
)
from novamind_engine_core.storage.path_strategy import DefaultPathStrategy, PathStrategy

# ---- 提示词 ----
from novamind_engine_core.prompts import (
    PromptManager,
    PromptTemplate,
    format_prompt,
    get_prompt,
)

__all__ = [
    # 端口协议
    "Logger",
    "PromptProvider",
    "FallbackLLMProvider",
    "ModelConfigPort",
    "KnowledgeSpaceInfoPort",
    "WebSearchPort",
    "AgentRegistryPort",
    "CachePort",
    # 引擎自用配置
    "AudioConfig",
    "DuckDuckGoSearchConfig",
    "SerpApiSearchConfig",
    "TavilySearchConfig",
    # 中立异常与枚举
    "RagError",
    "EmbeddingError",
    "SearchError",
    "ReviewStatus",
    # 日志
    "get_logger",
    "StdLogger",
    # AI 客户端
    "BaseLLM",
    "BaseEmbedding",
    "BaseRerank",
    "OpenAICompatibleLLM",
    "AnthropicLLM",
    "OllamaLLM",
    "TransformersLLM",
    "OpenAICompatibleEmbedding",
    "OllamaEmbedding",
    "TransformersEmbedding",
    "CompatibleRerankClient",
    "TransformersRerankClient",
    "create_llm_client",
    "create_embedding_client",
    "create_rerank_client",
    # 存储
    "ElasticsearchClient",
    "MinioClient",
    "IndexSchema",
    "DefaultIndexSchema",
    "IndexFieldNames",
    "PathStrategy",
    "DefaultPathStrategy",
    # 提示词
    "PromptManager",
    "PromptTemplate",
    "get_prompt",
    "format_prompt",
    # 数据类
    "ModelCredentials",
    "SpaceEmbeddingUsage",
    "WebSearchResult",
    "AgentSummary",
]