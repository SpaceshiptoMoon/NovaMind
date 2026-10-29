"""群聊仓储：群/成员/运行三表的数据库访问。"""
from __future__ import annotations

from novamind.features.agent.models.agent import AgentDefinition
from novamind.features.agent.models.group import AgentGroup, AgentGroupMember, AgentGroupRun
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession


class GroupRepository:
    """群定义与成员仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_group(
        self,
        user_id: int,
        name: str,
        mode: str,
        description: str | None = None,
        host_agent_id: int | None = None,
        extra_config: dict | None = None,
        members: list[dict] | None = None,
    ) -> AgentGroup:
        """建群并写入成员（flush 不 commit，事务由调用方收口）。

        Args:
            user_id: 属主用户 ID。
            name: 群名称。
            mode: 群模式（brainstorm/consult）。
            description: 群描述，可空。
            host_agent_id: 主持人 Agent ID，可空。
            extra_config: 编排参数（rounds_per_turn 等），可空。
            members: 成员列表，元素含 agent_id/role_hint/speak_order。

        Returns:
            已 flush 的群实体。
        """
        group = AgentGroup(
            user_id=user_id,
            name=name,
            mode=mode,
            description=description,
            host_agent_id=host_agent_id,
            extra_config=extra_config,
        )
        self.session.add(group)
        await self.session.flush()
        for m in members or []:
            self.session.add(AgentGroupMember(group_id=group.id, **m))
        await self.session.flush()
        return group

    async def get_group(self, group_id: int, user_id: int) -> AgentGroup | None:
        """按 ID 取群并校验属主，未命中或非本人返回 None。"""
        result = await self.session.execute(
            select(AgentGroup).where(
                AgentGroup.id == group_id, AgentGroup.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_groups(self, user_id: int, limit: int = 50, offset: int = 0) -> tuple[list[AgentGroup], int]:
        """分页列出用户群（created_at 倒序），返回 (items, total)。"""
        total = (
            await self.session.execute(
                select(func.count()).select_from(AgentGroup).where(AgentGroup.user_id == user_id)
            )
        ).scalar_one()
        result = await self.session.execute(
            select(AgentGroup)
            .where(AgentGroup.user_id == user_id)
            .order_by(AgentGroup.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total

    async def list_members(self, group_id: int) -> list[tuple[AgentGroupMember, str]]:
        """列群成员（按 speak_order），联表取 agent 名，返回 (member, agent_name) 列表。"""
        result = await self.session.execute(
            select(AgentGroupMember, AgentDefinition.name)
            .join(AgentDefinition, AgentGroupMember.agent_id == AgentDefinition.id)
            .where(AgentGroupMember.group_id == group_id)
            .order_by(AgentGroupMember.speak_order.asc(), AgentGroupMember.id.asc())
        )
        return [(m, name) for m, name in result.all()]

    async def replace_members(self, group_id: int, members: list[dict]) -> None:
        """全量替换群成员（先删后插，flush 不 commit）。"""
        await self.session.execute(
            delete(AgentGroupMember).where(AgentGroupMember.group_id == group_id)
        )
        for m in members:
            self.session.add(AgentGroupMember(group_id=group_id, **m))
        await self.session.flush()

    async def delete_group(self, group_id: int) -> None:
        """删群（成员级联手删；flush 不 commit）。"""
        await self.session.execute(
            delete(AgentGroupMember).where(AgentGroupMember.group_id == group_id)
        )
        await self.session.execute(delete(AgentGroup).where(AgentGroup.id == group_id))
        await self.session.flush()


class GroupRunRepository:
    """群编排运行仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_running_run(self, group_id: int, session_id: str) -> AgentGroupRun | None:
        """查同群会话进行中的 run（并发护栏判据）。"""
        result = await self.session.execute(
            select(AgentGroupRun).where(
                AgentGroupRun.group_id == group_id,
                AgentGroupRun.session_id == session_id,
                AgentGroupRun.status == "running",
            )
        )
        return result.scalar_one_or_none()

    async def create_run(
        self, group_id: int, user_id: int, session_id: str, mode_snapshot: str
    ) -> AgentGroupRun:
        """建 run（flush 不 commit）。"""
        from novamind.shared.utils.time_utils import now_china

        run = AgentGroupRun(
            group_id=group_id,
            user_id=user_id,
            session_id=session_id,
            status="running",
            mode_snapshot=mode_snapshot,
            started_at=now_china(),
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def finish_run(
        self, run_id: int, status: str, error: str | None = None,
        orchestration_meta: dict | None = None,
    ) -> None:
        """收尾 run：置终态与审计字段（flush 不 commit）。"""
        from novamind.shared.utils.time_utils import now_china

        run = await self.session.get(AgentGroupRun, run_id)
        if run is None:
            return
        run.status = status
        run.error = error
        run.orchestration_meta = orchestration_meta
        run.finished_at = now_china()
        await self.session.flush()
