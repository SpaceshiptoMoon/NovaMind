"""
SearchConfigPort 宿主适配器，构造 SearchConfigService 并以端口暴露。

对齐 ``as_knowledge_space_info_port`` 模式：解开 features/qa → features/user 的直接依赖，
消费方（AIChatService）经 ``SearchConfigPort`` 注入，不直接 import features/user 服务。
"""
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.user.services.search_config_service import SearchConfigService
from novamind.shared.search_config_ports import SearchConfigPort


def as_search_config_port(db: AsyncSession) -> SearchConfigPort:
    """构造 SearchConfigPort 实例（供 qa 装配点注入 AIChatService）。"""
    return SearchConfigService(db)  # type: ignore[return-value]


__all__ = ["as_search_config_port"]