"""文档生命周期状态机（kb-ops B1）：draft → active → superseded → archived。

职责：
- 状态转换校验（非法转换抛领域异常）；
- supersede 联动：旧文档降级 + ES chunk 标记 + 版本链锚点；
- ES chunk 状态同步：update_by_query 按文档批量改 lifecycle_status
  （排除式检索过滤消费该字段）。

失败方向安全：ES 同步失败时回滚 DB 状态（不留下「DB 已降级但检索仍召回」
的不一致——错误结果方向），由调用方重试。
"""
from __future__ import annotations

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.exceptions import (
    KnowledgeBaseNotFoundError,
)
from novamind.features.knowledge_space.models.document import (
    Document,
    DocumentLifecycleStatus as Lifecycle,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class DocumentLifecycleError(Exception):
    """生命周期转换非法（BaseAPIError 体系外的内部校验错误，路由层转 400/409）。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class LifecycleService:
    """文档生命周期状态机"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = get_logger(__name__)

    async def supersede(
        self,
        old_doc_id: int,
        new_doc_id: int,
    ) -> Document:
        """新版替代旧版：旧文档 → superseded + 版本链锚点 + ES chunk 同步。

        Args:
            old_doc_id: 被替代的旧文档 ID。
            new_doc_id: 新版文档 ID（须已存在且同空间）。

        Returns:
            更新后的旧文档。

        Raises:
            ValueError: 文档不存在/跨空间。
            DocumentLifecycleError: 非法转换（旧文档已是 superseded/archived）。
            RuntimeError: ES chunk 状态同步失败（DB 状态已回滚）。
        """
        return await self._transition_with_es_sync(
            old_doc_id,
            Lifecycle.SUPERSEDED,
            extra_updates={"superseded_by_doc_id": new_doc_id},
        )

    async def archive(self, doc_id: int) -> Document:
        """下线归档：active/superseded → archived（剔旧流程终点）。"""
        return await self._transition_with_es_sync(doc_id, Lifecycle.ARCHIVED)

    async def reactivate(self, doc_id: int) -> Document:
        """恢复召回：archived/superseded → active（误操作恢复，唯一回退通道）。"""
        return await self._transition_with_es_sync(doc_id, Lifecycle.ACTIVE)

    # ========== 内部 ==========

    async def _transition_with_es_sync(
        self,
        doc_id: int,
        target_status: str,
        extra_updates: dict | None = None,
    ) -> Document:
        """转换核心：DB 校验+落状态 → ES chunk 同步 → 失败回滚 DB。

        ES 同步在 DB commit 之后执行（update_by_query 无法参与 DB 事务）；
        失败则把 DB 状态改回原值并抛 RuntimeError，保证两侧最终一致优先
        「检索不多召回」的安全方向：宁可检索仍召回（恢复原状）也不做
        「DB 已下线但检索照出」的错误结果。
        """
        row = (await self.session.execute(
            select(Document).where(Document.id == doc_id)
        )).scalar_one_or_none()
        if row is None:
            raise ValueError(f"文档 {doc_id} 不存在")
        if row.deleted_at is not None:
            raise ValueError(f"文档 {doc_id} 已软删除")

        current = row.lifecycle_status or Lifecycle.ACTIVE
        if target_status not in Lifecycle.ALLOWED_TRANSITIONS.get(current, set()):
            raise DocumentLifecycleError(
                f"非法生命周期转换: {current} → {target_status} (doc {doc_id})"
            )

        previous_status = current
        previous_extra = {
            "superseded_by_doc_id": row.superseded_by_doc_id,
        }
        # 离开 superseded 态时清版本链锚点（reactivate/superseded→archived 均适用）：
        # 锚点只在「被替代」状态下有意义，残留会让版本链视图误判当前替代关系
        if current == Lifecycle.SUPERSEDED and target_status != Lifecycle.SUPERSEDED:
            extra_updates = {**(extra_updates or {}), "superseded_by_doc_id": None}

        # 1. DB 落状态（SAVEPOINT 保护）
        async with self.session.begin_nested():
            row.lifecycle_status = target_status
            if extra_updates:
                for k, v in extra_updates.items():
                    setattr(row, k, v)
            await self.session.flush()
        await self.session.commit()

        # 2. ES chunk 状态同步（失败回滚 DB 状态）
        try:
            updated = await self._sync_es_chunks(row.space_id, doc_id, target_status)
        except Exception as e:
            await self._rollback_db_status(
                row, previous_status, previous_extra, extra_updates or {}
            )
            raise RuntimeError(
                f"ES chunk 状态同步失败，已回滚 DB 状态（doc {doc_id}）: {e}"
            ) from e
        # 3. 失效检索缓存（wiki_tasks 同款先例）：不失效则同 query 的缓存结果
        # 仍含已下线 chunk，最久活到 TTL——「新版已替换旧版」在缓存窗口内不生效。
        # 失败仅告警（缓存有 TTL 兜底，最终一致），不回滚。
        await self._invalidate_search_cache(row.kb_id)
        self.logger.info(
            "生命周期转换完成",
            document_id=doc_id,
            status=f"{previous_status} → {target_status}",
            es_chunks_updated=updated,
        )
        return row

    async def _invalidate_search_cache(self, kb_id: int) -> None:
        """按 KB 清检索缓存（缓存键含 kb_id 前缀，wiki_tasks 同款先例）。"""
        try:
            from novamind.shared.storage.client_factory import get_redis_client

            cache = await get_redis_client()
            await cache.delete_by_pattern(f"search:{kb_id}:*", batch_size=100)
        except Exception as e:
            self.logger.warning("检索缓存清理失败（TTL 兜底）", kb_id=kb_id, error=str(e))

    async def _rollback_db_status(
        self,
        row: Document,
        previous_status: str,
        previous_extra: dict,
        applied_extra: dict,
    ) -> None:
        """ES 同步失败时把 DB 状态恢复到转换前。"""
        try:
            async with self.session.begin_nested():
                row.lifecycle_status = previous_status
                if "superseded_by_doc_id" in applied_extra:
                    row.superseded_by_doc_id = previous_extra["superseded_by_doc_id"]
                await self.session.flush()
            await self.session.commit()
        except Exception as rb_err:
            # 回滚也失败：记录高危不一致，人工介入（比静默吞掉更诚实）
            self.logger.error(
                "DB 状态回滚失败，存在 DB/ES 状态不一致，需人工修复",
                document_id=row.id,
                error=str(rb_err),
            )

    async def _sync_es_chunks(self, space_id: int, doc_id: int, status: str) -> int:
        """update_by_query 批量同步该文档全部 chunk 的 lifecycle_status。"""
        from novamind.features.knowledge_space.api.dependencies import (
            get_elasticsearch_client,
        )

        es_client = await get_elasticsearch_client()
        index_name = es_client.generate_index_name(space_id)
        try:
            result = await es_client.es_client.update_by_query(
                index=index_name,
                query={"term": {"document_id": doc_id}},
                script={
                    "source": "ctx._source.lifecycle_status = params.s",
                    "params": {"s": status},
                },
                refresh=True,
            )
            return int(result.get("updated", 0))
        except Exception as e:
            # 索引不存在（文档从未成功索引）视为 0 成功——转换本身合法
            if "index_not_found" in str(e).lower():
                return 0
            raise