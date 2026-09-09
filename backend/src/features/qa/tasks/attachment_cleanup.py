"""孤儿聊天附件清理（cron 任务）。

背景：chat-attachments 上传即落库落 MinIO，用户取消发送/发送失败时无人回收，
存储与表只增不减。判定口径：上传超过 ORPHAN_CUTOFF_DAYS 天、且从未被任何
消息 extra 引用的附件视为孤儿（附件与消息无外键，引用只经 JSON extra 传递——
agent_messages.extra 与 question_answer.extra 两处，形态均为 {"attachments": [{"id": ...}]}）。
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Set

from sqlalchemy import select

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 误删兜底：只清理上传超过 7 天仍无引用的附件
ORPHAN_CUTOFF_DAYS = 7


def _collect_referenced_ids(extras) -> Set[int]:
    """从消息 extra 列表收集被引用的附件 id 集合"""
    referenced: Set[int] = set()
    for row in extras:
        extra = row[0]
        if not isinstance(extra, dict):
            continue
        for att in extra.get("attachments") or []:
            if isinstance(att, dict) and isinstance(att.get("id"), int):
                referenced.add(att["id"])
    return referenced


async def cleanup_orphan_attachments(ctx: Dict[str, Any] | None = None) -> int:
    """删除孤儿附件（DB 记录 + MinIO 对象）。返回删除条数。

    cron 周期调用；任何一步失败都不中断整体（逐条容错）。
    """
    from novamind.core.database.database import get_db_session
    from novamind.features.agent.models.message import AgentMessage
    from novamind.features.qa.models.chat_attachment import ChatAttachment
    from novamind.features.qa.models.question_answer import QuestionAnswer

    cutoff = datetime.now(timezone.utc) - timedelta(days=ORPHAN_CUTOFF_DAYS)

    async with get_db_session() as db:
        # 1. 候选：cutoff 之前上传的附件
        result = await db.execute(
            select(ChatAttachment).where(ChatAttachment.created_at < cutoff)
        )
        candidates = list(result.scalars().all())
        if not candidates:
            return 0

        # 2. 被引用集合：两张消息表的 extra JSON（只查带 extra 的行，量级可控）
        agent_rows = await db.execute(
            select(AgentMessage.extra).where(AgentMessage.extra.isnot(None))
        )
        qa_rows = await db.execute(
            select(QuestionAnswer.extra).where(QuestionAnswer.extra.isnot(None))
        )
        referenced = _collect_referenced_ids(agent_rows) | _collect_referenced_ids(qa_rows)

        orphans = [a for a in candidates if a.id not in referenced]
        if not orphans:
            return 0

        # 3. MinIO 对象删除（失败仅告警，不阻断 DB 清理——对象泄漏可接受，误删不可）
        minio_client = None
        try:
            from novamind.shared.storage.client_factory import ClientFactory

            minio_client = await ClientFactory.get_minio_client()
        except Exception as e:
            logger.warning("孤儿附件清理：MinIO 客户端不可用，仅清理 DB 记录", error=str(e))

        deleted = 0
        for att in orphans:
            try:
                if minio_client is not None:
                    try:
                        await minio_client.delete_document(
                            minio_client.default_bucket, att.storage_path
                        )
                    except Exception as e:
                        logger.warning(
                            "孤儿附件 MinIO 删除失败（继续删 DB 记录）",
                            attachment_id=att.id,
                            error=str(e),
                        )
                await db.delete(att)
                deleted += 1
            except Exception as e:
                logger.warning(
                    "孤儿附件删除失败",
                    attachment_id=att.id,
                    error=str(e),
                )
        await db.commit()

    logger.info("孤儿附件清理完成", deleted=deleted, cutoff_days=ORPHAN_CUTOFF_DAYS)
    return deleted