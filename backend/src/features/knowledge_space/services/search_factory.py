"""SearchService 装配单一入口。

7 处构造点（FastAPI DI / worker / cron / 跨 feature 适配器）曾各自复制
「es_client 获取 + ModelConfigService 现构造 + Instrumented 包装选择」装配；
本工厂是唯一出处，es_client 缺省走 shared/storage/client_factory 单例。

放 services 层而非 api/dependencies：worker/cron 不能依赖 FastAPI 模块的
导入副作用（evaluation/standalone_factory.py 已示范同形态）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.storage.elasticsearch_client import ElasticsearchClient
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from novamind.engines.rag.retrieval_engine import RetrievalEngine
    from novamind.features.knowledge_space.services.search_service import SearchService


async def build_search_service(
    session: AsyncSession,
    *,
    es_client: ElasticsearchClient | None = None,
    model_config_service: ModelConfigService | None = None,
    instrumented: bool = True,
    retrieval_engine: RetrievalEngine | None = None,
) -> SearchService:
    """构造装配完成的检索服务。

    Args:
        session: DB 会话（请求级 get_db 或 worker 自管会话）。
        es_client: ES 客户端；None 时取 client_factory 单例。
        model_config_service: 模型配置服务；None 时按当前会话现构造。
        instrumented: True 返回带 kb-ops 埋点的 InstrumentedSearchService
            （用户触发的检索进事件账本）；False 返回裸 SearchService
            （后台重放/评测等非用户交互场景，不进账本）。
        retrieval_engine: 显式检索引擎（仅 FastAPI 权威装配点注入带
            RedisCache 的实例）；None 时 SearchService 内部惰性降级
            （LazyRedisCache，未装配时 no-op）。

    Returns:
        SearchService（或其 Instrumented 子类——纯继承透传，调用方无感）。
    """
    if es_client is None:
        from novamind.shared.storage.client_factory import get_elasticsearch_client

        es_client = await get_elasticsearch_client()
    if model_config_service is None:
        model_config_service = ModelConfigService(session)

    if instrumented:
        from novamind.features.knowledge_space.services.instrumented_search_service import (
            InstrumentedSearchService,
        )

        return InstrumentedSearchService(
            session=session,
            es_client=es_client,
            model_config_service=model_config_service,
            retrieval_engine=retrieval_engine,
        )
    from novamind.features.knowledge_space.services.search_service import SearchService

    return SearchService(
        session=session,
        es_client=es_client,
        model_config_service=model_config_service,
        retrieval_engine=retrieval_engine,
    )
