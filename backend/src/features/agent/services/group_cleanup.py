"""删 Agent 时的群侧引用清理。

独立模块而非并入 group_service：GroupService 构造 AgentService，
AgentService 反向复用群侧清理逻辑时若经 group_service 即成 import 环（R1 门禁）。
"""
from __future__ import annotations

from novamind.features.agent.models.session import AgentSession
from sqlalchemy.ext.asyncio import AsyncSession

# 与 group_service.GROUP_SESSION_FLAG 同源；独立常量避免 import 回环
GROUP_SESSION_FLAG = "group"


async def cleanup_agent_group_refs(db: AsyncSession, agent_id: int) -> None:
    """删 Agent 前清理群侧引用（同一事务，由调用方 commit）。

    Args:
        db: 调用方事务会话。
        agent_id: 被删 Agent 的 ID。
    """
    from novamind.features.agent.models.group import (
        AgentGroup,
        AgentGroupMember,
        AgentGroupRun,
    )
    from sqlalchemy import delete as sa_delete
    from sqlalchemy import select
    from sqlalchemy import update as sa_update

    member_rows = (
        await db.execute(
            select(AgentGroupMember, AgentGroup)
            .join(AgentGroup, AgentGroupMember.group_id == AgentGroup.id)
            .where(AgentGroupMember.agent_id == agent_id)
        )
    ).all()
    if not member_rows:
        return

    affected_group_ids = sorted({m.group_id for m, _ in member_rows})
    # 成员行硬删：被删 Agent 的成员身份无保留意义
    await db.execute(
        sa_delete(AgentGroupMember).where(AgentGroupMember.agent_id == agent_id)
    )
    for group_id in affected_group_ids:
        remaining = (
            await db.execute(
                select(AgentGroupMember.agent_id)
                .where(AgentGroupMember.group_id == group_id)
                .order_by(AgentGroupMember.speak_order.asc(), AgentGroupMember.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if remaining is None:
            # 群已无成员：连带解散（runs 是群的审计根随群消亡）
            await db.execute(sa_delete(AgentGroupRun).where(AgentGroupRun.group_id == group_id))
            await db.execute(sa_delete(AgentGroup).where(AgentGroup.id == group_id))
        else:
            # 主持人引用改锚到存活首成员（失败方向安全：不丢群，只换锚）
            await db.execute(
                sa_update(AgentGroup)
                .where(AgentGroup.id == group_id, AgentGroup.host_agent_id == agent_id)
                .values(host_agent_id=remaining)
            )
            # 群会话 agent_id 外键锚在被删 Agent 上：改锚到存活成员，
            # 保时间线与 runs 存续（锚会话只是外键载体，无业务语义）
            await db.execute(
                sa_update(AgentSession)
                .where(
                    AgentSession.extra_config[GROUP_SESSION_FLAG]["group_id"].as_integer() == group_id,
                    AgentSession.agent_id == agent_id,
                )
                .values(agent_id=remaining)
            )
