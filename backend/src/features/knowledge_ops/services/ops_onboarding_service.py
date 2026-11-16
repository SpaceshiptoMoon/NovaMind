"""运营冷启动引导服务：新空间从零到飞轮转起来的检查清单。

三项硬检查（检索能力/内容沉淀/行为数据）+ 三态阶段判定。判定全部用
生效语义（embedding 判定与检索侧一致：显式配置 or 用户默认回退），
避免「没显式配但默认模型可用」被误判为不可检索。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_ops.repository.kb_event_repository import KbEventRepository
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

DOCUMENT_MINIMUM = 10
QUERY_VOLUME_MINIMUM = 30
QUERY_WINDOW_DAYS = 7


class OpsOnboardingService:
    """空间运营冷启动检查"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_onboarding(self, space_id: int) -> dict[str, Any]:
        """冷启动检查清单 + 阶段判定。

        Args:
            space_id: 空间 ID。

        Returns:
            {"stage": empty|collecting|ready, "checks": [...], "next_step": 文案}。
        """
        space = await self.session.get(KnowledgeSpace, space_id)
        if space is None:
            return {
                "stage": "empty",
                "checks": [],
                "next_step": "空间不存在或已删除",
            }

        embedding_ok, embedding_detail = await self._check_embedding(space)
        document_count = await self._count_documents(space_id)
        query_count = await self._count_recent_queries(space_id)

        checks = [
            {
                "key": "embedding",
                "label": "检索能力",
                "ok": embedding_ok,
                "detail": embedding_detail,
                "action_hint": None
                if embedding_ok
                else "在空间设置中配置 Embedding 模型，或在个人模型配置中设置默认 embedding——没有它，检索维恒为空",
            },
            {
                "key": "documents",
                "label": "内容沉淀",
                "ok": document_count >= DOCUMENT_MINIMUM,
                "detail": f"{document_count} 篇文档（建议 ≥{DOCUMENT_MINIMUM} 篇起评）",
                "action_hint": None
                if document_count >= DOCUMENT_MINIMUM
                else "上传并解析第一批文档——运营飞轮的燃料是内容",
            },
            {
                "key": "query_volume",
                "label": "行为数据",
                "ok": query_count >= QUERY_VOLUME_MINIMUM,
                "detail": (
                    f"近 {QUERY_WINDOW_DAYS} 天 {query_count} 次检索"
                    + ("" if query_count >= QUERY_VOLUME_MINIMUM else f"（采集期，≥{QUERY_VOLUME_MINIMUM} 次后健康分开始有统计意义）")
                ),
                "action_hint": None
                if query_count >= QUERY_VOLUME_MINIMUM
                else "让团队成员开始提问使用——检索/反馈两个维度依赖真实行为数据",
            },
        ]

        if not embedding_ok or document_count == 0:
            stage = "empty"
            next_step = "先完成检索能力配置与首批文档上传，再谈运营"
        elif query_count < QUERY_VOLUME_MINIMUM:
            stage = "collecting"
            next_step = "内容就绪，正在采集行为数据：健康分将在数据攒够后生效，期间静态体检（过期/重复）照常可用"
        else:
            stage = "ready"
            next_step = "运营就绪：打开收件箱处理今天的待办"
        return {"stage": stage, "checks": checks, "next_step": next_step}

    async def _check_embedding(self, space: KnowledgeSpace) -> tuple[bool, str]:
        """检索能力检查（生效语义：显式配置 or owner 用户默认）。"""
        model = space.embedding_model
        source = "空间配置"
        if not model:
            try:
                from novamind.features.user.services.model_config_service import (
                    ModelConfigService,
                )

                model = await ModelConfigService(self.session).get_user_default_model_name(
                    space.owner_id, "embedding"
                )
                source = "用户默认"
            except Exception as e:
                logger.warning(
                    "用户默认 embedding 查询失败（按未配置处理）",
                    space_id=space.id,
                    error=str(e),
                )
        if model:
            return True, f"{model}（{source}）"
        return False, "未配置（无显式配置且无用户默认模型）"

    async def _count_documents(self, space_id: int) -> int:
        """内容沉淀检查：未删除文档数（全部生命周期状态）。"""
        query = (
            select(func.count(Document.id))
            .where(Document.space_id == space_id, Document.deleted_at.is_(None))
        )
        result = await self.session.execute(query)
        return int(result.scalar() or 0)

    async def _count_recent_queries(self, space_id: int) -> int:
        """行为数据检查：近 7 天 query 事件数（与趋势端点同源）。"""
        end = datetime.now()
        start = end - timedelta(days=QUERY_WINDOW_DAYS)
        return await KbEventRepository(self.session).count_events(
            space_ids=[space_id], event_type="query", start=start, end=end
        )
