"""
研究会话仓储层

处理研究会话的数据库操作
"""

from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.engines.deep_research.types import SearchSource
from novamind.features.deep_research.exceptions import DeepResearchError
from novamind.features.deep_research.models.research_session import (
    ExternalSearchProvider,
    ResearchMode,
    ResearchSession,
    ResearchStatus,
)
from novamind.shared.utils.time_utils import now_china
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

# update_status 允许更新的字段白名单
_UPDATABLE_FIELDS = frozenset({
    "status_info", "plan", "result", "stats",
    "completed_at", "started_at", "external_provider",
})

logger = get_logger(__name__)


class ResearchRepository:
    """研究会话仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        space_id: int,
        user_id: int,
        query: str,
        mode: ResearchMode = ResearchMode.STANDARD,
        search_source: SearchSource = SearchSource.HYBRID,
        external_provider: ExternalSearchProvider = ExternalSearchProvider.DUCKDUCKGO,
        config: dict[str, Any] | None = None,
    ) -> ResearchSession:
        """
        创建研究会话

        Args:
            space_id: 知识空间 ID
            user_id: 用户 ID
            query: 研究查询
            mode: 研究模式
            search_source: 搜索来源
            external_provider: 外部搜索服务商
            config: 研究配置（internal_search / external_search / llm 子配置）

        Returns:
            创建的研究会话
        """
        try:
            session = ResearchSession(
                space_id=space_id,
                user_id=user_id,
                session_id=ResearchSession.generate_session_id(),
                query=query,
                mode=mode.value,
                search_source=search_source.value,
                external_provider=external_provider.value,
                config=config or {},
                status=ResearchStatus.PENDING,
            )
            self.session.add(session)
            await self.session.flush()
            await self.session.refresh(session)
            return session
        except DeepResearchError:
            raise
        except Exception as e:
            logger.error("创建研究会话失败", error=str(e))
            raise DeepResearchError(f"创建研究会话失败: {str(e)}")

    async def get_by_id(self, research_id: int) -> ResearchSession | None:
        """
        通过 ID 获取研究会话（内部使用，不检查 space 状态）

        内部流程方法（update_status 等）使用此方法，
        space 状态验证在 API 层或 get_by_session_id 中完成。

        Args:
            research_id: 研究会话 ID

        Returns:
            研究会话或 None
        """
        result = await self.session.execute(
            select(ResearchSession).where(
                ResearchSession.id == research_id,
                ResearchSession.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_session_id(
        self, session_id: str, user_id: int | None = None
    ) -> ResearchSession | None:
        """
        通过会话 ID 获取研究会话（检查关联 space 未删除）

        Args:
            session_id: 会话唯一标识
            user_id: 用户 ID（可选，提供时进行用户隔离）

        Returns:
            研究会话或 None
        """
        from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace

        conditions = [
            ResearchSession.session_id == session_id,
            ResearchSession.deleted_at.is_(None),
            KnowledgeSpace.deleted_at.is_(None),
        ]
        if user_id is not None:
            conditions.append(ResearchSession.user_id == user_id)

        result = await self.session.execute(
            select(ResearchSession)
            .join(KnowledgeSpace, ResearchSession.space_id == KnowledgeSpace.id)
            .where(*conditions)
        )
        return result.scalar_one_or_none()

    async def get_by_space(
        self,
        space_id: int,
        user_id: int | None = None,
        status: ResearchStatus | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[ResearchSession]:
        """
        获取空间的研究会话列表

        Args:
            space_id: 知识空间 ID
            user_id: 用户 ID（可选，不传则返回空间所有研究）
            status: 状态过滤
            limit: 返回数量
            offset: 偏移量

        Returns:
            研究会话列表
        """
        query = select(ResearchSession).where(
            ResearchSession.space_id == space_id,
            ResearchSession.deleted_at.is_(None),
        )

        if user_id is not None:
            query = query.where(ResearchSession.user_id == user_id)

        if status is not None:
            query = query.where(ResearchSession.status == status)

        query = query.order_by(ResearchSession.created_at.desc()).offset(offset).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_by_space(
        self,
        space_id: int,
        user_id: int | None = None,
        status: ResearchStatus | None = None,
    ) -> int:
        """
        统计空间的研究会话数量

        Args:
            space_id: 知识空间 ID
            user_id: 用户 ID（可选）
            status: 状态过滤

        Returns:
            数量
        """
        query = select(func.count(ResearchSession.id)).where(
            ResearchSession.space_id == space_id,
            ResearchSession.deleted_at.is_(None),
        )

        if user_id is not None:
            query = query.where(ResearchSession.user_id == user_id)

        if status is not None:
            query = query.where(ResearchSession.status == status)

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def update_status(
        self,
        research_id: int,
        status: ResearchStatus,
        **kwargs,
    ) -> ResearchSession | None:
        """
        更新研究状态

        Args:
            research_id: 研究会话 ID
            status: 新状态
            **kwargs: 其他更新字段

        Returns:
            更新后的研究会话
        """
        try:
            research = await self.get_by_id(research_id)
            if not research:
                return None

            research.status = status

            for key, value in kwargs.items():
                if key in _UPDATABLE_FIELDS and hasattr(research, key):
                    setattr(research, key, value)

            await self.session.flush()
            await self.session.refresh(research)
            return research
        except DeepResearchError:
            raise
        except Exception as e:
            logger.error("更新研究状态失败", research_id=research_id, error=str(e))
            raise DeepResearchError(f"更新研究状态失败: {str(e)}")

    async def update_research_topic(
        self,
        research_id: int,
        topic: str,
    ) -> ResearchSession | None:
        """
        更新研究主题（存储到 config 中）

        Args:
            research_id: 研究会话 ID
            topic: 研究主题

        Returns:
            更新后的研究会话
        """
        try:
            research = await self.get_by_id(research_id)
            if not research:
                return None

            if not research.config:
                research.config = {}
            research.config["research_topic"] = topic
            flag_modified(research, "config")
            await self.session.flush()
            await self.session.refresh(research)
            return research
        except DeepResearchError:
            raise
        except Exception as e:
            logger.error("更新研究主题失败", research_id=research_id, error=str(e))
            raise DeepResearchError(f"更新研究主题失败: {str(e)}")

    async def update_tasks(
        self,
        research_id: int,
        tasks: list[dict[str, Any]],
    ) -> ResearchSession | None:
        """
        更新研究任务列表（旧形状，兼容保留；新代码用 update_plan）

        Args:
            research_id: 研究会话 ID
            tasks: 任务列表

        Returns:
            更新后的研究会话
        """
        return await self.update_plan(research_id, {"version": 1, "tasks": tasks})

    async def update_plan(
        self,
        research_id: int,
        plan_json: dict[str, Any],
    ) -> ResearchSession | None:
        """
        写入研究计划（deer-flow 对齐 v2 形状）

        Args:
            research_id: 研究会话 ID
            plan_json: 完整 plan JSON（{"version": 2, "title", "thought",
                "has_enough_context", "steps": [...], ...}）

        Returns:
            更新后的研究会话
        """
        try:
            research = await self.get_by_id(research_id)
            if not research:
                return None

            research.plan = plan_json
            flag_modified(research, "plan")
            await self.session.flush()
            await self.session.refresh(research)
            return research
        except DeepResearchError:
            raise
        except Exception as e:
            logger.error("更新研究计划失败", research_id=research_id, error=str(e))
            raise DeepResearchError(f"更新研究计划失败: {str(e)}")

    async def update_search_results(
        self,
        research_id: int,
        results: list[dict[str, Any]],
    ) -> ResearchSession | None:
        """
        更新检索结果（存储到 result 中）

        Args:
            research_id: 研究会话 ID
            results: 检索结果列表

        Returns:
            更新后的研究会话
        """
        try:
            research = await self.get_by_id(research_id)
            if not research:
                return None

            if not research.result:
                research.result = {}
            research.result["search_results"] = results
            flag_modified(research, "result")
            await self.session.flush()
            await self.session.refresh(research)
            return research
        except DeepResearchError:
            raise
        except Exception as e:
            logger.error("更新检索结果失败", research_id=research_id, error=str(e))
            raise DeepResearchError(f"更新检索结果失败: {str(e)}")

    async def complete_research(
        self,
        research_id: int,
        report: str,
        stats: dict[str, Any],
        sources: list[str] | None = None,
        citations: list[dict[str, Any]] | None = None,
    ) -> ResearchSession | None:
        """
        完成研究

        Args:
            research_id: 研究会话 ID
            report: 最终报告
            stats: 统计信息
            sources: 关键来源列表（≤5 条字符串，旧形状保留）
            citations: 全量引用列表（[{title, url, source_type}]，deer-flow 对齐）

        Returns:
            更新后的研究会话
        """
        try:
            research = await self.get_by_id(research_id)
            if not research:
                return None

            research.mark_completed(answer=report, sources=sources, stats=stats)
            if citations is not None:
                if not research.result:
                    research.result = {}
                research.result["citations"] = citations
                flag_modified(research, "result")
            await self.session.flush()
            await self.session.refresh(research)
            return research
        except DeepResearchError:
            raise
        except Exception as e:
            logger.error("完成研究失败", research_id=research_id, error=str(e))
            raise DeepResearchError(f"完成研究失败: {str(e)}")

    async def fail_research(
        self,
        research_id: int,
        error_message: str,
    ) -> ResearchSession | None:
        """
        标记研究失败

        Args:
            research_id: 研究会话 ID
            error_message: 错误信息

        Returns:
            更新后的研究会话
        """
        try:
            research = await self.get_by_id(research_id)
            if not research:
                return None

            research.mark_failed(error_message)
            await self.session.flush()
            await self.session.refresh(research)
            return research
        except DeepResearchError:
            raise
        except Exception as e:
            logger.error("标记研究失败操作失败", research_id=research_id, error=str(e))
            raise DeepResearchError(f"标记研究失败操作失败: {str(e)}")

    async def delete(self, research_id: int) -> bool:
        """
        软删除研究会话

        Args:
            research_id: 研究会话 ID

        Returns:
            是否成功
        """
        try:
            research = await self.get_by_id(research_id)
            if not research:
                return False

            research.deleted_at = now_china()
            await self.session.flush()
            return True
        except DeepResearchError:
            raise
        except Exception as e:
            logger.error("删除研究会话失败", research_id=research_id, error=str(e))
            raise DeepResearchError(f"删除研究会话失败: {str(e)}")
