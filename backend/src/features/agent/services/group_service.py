"""群聊管理服务：群 CRUD、成员校验、群会话 get_or_create、一响触发入口。"""
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.agent.exceptions import (
    AgentNotFoundError,
    GroupNotFoundError,
    GroupRunConflictError,
)
from novamind.features.agent.models.group import AgentGroup
from novamind.features.agent.models.session import AgentSession
from novamind.features.agent.repository.group_repository import (
    GroupRepository,
    GroupRunRepository,
)
from novamind.features.agent.repository.agent_repository import SessionRepository
from novamind.features.agent.schemas.group_schema import (
    AgentGroupCreate,
    AgentGroupDetailResponse,
    AgentGroupListResponse,
    AgentGroupMemberResponse,
    AgentGroupResponse,
    AgentGroupUpdate,
)
from novamind.features.agent.services.agent_service import AgentService
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# 群会话 extra_config.group 标记键（时间线所在会话）
GROUP_SESSION_FLAG = "group"


class GroupService:
    """群聊管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.agent_service = AgentService(db)
        self.group_repo = GroupRepository(db)
        self.run_repo = GroupRunRepository(db)
        self.session_repo = SessionRepository(db)

    # ==================== 群 CRUD ====================

    async def create_group(self, user_id: int, data: AgentGroupCreate) -> AgentGroupDetailResponse:
        """建群：成员 Agent 逐一归属校验后落群+成员（consult 主持人校验在 schema 层）。"""
        for agent_id in data.member_ids:
            await self.agent_service.get_agent_or_fail(user_id, agent_id)
        extra_config = {"rounds_per_turn": data.rounds_per_turn}
        group = await self.group_repo.create_group(
            user_id=user_id,
            name=data.name,
            mode=data.mode,
            description=data.description,
            host_agent_id=data.host_agent_id,
            extra_config=extra_config,
            members=[
                {"agent_id": aid, "role_hint": None, "speak_order": idx}
                for idx, aid in enumerate(data.member_ids)
            ],
        )
        await self.db.commit()
        return await self.get_group(user_id, group.id)

    async def list_groups(self, user_id: int, limit: int, offset: int) -> AgentGroupListResponse:
        """分页列我的群，逐群补成员数。"""
        groups, total = await self.group_repo.list_groups(user_id, limit, offset)
        items = []
        for g in groups:
            resp = AgentGroupResponse.model_validate(g)
            resp.member_count = len(await self.group_repo.list_members(g.id))
            items.append(resp)
        return AgentGroupListResponse(items=items, total=total)

    async def get_group(self, user_id: int, group_id: int) -> AgentGroupDetailResponse:
        """取群详情（含成员），未命中或非属主抛 GroupNotFoundError。"""
        group = await self._get_owned_group(user_id, group_id)
        member_rows = await self.group_repo.list_members(group.id)
        return AgentGroupDetailResponse(
            id=group.id,
            name=group.name,
            description=group.description,
            mode=group.mode,
            host_agent_id=group.host_agent_id,
            member_count=len(member_rows),
            created_at=group.created_at,
            extra_config=group.extra_config,
            members=[
                AgentGroupMemberResponse(
                    id=row.id, agent_id=row.agent_id, role_hint=row.role_hint,
                    speak_order=row.speak_order, agent_name=name,
                )
                for row, name in member_rows
            ],
        )

    async def update_group(
        self, user_id: int, group_id: int, data: AgentGroupUpdate
    ) -> AgentGroupDetailResponse:
        """改群：全量替换成员时重算 speak_order；mode/host/成员组合校验对齐建群口径。"""
        group = await self._get_owned_group(user_id, group_id)
        update = data.model_dump(exclude_unset=True)

        effective_members = (
            update["member_ids"] if update.get("member_ids") is not None
            else [row.agent_id for row, _ in await self.group_repo.list_members(group.id)]
        )
        effective_mode = update.get("mode") or group.mode
        effective_host = update.get("host_agent_id") or group.host_agent_id
        if effective_mode == "consult":
            if effective_host is None:
                from novamind.features.agent.exceptions import AgentError
                raise AgentError("专家咨询模式必须指定主持人")
            if effective_host not in effective_members:
                from novamind.features.agent.exceptions import AgentError
                raise AgentError("主持人必须在成员列表内")

        if update.get("member_ids") is not None:
            for aid in update["member_ids"]:
                await self.agent_service.get_agent_or_fail(user_id, aid)

        patch: dict[str, Any] = {}
        for key in ("name", "description", "mode", "host_agent_id"):
            if key in update:
                patch[key] = update[key]
        if "rounds_per_turn" in update:
            patch["extra_config"] = {
                **(group.extra_config or {}),
                "rounds_per_turn": update["rounds_per_turn"],
            }
        if patch:
            from sqlalchemy import update as sa_update

            from novamind.features.agent.models.group import AgentGroup

            await self.db.execute(sa_update(AgentGroup).where(AgentGroup.id == group.id).values(**patch))
            await self.db.flush()
        if update.get("member_ids") is not None:
            await self.group_repo.replace_members(
                group.id,
                [
                    {"agent_id": aid, "role_hint": None, "speak_order": idx}
                    for idx, aid in enumerate(update["member_ids"])
                ],
            )
        await self.db.commit()
        return await self.get_group(user_id, group_id)

    async def delete_group(self, user_id: int, group_id: int) -> None:
        """解散群（成员级联删；成员私有会话保留——普通会话，用户可自行清理）。"""
        await self._get_owned_group(user_id, group_id)
        await self.group_repo.delete_group(group_id)
        await self.db.commit()

    # ==================== 群会话与一响触发 ====================

    async def get_or_create_group_session(
        self, user_id: int, group_id: int, session_id: str | None = None
    ) -> AgentSession:
        """取/建群会话（时间线载体，extra_config.group={group_id} 标记）。

        Args:
            session_id: 带值时校验归属与群匹配（一个群一个会话，P1 不做多会话）。
        """
        group = await self._get_owned_group(user_id, group_id)
        if session_id:
            conv = await self.session_repo.get_by_session_id(session_id)
            if (
                conv is None or conv.user_id != user_id
                or conv.status != "active"
                or (conv.extra_config or {}).get(GROUP_SESSION_FLAG, {}).get("group_id") != group.id
            ):
                raise GroupNotFoundError(group_id)
            return conv
        existing = await self._find_group_session(group.id)
        if existing is not None:
            return existing
        conv = await self.session_repo.create(
            user_id=user_id, agent_id=group.host_agent_id or _first_member_agent_id(self.db, group.id),
            extra_config={GROUP_SESSION_FLAG: {"group_id": group.id}},
        )
        await self.db.commit()
        return conv

    async def _find_group_session(self, group_id: int) -> AgentSession | None:
        from sqlalchemy import select

        stmt = (
            select(AgentSession)
            .where(
                AgentSession.extra_config[GROUP_SESSION_FLAG]["group_id"].as_integer() == group_id,
                AgentSession.status == "active",
            )
            .order_by(AgentSession.id.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def ensure_no_running_run(self, group_id: int, session_id: str) -> None:
        """同群会话并发护栏：已有 running run 时拒绝（GroupRunConflictError）。"""
        running = await self.run_repo.get_running_run(group_id, session_id)
        if running is not None:
            raise GroupRunConflictError(group_id)

    async def start_run(
        self, user_id: int, group: AgentGroup, session_id: str
    ) -> "AgentGroupRun":
        """创建一响 run（running 状态，flush 由调用方 commit）。"""
        return await self.run_repo.create_run(
            group_id=group.id, user_id=user_id,
            session_id=session_id, mode_snapshot=group.mode,
        )

    async def _get_owned_group(self, user_id: int, group_id: int) -> AgentGroup:
        group = await self.group_repo.get_group(group_id, user_id)
        if group is None:
            raise GroupNotFoundError(group_id)
        return group


async def _first_member_agent_id(db: AsyncSession, group_id: int) -> int:
    """取群首个成员的 agent_id（群会话 agent_id 外键兜底值）。"""
    from sqlalchemy import select

    from novamind.features.agent.models.group import AgentGroupMember

    result = await db.execute(
        select(AgentGroupMember.agent_id)
        .where(AgentGroupMember.group_id == group_id)
        .order_by(AgentGroupMember.speak_order.asc())
        .limit(1)
    )
    aid = result.scalar_one_or_none()
    if aid is None:
        raise AgentNotFoundError(0)
    return aid
