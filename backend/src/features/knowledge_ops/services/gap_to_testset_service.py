"""gap → 测试集转换服务（kb-ops C flywheel）：生产失败变回归用例。

语义：把近 7 天内容缺口清单的 query 转成检索命中验证型测试用例，
追加进指定测试集（无则创建）。用例语义：补充文档后该 query 应能命中。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from novamind.features.evaluation.services.evaluation_service import EvaluationService
from novamind.features.knowledge_ops.exceptions import KbOpsError
from novamind.features.knowledge_ops.repository.gap_repository import GapRepository
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_GAP_LIMIT = 50


class GapToTestSetService:
    """gap → 测试用例转换服务"""

    def __init__(self, session: AsyncSession, evaluation_service: EvaluationService):
        self.session = session
        self.evaluation_service = evaluation_service
        self.repo = GapRepository(session)

    async def convert(
        self,
        space_id: int,
        kb_id: int,
        user_id: int,
        test_set_id: int | None = None,
    ) -> dict[str, Any]:
        """把近 7 天 gap 条目转成测试用例并落测试集。

        Args:
            space_id: 空间 ID（gap 清单与测试集的归属域）。
            kb_id: 目标知识库 ID。
            user_id: 创建人用户 ID（新建测试集时记录）。
            test_set_id: 已有测试集 ID；不传则按日期创建新集。

        Returns:
            {test_set_id, total_cases, added_cases, message} 响应字典。

        Raises:
            KbOpsError: 窗口内没有可转换的 gap 条目。
        """
        end = datetime.now()
        start = end - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        items = await self.repo.list_gap_items(space_id, start, end, limit=DEFAULT_GAP_LIMIT)
        if not items:
            raise KbOpsError("近 7 天没有内容缺口，无可转换的 gap 条目")

        cases = [
            {
                "question": item["query"],
                # 检索命中验证型用例：expected_answer 语义为「补充文档后应能检索到本问题相关内容」
                "expected_answer": (
                    f"知识库应能回答该问题（gap 转用例，最近提问 {item['hit_count']} 次）"
                ),
            }
            for item in items
        ]

        if test_set_id:
            test_set_obj = await self.evaluation_service.append_cases_to_test_set(
                test_set_id=test_set_id, space_id=space_id, kb_id=kb_id, cases=cases,
            )
            action = "已追加"
        else:
            test_set_obj = await self.evaluation_service.create_test_set_from_cases(
                space_id=space_id, kb_id=kb_id, user_id=user_id,
                name=f"缺口用例集-{kb_id}-{datetime.now().strftime('%Y%m%d')}", cases=cases,
            )
            action = "已创建"
        await self.session.commit()

        # 飞轮动作落账（旁路）：本周战果「缺口转化」计数的数据源
        await self._record_action_event(
            user_id=user_id, space_id=space_id, kb_id=kb_id,
            test_set_id=test_set_obj.id, added=len(cases),
        )
        # 半闭环回报（旁路，失败静默）：缺口 → 用例的链路对处理人显形；
        # 「回归通过」全闭环回报需测试集 ↔ 缺口 ↔ 处理人溯源，随批次 B 补齐
        await self._notify_operator(
            user_id=user_id, space_id=space_id, kb_id=kb_id,
            test_set_id=test_set_obj.id, added=len(cases), action=action,
        )
        return {
            "test_set_id": test_set_obj.id,
            "total_cases": test_set_obj.total_cases,
            "added_cases": len(cases),
            "message": f"gap 条目转测试用例{action}",
        }

    async def _notify_operator(
        self, user_id: int, space_id: int, kb_id: int, test_set_id: int, added: int, action: str
    ) -> None:
        """转换成功通知操作人（kb_gap_resolved 半闭环态）。"""
        try:
            from novamind.features.notification.models.notification import NotificationType
            from novamind.features.notification.services.notification_service import (
                NotificationService,
            )

            await NotificationService(self.session).send_notification(
                user_id=user_id,
                type=NotificationType.KB_GAP_RESOLVED.value,
                title=f"{added} 条内容缺口已转测试用例",
                content=(
                    f"缺口用例{action}于测试集 #{test_set_id}。质量基线跑批后，"
                    "可在知识运营的质量基线页查看回归结果——修复是否生效由回归说了算。"
                ),
                link=f"/home/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation",
            )
        except Exception as e:
            from novamind.core.middleware.structured_logging import get_logger

            get_logger(__name__).warning(
                "缺口转用例通知发送失败（跳过）", test_set_id=test_set_id, error=str(e)
            )

    async def _record_action_event(
        self, user_id: int, space_id: int, kb_id: int, test_set_id: int, added: int
    ) -> None:
        """缺口转化动作统一登记（动作表 + 账本双写，旁路失败静默）。"""
        try:
            from novamind.features.knowledge_ops.services.ops_action_service import OpsActionService

            await OpsActionService().record(
                action="gap_converted",
                target_kind="gap",
                target_id=f"kb:{kb_id}",
                actor_id=user_id,
                space_id=space_id,
                kb_id=kb_id,
                extra={"test_set_id": test_set_id, "added_cases": added},
                context_snapshot={"test_set_id": test_set_id, "added_cases": added},
            )
        except Exception as e:
            from novamind.core.middleware.structured_logging import get_logger

            get_logger(__name__).warning(
                "缺口转化动作登记失败（跳过）", test_set_id=test_set_id, error=str(e)
            )
