"""
KnowledgeSpaceInfoPort 宿主适配器，查询空间绑定信息。

供 ModelConfigService 在删除 embedding 模型前检查依赖，桥接 knowledge_space ORM。
"""
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
from novamind.features.user.ports import (
    KnowledgeSpaceInfoPort,
    SpaceEmbeddingUsage,
)


class HostKnowledgeSpaceInfoPort:
    """KnowledgeSpaceInfoPort 宿主实现：查 knowledge_space ORM。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def find_spaces_using_embedding_model(
        self, model_name: str
    ) -> List[SpaceEmbeddingUsage]:
        stmt = select(
            KnowledgeSpace.id, KnowledgeSpace.name, KnowledgeSpace.config
        ).where(KnowledgeSpace.deleted_at.is_(None))
        result = await self._db.execute(stmt)
        usages: List[SpaceEmbeddingUsage] = []
        for space_id, space_name, space_config in result.all():
            space_config = space_config or {}
            embedding_model = (space_config.get("embedding") or {}).get("model")
            if embedding_model == model_name:
                usages.append(SpaceEmbeddingUsage(space_id=space_id, space_name=space_name))
        return usages


def as_knowledge_space_info_port(db: AsyncSession) -> KnowledgeSpaceInfoPort:
    """构造 KnowledgeSpaceInfoPort 实例（供装配点注入 ModelConfigService）。"""
    return HostKnowledgeSpaceInfoPort(db)  # type: ignore[return-value]