"""Wiki 页 ES 同步——对齐 WeKnora 的 wiki_page chunk 机制

wiki 页以 ``chunk_type="wiki_page"`` 文档同步进 ES 向量库参与检索：

- chunk_id 约定 ``wp-{page_id}``（对齐 WeKnora ``wp-`` 前缀）
- document_id 用哨兵 0（无真实文档归属；消费端按 chunk_type 分支展示，
  避免按 document_id 跳文档详情 404）
- content = title + summary + 正文（进 ES 全文与向量字段）
- KB 级 ``delete_by_query(kb_id)`` 天然覆盖 wiki 文档清理（无额外工作）

无 embedding 模型（space.embedding_config["dimension"] 缺失）时优雅跳过
并 warn——对齐 WeKnora chunkRepo 可空的「可装配」语义。
"""
from typing import Any

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

WIKI_CHUNK_TYPE = "wiki_page"
WIKI_CHUNK_ID_PREFIX = "wp-"


def wiki_chunk_id(page_id: str) -> str:
    return f"{WIKI_CHUNK_ID_PREFIX}{page_id}"


class WikiEsSyncService:
    """wiki 页 → ES 文档同步"""

    def __init__(self, session: Any, es_client: Any):
        self.session = session
        self.es = es_client

    async def _resolve_embedding_dim(self, space_id: int) -> int | None:
        """从 space.embedding_config 取维度；缺失返回 None（调用方跳过）"""
        from novamind.features.knowledge_space.repository.knowledge_space_repository import (
            KnowledgeSpaceRepository,
        )

        space = await KnowledgeSpaceRepository(self.session).get_by_id(space_id, use_cache=True)
        if not space:
            return None
        dim = (space.embedding_config or {}).get("dimension")
        return int(dim) if dim else None

    async def sync_page(self, space_id: int, page: Any, embedding: list | None = None) -> bool:
        """同步单个 wiki 页到 ES。

        Args:
            page: WikiPage ORM 对象
            embedding: 页面向量（调用方用空间 embedding 模型预生成）。
                缺失时跳过同步（可装配语义）。
        """
        content = (page.content or "").strip()
        if not content:
            return False
        dim = await self._resolve_embedding_dim(space_id)
        if not dim:
            logger.warning(
                "wiki ES 同步跳过：空间未配置 embedding 维度",
                space_id=space_id, slug=page.slug,
            )
            return False

        if not embedding:
            logger.warning(
                "wiki ES 同步跳过：页面无 embedding 向量",
                space_id=space_id, slug=page.slug,
            )
            return False

        doc = {
            "chunk_id": wiki_chunk_id(page.id),
            "chunk_type": WIKI_CHUNK_TYPE,
            # 哨兵：wiki 页不归属任何真实文档；消费端按 chunk_type 分支
            "document_id": 0,
            "chunk_index": 0,
            "kb_id": page.kb_id,
            "space_id": space_id,
            "content": f"{page.title}\n{page.summary or ''}\n{content}"[:32000],
            "embedding": embedding,
            "embedding_dim": dim,
            "questions": [],
            "metadata": {
                "wiki_slug": page.slug,
                "wiki_title": page.title,
                "wiki_page_type": page.page_type,
            },
            "file_info": {},
        }
        return await self.es.index_chunk(space_id, doc)

    async def delete_page(self, space_id: int, page_id: str) -> bool:
        """删除 wiki 页对应的 ES 文档"""
        try:
            return await self.es.delete_chunk(space_id, wiki_chunk_id(page_id))
        except Exception as e:
            logger.warning("wiki ES 文档删除失败", page_id=page_id, error=str(e))
            return False
