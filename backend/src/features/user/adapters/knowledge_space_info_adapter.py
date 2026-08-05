"""KnowledgeSpaceInfoPort 宿主适配器（user feature）。

把 knowledge_space 的空间配置查询包成引擎端口 ``KnowledgeSpaceInfoPort``，供
``ModelConfigService._check_delete_impact`` 在删除 embedding 模型配置前查空间绑定，
不再直接 import ``knowledge_space.models.knowledge_space.KnowledgeSpace``（切断
``user.services → knowledge_space.models`` 反向依赖；:999 原内联 import 移到本 adapter
层，adapter 层允许跨 feature import）。

查询逻辑逐字迁自原 ``model_config_service._check_delete_impact:999`` 的 EMBEDDING 分支：
扫所有未删除空间，比对 ``space.config.embedding.model == model_name``。
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