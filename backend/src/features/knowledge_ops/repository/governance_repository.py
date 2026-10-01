"""治理聚合仓库（kb-ops D）：重复文档视图 + 贡献统计。

纯 SQL 聚合，无 LLM；只读。重复视图 = 精确重复（file_hash 同 KB 分组）+
同归一化文件名分组（复用 new_version_detector.normalize_filename 口径）；
贡献统计 = citation_click 聚合（kb_events）。
"""
from __future__ import annotations

from typing import Any

from novamind.features.knowledge_ops.services.new_version_detector import (
    normalize_filename,
)
from sqlalchemy import BigInteger, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


class GovernanceRepository:
    """治理视图聚合仓库（只读）"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ========== 重复文档（七问之7：「退货政策有几份」） ==========

    async def find_duplicate_groups(
        self, space_id: int, kb_id: int | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """重复文档分组：精确重复（file_hash）+ 同归一化文件名，两类分别返回。

        只统计未软删的 active/superseded/archived 文档（soft-deleted 不算在库）。
        每组返回文档清单与重复类型；处置建议走 B2 建议流，本视图只展示。
        """
        from novamind.features.knowledge_space.models.document import (
            Document,
            DocumentLifecycleStatus,
        )

        conditions = [
            Document.space_id == space_id,
            Document.deleted_at.is_(None),
        ]
        if kb_id is not None:
            conditions.append(Document.kb_id == kb_id)

        rows = (await self.session.execute(
            select(
                Document.id, Document.kb_id, Document.filename,
                Document.file_hash, Document.lifecycle_status, Document.created_at,
                Document.superseded_by_doc_id,
            )
            .where(*conditions)
            .order_by(Document.kb_id, Document.id)
            .limit(1000)
        )).all()

        # 精确重复组：(kb_id, file_hash) → docs（>1 才算组）
        by_hash: dict[tuple[int, str], list[dict]] = {}
        # 同名组：(kb_id, 归一化名) → docs（>1 才算组）
        by_name: dict[tuple[int, str], list[dict]] = {}

        for r in rows:
            doc = {
                "document_id": r.id,
                "kb_id": r.kb_id,
                "filename": r.filename,
                "lifecycle_status": r.lifecycle_status or "active",
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "superseded_by_doc_id": r.superseded_by_doc_id,
            }
            by_hash.setdefault((r.kb_id, r.file_hash), []).append(doc)
            name_key = normalize_filename(r.filename)
            if name_key:
                by_name.setdefault((r.kb_id, name_key), []).append(doc)

        groups: list[dict[str, Any]] = []
        for (kb, h), docs in by_hash.items():
            if len(docs) > 1:
                groups.append({
                    "group_type": "exact_hash",
                    "kb_id": kb,
                    "key": h[:16],
                    "documents": docs,
                })
        for (kb, name), docs in by_name.items():
            if len(docs) > 1:
                groups.append({
                    "group_type": "same_normalized_name",
                    "kb_id": kb,
                    "key": name[:32],
                    "documents": docs,
                })
        # 组内文档数降序（最严重的重复组在前）
        groups.sort(key=lambda g: -len(g["documents"]))
        return groups[:limit]

    # ========== 贡献统计（七问之2：哪些文档最常支撑回答/从未被用） ==========

    async def citation_stats_by_document(
        self, space_id: int, limit: int = 50,
    ) -> list[dict[str, Any]]:
        """文档被点击核验统计：kb_events.citation_click 按 extra.document_id 聚合。

        Returns:
            [{document_id, kb_id, click_count}] 按点击降序。
        """
        from novamind.features.knowledge_ops.models.kb_event import KbEvent

        rows = (await self.session.execute(
            select(
                KbEvent.extra["document_id"].as_integer().label("document_id"),
                func.count(KbEvent.id).label("click_count"),
            )
            .where(
                KbEvent.space_id == space_id,
                KbEvent.event_type == "citation_click",
                KbEvent.extra["document_id"].as_integer().isnot(None),
            )
            .group_by(KbEvent.extra["document_id"].as_integer())
            .order_by(func.count(KbEvent.id).desc())
            .limit(limit)
        )).all()
        return [
            {"document_id": r.document_id, "click_count": int(r.click_count)}
            for r in rows
        ]

    async def support_stats_by_document(
        self, space_id: int, limit: int = 50,
    ) -> list[dict[str, Any]]:
        """文档支撑回答统计：question_answers.extra.sources 里的 document_id 聚合。

        「支撑回答数」= assistant 消息的 sources 引用了该文档的次数（与批次 2b
        看板同源 question_answers，无回溯难题——O1 未把 sources 落 kb_events，
        数据权威源在消息行）。

        空间归属：消息行 space_id 常为空（不回填，O2 起的五处同根因），空则经
        会话 RAG 绑定兜底（与 citation_click/归因/gap 同款兜底链）。
        """
        from novamind.features.qa.models.question_answer import QuestionAnswer
        from novamind.features.qa.models.session_config import SessionConfig

        rows = (await self.session.execute(
            select(
                QuestionAnswer.session_id,
                QuestionAnswer.space_id,
                QuestionAnswer.extra["sources"],
            )
            .where(
                QuestionAnswer.role == "assistant",
                or_(
                    QuestionAnswer.space_id == space_id,
                    QuestionAnswer.space_id.is_(None),
                ),
                QuestionAnswer.extra["sources"].isnot(None),
            )
            .order_by(QuestionAnswer.id.desc())
            .limit(2000)
        )).all()

        # 会话 → RAG 绑定空间映射（只为 space 为空的消息兜底，一次查回）
        null_space_sessions = {
            r.session_id for r in rows if r.space_id is None
        }
        session_space: dict[str, int | None] = {}
        if null_space_sessions:
            cfg_rows = (await self.session.execute(
                select(
                    SessionConfig.session_id,
                    SessionConfig.kb_bindings["space_id"].as_integer(),
                ).where(SessionConfig.session_id.in_(null_space_sessions))
            )).all()
            session_space = {r.session_id: r[1] for r in cfg_rows}

        counts: dict[int, int] = {}
        for r in rows:
            effective_space = r.space_id if r.space_id is not None else session_space.get(r.session_id)
            if effective_space != space_id:
                continue  # 兜底后仍不属于该空间（或无从判定）→ 不计入
            sources = r[2]
            if not isinstance(sources, list):
                continue
            seen_docs: set[int] = set()  # 同一消息内同文档去重（支撑=是否被引用）
            for s in sources:
                if isinstance(s, dict) and s.get("kind") == "kb" and s.get("document_id"):
                    seen_docs.add(int(s["document_id"]))
            for doc_id in seen_docs:
                counts[doc_id] = counts.get(doc_id, 0) + 1

        ranked = sorted(counts.items(), key=lambda x: -x[1])[:limit]
        return [
            {"document_id": doc_id, "support_count": count}
            for doc_id, count in ranked
        ]
