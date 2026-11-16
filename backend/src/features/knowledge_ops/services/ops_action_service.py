"""运营动作统一登记服务：散落的处置留痕收口为单一入口。

双写语义：ops_actions 行是动作权威，kb_events 审计流对齐既有事件枚举。
两者都走独立短事务（与 EventRecorder 同模式）——调用点在请求事务内、
外、commit 前后皆可，动作登记不绑主链路的事务命运（失败方向安全：
多记一行「人确实做了这个动作」优于丢记）。
"""
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_ops.models.ops_action import OpsAction

logger = get_logger(__name__)

LEDGER_REGISTERED_ACTIONS = {"gap_converted", "review_confirmed", "todo_ignored", "todo_unignored"}
"""账本已登记事件类型（kb_event.py 注释是登记处）。

doc_archived 等新动作只进 ops_actions，避免账本事件面膨胀——
战果统计读动作表，审计流保持既有类型。"""


class OpsActionService:
    """运营动作登记公共入口（四类调用方：复审确认/生命周期/缺口转化/建议处置）"""

    async def record(
        self,
        *,
        action: str,
        target_kind: str,
        target_id: str | int,
        actor_id: int,
        space_id: int | None = None,
        kb_id: int | None = None,
        query_text: str | None = None,
        extra: dict | None = None,
        scope: dict | None = None,
        context_snapshot: dict | None = None,
        parent_action_id: int | None = None,
    ) -> OpsAction | None:
        """登记一次处置动作（动作行 + 账本双写，失败不阻断主链路）。

        Args:
            action: 动作类型（ops_action.py 模块注释维护枚举）。
            target_kind: 目标类别（document/gap/todo/suggestion/retrieval_config）。
            target_id: 目标标识。
            actor_id: 处置人用户 ID。
            space_id: 空间 ID（可空——全局动作）。
            kb_id: 关联知识库 ID（可空）。
            query_text: 关联查询文本（账本侧脱敏，可空）。
            extra: 账本事件载荷（与既有事件结构向后兼容，仅账本登记类型消费）。
            scope: 干预面（干预回看预留，本批次调用方不传）。
            context_snapshot: 动作时上下文快照。
            parent_action_id: 复检等二次处置的前序动作 ID。

        Returns:
            落库后的动作行；写入失败时 None（已告警）。
        """
        row = OpsAction(
            space_id=space_id,
            actor_id=actor_id,
            action=action,
            target_kind=target_kind,
            target_id=str(target_id),
            parent_action_id=parent_action_id,
            scope=scope,
            context_snapshot=context_snapshot,
        )
        try:
            from novamind.core.database.database import get_session_factory
            from novamind.features.knowledge_ops.repository.ops_action_repository import (
                OpsActionRepository,
            )

            factory = get_session_factory()
            async with factory() as session:
                row = await OpsActionRepository(session).insert(row)
                # 独立短事务显式提交（同 EventRecorder：不提交则关会话即回滚）
                await session.commit()
        except Exception as e:
            logger.warning(
                "运营动作登记失败（已忽略）",
                action=action,
                target_kind=target_kind,
                error=str(e),
            )
            row = None
        if action in LEDGER_REGISTERED_ACTIONS:
            from novamind.features.knowledge_ops.services.event_recorder import EventRecorder

            await EventRecorder().record(
                event_type=action,
                user_id=actor_id,
                space_id=space_id,
                kb_id=kb_id,
                query_text=query_text,
                extra=extra,
            )
        return row
