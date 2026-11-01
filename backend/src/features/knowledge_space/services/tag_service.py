"""文档标签服务：用户自定义业务标签的规范化、持久化与 ES chunk 同步。

标签打在文档级（``documents.tags``），chunk 落 ES 时由解析尾段冗余到
``metadata.doc_tags``（写入时打标原则）；手动改标经 update_by_query 即时同步
全部分块，重解析时由解析尾段从文档行回填，两条写路径都不丢标签。

失败方向安全语义对齐 lifecycle_service：ES 同步失败回滚 DB 标签——宁可检索
面暂时保持旧标签，不留「DB 已改但检索结果分裂」的错误结果。
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from novamind.shared.logging import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# 单文档标签数与单标签长度上限：防标签爆炸撑大 chunk metadata 与 ES mapping
MAX_TAGS_PER_DOC = 20
MAX_TAG_LENGTH = 50


def normalize_tags(raw: Iterable[str]) -> list[str]:
    """规范化标签序列：trim、压缩内部空白、casefold、过滤空值、去重保序、截断上限。

    Args:
        raw: 用户输入的原始标签序列。

    Returns:
        规范化后的标签列表（≤ :data:`MAX_TAGS_PER_DOC` 个，每个 ≤
        :data:`MAX_TAG_LENGTH` 字符）。
    """
    seen: dict[str, None] = {}
    for item in raw:
        if not isinstance(item, str):
            continue
        tag = " ".join(item.split()).strip()
        if not tag:
            continue
        tag = tag[:MAX_TAG_LENGTH].casefold()
        seen.setdefault(tag, None)
        if len(seen) >= MAX_TAGS_PER_DOC:
            break
    return list(seen)


class DocumentTagService:
    """打标核心：DB 落值 → ES chunk 同步（metadata.doc_tags）→ 失败回滚。"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = get_logger(__name__)

    async def set_document_tags(self, document, raw_tags: Iterable[str]) -> list[str]:
        """设置文档标签并同步该文档全部 chunk 的 metadata.doc_tags。

        Args:
            document: Document ORM 对象（调用方已校验存在与权限）。
            raw_tags: 用户原始标签序列（服务内规范化）。

        Returns:
            规范化后落库的标签列表。

        Raises:
            RuntimeError: ES chunk 同步失败（DB 标签已回滚到改标前）。
        """
        tags = normalize_tags(raw_tags)
        previous = document.tags

        # 1. DB 落值（SAVEPOINT 保护，语义同 lifecycle_service）
        async with self.session.begin_nested():
            document.tags = tags
            await self.session.flush()
        await self.session.commit()

        # 2. ES chunk 同步（失败回滚 DB 标签）
        try:
            updated = await self._sync_es_chunks(document.space_id, document.id, tags)
        except Exception as e:
            await self._rollback_db_tags(document, previous)
            raise RuntimeError(
                f"ES chunk 标签同步失败，已回滚 DB 标签（doc {document.id}）: {e}"
            ) from e

        # 3. 失效检索缓存（改标后旧缓存结果与新过滤不一致；失败 TTL 兜底仅告警）
        await self._invalidate_search_cache(document.kb_id)
        self.logger.info(
            "文档标签已更新",
            document_id=document.id,
            kb_id=document.kb_id,
            tags=tags,
            es_chunks_updated=updated,
        )
        return tags

    async def aggregate_kb_tags(self, space_id: int, kb_id: int) -> list[dict[str, Any]]:
        """聚合知识库内全部活跃 chunk 的标签计数（标签云/筛选器数据源，KB 级作用域）。

        Args:
            space_id: 空间 ID（决定索引）。
            kb_id: 知识库 ID（过滤面）。

        Returns:
            ``[{"tag": ..., "count": ...}, ...]`` 按计数降序；无文档返回空表。
        """
        from novamind.features.knowledge_space.api.dependencies import (
            get_elasticsearch_client,
        )

        es_client = await get_elasticsearch_client()
        index_name = es_client.generate_index_name(space_id)
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"kb_id": kb_id}},
                        {"bool": {"must_not": [
                            {"terms": {"lifecycle_status": ["superseded", "archived"]}},
                        ]}},
                    ]
                }
            },
            "aggs": {"doc_tags": {"terms": {"field": "metadata.doc_tags.keyword", "size": 100}}},
        }
        result = await es_client.es_client.search(index=index_name, body=body)
        buckets = (
            result.get("aggregations", {}).get("doc_tags", {}).get("buckets", [])
        )
        return [{"tag": b["key"], "count": b["doc_count"]} for b in buckets]

    async def _sync_es_chunks(self, space_id: int, doc_id: int, tags: list[str]) -> int:
        """update_by_query 批量同步该文档全部 chunk 的 metadata.doc_tags。

        Returns:
            ES 报告的更新条数。
        """
        from novamind.features.knowledge_space.api.dependencies import (
            get_elasticsearch_client,
        )

        es_client = await get_elasticsearch_client()
        index_name = es_client.generate_index_name(space_id)
        result = await es_client.es_client.update_by_query(
            index=index_name,
            query={"term": {"document_id": doc_id}},
            script={
                "source": "ctx._source.metadata.doc_tags = params.t",
                "lang": "painless",
                "params": {"t": tags},
            },
            refresh=True,
        )
        return int(result.get("updated", 0))

    async def _rollback_db_tags(self, document, previous: list[str] | None) -> None:
        """ES 同步失败时把 DB 标签恢复到改标前（回滚也失败则报高危日志，人工介入）。"""
        try:
            async with self.session.begin_nested():
                document.tags = previous
                await self.session.flush()
            await self.session.commit()
        except Exception as rb_err:
            self.logger.error(
                "DB 标签回滚失败，存在 DB/ES 状态不一致，需人工修复",
                document_id=document.id,
                error=str(rb_err),
            )

    async def _invalidate_search_cache(self, kb_id: int) -> None:
        """按 KB 清检索缓存（缓存键含 kb_id 前缀，lifecycle_service 同款）。"""
        try:
            from novamind.shared.storage.client_factory import get_redis_client

            cache = await get_redis_client()
            await cache.delete_by_pattern(f"search:{kb_id}:*", batch_size=100)
        except Exception as e:  # noqa: BLE001
            self.logger.warning("检索缓存清理失败（TTL 兜底）", kb_id=kb_id, error=str(e))
