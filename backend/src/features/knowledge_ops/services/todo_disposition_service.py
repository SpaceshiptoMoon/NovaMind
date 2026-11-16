"""待办处置状态服务：忽略/撤销的服务面（轻状态表的唯一写入口）。

忽略 = upsert 状态行 + todo_ignored 账本留痕；撤销 = 删行 +
todo_unignored 留痕。收件箱聚合按状态表过滤，忽略态由此跨会话/跨用户。
"""
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_ops.repository.todo_disposition_repository import (
    TodoDispositionRepository,
)
from novamind.features.knowledge_ops.services.event_recorder import EventRecorder
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

IGNORE_REASONS = {"one_shot", "non_kb", "false_positive"}
"""忽略原因受控枚举：一次性提问 / 非知识需求 / 误报（自动分诊的判例燃料）。"""


class TodoDispositionService:
    """待办忽略状态服务（收件箱处置动作的持久层门面）"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def ignore(
        self,
        space_id: int,
        kind: str,
        todo_key: str,
        operator_id: int,
        reason: str | None = None,
        query_text: str | None = None,
    ) -> bool:
        """忽略一条待办：写状态行 + 账本留痕（旁路语义，失败仅告警）。

        Args:
            space_id: 空间 ID。
            kind: 待办类型（gap/review/feedback）。
            todo_key: 待办唯一键（与聚合约定同编码）。
            operator_id: 处置人用户 ID。
            reason: 忽略原因（受控枚举外原样落库但告警，便于前端契约漂移早发现）。
            query_text: 关联查询文本（gap 类携带，账本留痕用）。

        Returns:
            是否成功写入状态行。
        """
        if reason is not None and reason not in IGNORE_REASONS:
            logger.warning("待办忽略原因不在受控枚举", reason=reason, kind=kind)
        try:
            await TodoDispositionRepository(self.session).upsert_ignore(
                space_id=space_id,
                todo_key=todo_key,
                kind=kind,
                operator_id=operator_id,
                reason=reason,
            )
        except Exception as e:
            logger.warning(
                "待办忽略状态写入失败（已忽略）", kind=kind, todo_key=todo_key[:32], error=str(e)
            )
            return False
        await EventRecorder().record(
            event_type="todo_ignored",
            user_id=operator_id,
            space_id=space_id,
            query_text=query_text,
            extra={"kind": kind, "todo_key": todo_key, "reason": reason},
        )
        return True

    async def undo(self, space_id: int, kind: str, todo_key: str, operator_id: int) -> bool:
        """撤销忽略：删状态行 + todo_unignored 留痕。

        Args:
            space_id: 空间 ID。
            kind: 待办类型。
            todo_key: 待办唯一键。
            operator_id: 操作人用户 ID。

        Returns:
            是否确有忽略态被撤销（False = 本就无忽略，幂等）。
        """
        try:
            removed = await TodoDispositionRepository(self.session).delete_ignore(
                space_id=space_id, todo_key=todo_key
            )
        except Exception as e:
            logger.warning(
                "待办撤销忽略失败（已忽略）", kind=kind, todo_key=todo_key[:32], error=str(e)
            )
            return False
        if removed:
            await EventRecorder().record(
                event_type="todo_unignored",
                user_id=operator_id,
                space_id=space_id,
                extra={"kind": kind, "todo_key": todo_key},
            )
        return removed > 0
