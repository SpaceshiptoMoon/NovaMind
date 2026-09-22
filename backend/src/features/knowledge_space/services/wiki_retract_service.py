"""Wiki 来源回收（retract）——对齐 WeKnora cleanupWikiOnKnowledgeDelete 三步

源文档删除时 wiki 页面的联动处置：

1. **tombstone**：写 Redis 墓碑 ``wiki:deleted:{kb_id}:{document_id}``
   （TTL 1h > per-KB 锁 TTL 30min），防「删除 vs 生成中」竞态——
   ingest 任务在入口与 reduce 落库前各查一次，命中即放弃（不留
   幽灵 source_ref）；墓碑同时用于清理该文档的 pending ingest 语义。
2. **立即对账**（reconcile_document_removal，幂等）：反查引用该文档的
   页面——唯一来源页整体软删；多来源页剥掉该文档的 source_ref 与
   ``{document_id}_`` 前缀的 chunk_refs 后仅元数据更新（不动 version）。
3. **链接收尾**：对账后跑 finalize links（死链剔除 + in_links 双向对齐）。

异步兜底：删除入口同步对账一次 + 入队 arq retract 任务再跑一遍
（幂等，重试安全）。
"""

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.models.wiki import WikiPage
from novamind.features.knowledge_space.repository.wiki_repository import WikiPageRepository
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# tombstone TTL：须大于 per-KB 锁 TTL（1800s），保证生成中文档被删后
# 墓碑活到下一轮 ingest 检查点
WIKI_TOMBSTONE_TTL = 3600


def tombstone_key(kb_id: int, document_id: int) -> str:
    return f"wiki:deleted:{kb_id}:{document_id}"


async def write_tombstone(kb_id: int, document_id: int) -> bool:
    """写删除墓碑。Redis 不可用时返回 False（调用方降级为仅同步对账）。"""
    try:
        from novamind.shared.storage.client_factory import get_redis_client

        redis = await get_redis_client()
        raw = redis.redis_client
        await raw.set(tombstone_key(kb_id, document_id), "1", ex=WIKI_TOMBSTONE_TTL)
        return True
    except Exception as e:
        logger.warning("wiki tombstone 写入失败", kb_id=kb_id, document_id=document_id, error=str(e))
        return False


async def tombstone_exists(kb_id: int, document_id: int) -> bool:
    """ingest 管道检查点：该文档是否已被删除（删除竞态守卫）"""
    try:
        from novamind.shared.storage.client_factory import get_redis_client

        redis = await get_redis_client()
        raw = redis.redis_client
        val = await raw.get(tombstone_key(kb_id, document_id))
        return bool(val)
    except Exception:
        return False


def _source_ref_matches(page: WikiPage, document_id: int) -> bool:
    prefix = f"{document_id}|"
    return any(str(r).startswith(prefix) for r in (page.source_refs or []))


class WikiRetractService:
    """来源文档删除的 wiki 页面对账"""

    def __init__(self, session: AsyncSession, *, kb_id: int, space_id: int):
        self.session = session
        self.kb_id = kb_id
        self.space_id = space_id
        self.page_repo = WikiPageRepository(session)

    async def reconcile_document_removal(self, document_id: int) -> dict:
        """对账：唯一来源页软删、多来源页剥该文档引用。幂等可重试。

        返回 {deleted: [slug], stripped: [slug]}。
        """
        pages = await self.page_repo.list_by_source_document(self.kb_id, document_id)
        deleted: list[str] = []
        stripped: list[str] = []

        for page in pages:
            if not _source_ref_matches(page, document_id):
                continue  # 反查 LIKE 命中但实际无引用（防御）
            remaining = [
                r for r in (page.source_refs or [])
                if not str(r).startswith(f"{document_id}|")
            ]
            if not remaining:
                # 唯一来源：整页软删（对齐 WeKnora——留孤儿摘要页比删页更糟：
                # 模型还会链到它、read_source_doc 钻取必然失败）
                await self.page_repo.soft_delete_page(page)
                deleted.append(page.slug)
            else:
                # 多来源：剥本文档引用（source_ref 全剥 + chunk_refs 按前缀剥）
                page.source_refs = remaining
                prefix = f"{document_id}_"
                page.chunk_refs = [
                    r for r in (page.chunk_refs or [])
                    if not str(r).startswith(prefix)
                ]
                stripped.append(page.slug)

        await self.session.flush()

        if deleted or stripped:
            await self.page_repo.rebuild_links(self.kb_id)

        return {"deleted": deleted, "stripped": stripped}
