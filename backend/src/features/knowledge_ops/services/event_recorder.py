"""事件账本写入端口：旁路语义，任何异常不向调用方传播。

失败方向安全（项目硬规则）：账本挂了问答照常，绝不让运营埋点拖垮主链路。
脱敏在写入前完成（redact_sensitive_text），query_text 默认脱敏。
"""
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_ops.models.kb_event import KbEvent
from novamind.shared.utils.redact import redact_sensitive_text

logger = get_logger(__name__)


class EventRecorder:
    """运营事件写入端口（旁路，永不抛错）。

    会话工厂在 record 时惰性获取而非 __init__ 预取：埋点调用点在请求事务内，
    直接复用请求 session 会把账本写入绑定到问答主链路的事务命运上（主链路
    rollback 会连带回滚账本行）；独立短事务保证「旁路」语义真正成立。
    """

    async def record(
        self,
        event_type: str,
        user_id: int,
        session_id: str | None = None,
        space_id: int | None = None,
        kb_id: int | None = None,
        query_text: str | None = None,
        extra: dict | None = None,
    ) -> None:
        """记录一条事件；内部独立短事务 + 全异常吞掉。

        Args:
            event_type: 事件类型常量（kb_event.py 模块注释维护枚举）。
            user_id: 触发用户 ID。
            session_id: 关联会话 ID（可空）。
            space_id: 关联空间 ID（权限域过滤必带，可空）。
            kb_id: 关联知识库 ID（可空）。
            query_text: 查询文本，写入前脱敏（可空）。
            extra: 事件私有载荷（dict，可 JSON 序列化）。
        """
        try:
            from novamind.core.database.database import get_session_factory

            redacted = redact_sensitive_text(query_text) if query_text else query_text
            # 截断到列宽（512），避免长查询落库报错——脱敏后仍可能超长
            if redacted and len(redacted) > 512:
                redacted = redacted[:512]
            event = KbEvent(
                event_type=event_type,
                user_id=user_id,
                session_id=session_id,
                space_id=space_id,
                kb_id=kb_id,
                query_text=redacted,
                extra=extra,
            )
            factory = get_session_factory()
            async with factory() as session:
                from novamind.features.knowledge_ops.repository.kb_event_repository import (
                    KbEventRepository,
                )
                await KbEventRepository(session).insert(event)
                # 独立短事务必须显式提交：本会话不随请求事务走，不提交则
                # 会话关闭时整体回滚，事件行丢失（旁路语义反成"永远不记"）
                await session.commit()
        except Exception as e:
            # 旁路语义：吞掉一切异常（含 CancelledError 以外的 DB/配置错误），仅告警
            logger.warning("运营事件记录失败（已忽略）", event_type=event_type, error=str(e))
