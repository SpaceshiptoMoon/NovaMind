"""群聊管理服务：群 CRUD、成员校验、群会话（一群多会话）、一响触发入口。"""
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
# 成员私有会话 extra_config.group_member 标记键（与 orchestrator 同值；
# 不从对方 import——两者互不依赖，同值约定见设计文档数据模型节）
GROUP_MEMBER_FLAG = "group_member"


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
        """解散群（成员级联删、运行审计连带清；群会话保留——普通会话，用户可自行清理）。"""
        group = await self._get_owned_group(user_id, group_id)
        from sqlalchemy import delete as sa_delete

        from novamind.features.agent.models.group import AgentGroupRun

        # runs 外键同时引用群与会话，留着即 1451；群是审计的根，随群消亡
        await self.db.execute(sa_delete(AgentGroupRun).where(AgentGroupRun.group_id == group.id))
        await self.group_repo.delete_group(group.id)
        await self.db.commit()

    # ==================== 群会话与一响触发 ====================

    async def get_or_create_group_session(
        self, user_id: int, group_id: int, session_id: str | None = None
    ) -> AgentSession:
        """取/建群会话（时间线载体，extra_config.group={group_id} 标记）。

        未带 session_id 时返回该群最新 active 群会话，无则新建——供前端
        未指定会话的进入路径与 WS 容错；多会话由 create_group_session
        显式新建。

        Args:
            session_id: 带值时校验归属与群匹配（会话须属于该群）。
        """
        group = await self._get_owned_group(user_id, group_id)
        if session_id:
            conv = await self._get_group_session_or_fail(user_id, group_id, session_id)
            return conv
        existing = await self._find_group_session(group.id)
        if existing is not None:
            return existing
        agent_id = group.host_agent_id
        if agent_id is None:
            agent_id = await _first_member_agent_id(self.db, group.id)
        conv = await self.session_repo.create(
            user_id=user_id, agent_id=agent_id,
            extra_config={GROUP_SESSION_FLAG: {"group_id": group.id}},
        )
        await self.db.commit()
        return conv

    async def create_group_session(self, user_id: int, group_id: int) -> AgentSession:
        """显式新建群会话（一群多会话：每次调用都是新会话，不复用不回退）。

        Args:
            user_id: 属主用户 ID。
            group_id: 群 ID（须为属主的群）。

        Returns:
            新建的群会话（extra_config.group={group_id} 标记）。

        Raises:
            GroupNotFoundError: 群不存在或非属主。
        """
        group = await self._get_owned_group(user_id, group_id)
        agent_id = group.host_agent_id
        if agent_id is None:
            agent_id = await _first_member_agent_id(self.db, group.id)
        conv = await self.session_repo.create(
            user_id=user_id, agent_id=agent_id,
            extra_config={GROUP_SESSION_FLAG: {"group_id": group.id}},
        )
        await self.db.commit()
        return conv

    async def list_group_sessions(
        self, user_id: int, group_id: int, limit: int = 50, offset: int = 0
    ) -> tuple[list[AgentSession], int]:
        """列出群的 active 会话（id 倒序=最新在前），供会话侧栏展示。"""
        await self._get_owned_group(user_id, group_id)
        from sqlalchemy import func, select

        base = select(AgentSession).where(
            AgentSession.user_id == user_id,
            AgentSession.status == "active",
            AgentSession.extra_config[GROUP_SESSION_FLAG]["group_id"].as_integer() == group_id,
        )
        total = (await self.db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
        result = await self.db.execute(
            base.order_by(AgentSession.id.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def delete_group_session(self, user_id: int, group_id: int, session_id: str) -> None:
        """软删群会话；该会话关联的成员私有会话与 runs 一并清（隔离边界随之消亡）。

        Raises:
            GroupNotFoundError: 群或会话不存在/非属主/不属于该群。
            AgentError: 该会话仍有 running run（先停止讨论再删）。
        """
        from novamind.features.agent.exceptions import AgentError
        from novamind.features.agent.models.group import AgentGroupRun
        from sqlalchemy import delete as sa_delete
        from sqlalchemy import select

        group = await self._get_owned_group(user_id, group_id)
        conv = await self._get_group_session_or_fail(user_id, group.id, session_id)
        running = await self.run_repo.get_running_run(group.id, conv.session_id)
        if running is not None:
            raise AgentError("该会话正在讨论中，请先停止再删除")
        # 成员私有会话按 (group_id, group_session_id) 归属，随群会话一起软删
        member_result = await self.db.execute(
            select(AgentSession).where(
                AgentSession.extra_config[GROUP_MEMBER_FLAG]["group_id"].as_integer() == group.id,
                AgentSession.extra_config[GROUP_MEMBER_FLAG]["group_session_id"].as_string()
                == conv.session_id,
                AgentSession.status == "active",
            )
        )
        from novamind.shared.utils.time_utils import now_china

        from sqlalchemy import update as sa_update

        now = now_china()
        for member_conv in member_result.scalars().all():
            await self.db.execute(
                sa_update(AgentSession)
                .where(AgentSession.id == member_conv.id)
                .values(status="deleted", updated_at=now)
            )
        await self.db.execute(
            sa_update(AgentSession)
            .where(AgentSession.id == conv.id)
            .values(status="deleted", updated_at=now)
        )
        await self.db.execute(
            sa_delete(AgentGroupRun).where(
                AgentGroupRun.group_id == group.id,
                AgentGroupRun.session_id == conv.session_id,
            )
        )
        await self.db.commit()

    async def _get_group_session_or_fail(
        self, user_id: int, group_id: int, session_id: str
    ) -> AgentSession:
        """取群会话并校验：存在、属主、active、且 extra_config.group.group_id 匹配。"""
        conv = await self.session_repo.get_by_session_id(session_id)
        if (
            conv is None or conv.user_id != user_id
            or conv.status != "active"
            or (conv.extra_config or {}).get(GROUP_SESSION_FLAG, {}).get("group_id") != group_id
        ):
            raise GroupNotFoundError(group_id)
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
