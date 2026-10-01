"""无请求依赖的 EvaluationService 装配工厂（kb-ops backlog）。

背景：EvaluationService 的标准装配走 FastAPI Depends（get_evaluation_service），
依赖请求级 session——后台 cron 无法复用。本工厂用全局 get_db_session 工厂 +
单例客户端（ES/MinIO）构造完全自持的服务实例，供质量基线 cron 等后台场景使用。

与 dependencies.get_evaluation_service 的差异：无请求级 db（所有 DB 访问经
service 内部 _session_factory 短会话）；retrieval_port 为 None（后台任务只用
retrieval_factory）。
"""
from __future__ import annotations

from typing import Any

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


async def build_standalone_evaluation_service() -> Any:
    """构造后台自持的 EvaluationService（不依赖任何请求上下文）。

    Returns:
        装配完整的 EvaluationService；ES/MinIO 不可用抛原异常（调用方决定降级）。
    """
    from novamind.core.database.database import get_db_session
    from novamind.features.evaluation.services.evaluation_service import EvaluationService
    from novamind.shared.storage.client_factory import (
        get_elasticsearch_client,
        get_minio_client,
    )

    es_client = await get_elasticsearch_client()
    minio_client = await get_minio_client()

    def retrieval_factory(session):
        from novamind.features.knowledge_space.services.search_service import SearchService
        from novamind.features.user.services.model_config_service import ModelConfigService

        return SearchService(
            session,
            es_client,
            ModelConfigService(session),
        )

    return EvaluationService(
        db=None,  # 后台场景无请求级会话；公开方法均走 _session_factory 短会话
        retrieval_port=None,
        model_config_service=None,
        minio_client=minio_client,
        retrieval_factory=retrieval_factory,
        session_factory=get_db_session,
    )
