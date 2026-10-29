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
        return {
            "test_set_id": test_set_obj.id,
            "total_cases": test_set_obj.total_cases,
            "added_cases": len(cases),
            "message": f"gap 条目转测试用例{action}",
        }
