"""空间/知识库访问判定服务（批次 4.2 权限收编）。

此前 agent 的 wiki_tools 自带一套平行权限实现（``_check_kb_access`` +
``_is_admin``），与路由层 Depends 链各写一遍。本服务成为可调用共享实现，
Depends 链与 agent 工具按同一逻辑判定。

返回约定（供工具层使用错误消息而非异常）：
``check_kb_access(db, kb_id, user_id, write) -> (kb, error_msg)``
- (kb, None)：通过
- (None, msg)：拒绝（kb 不存在/无空间权限/写权限不足）
"""
from __future__ import annotations

from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.repository.member_repository import MemberRepository
from novamind.features.knowledge_space.services.permission_service import SpaceAccessChecker
from sqlalchemy.ext.asyncio import AsyncSession


async def is_admin_user(db: AsyncSession, user_id: int) -> bool:
    """用户是否平台管理员（查询失败按非管理员处理）。"""
    try:
        from novamind.features.user.models.user import User

        user = await db.get(User, user_id)
        return bool(user and user.is_admin)
    except Exception:
        return False


async def check_space_access(db: AsyncSession, space_id: int, user_id: int) -> bool:
    """空间级访问判定（agent 工具等消费方使用）。

    规则：空间存在且未删且 ACTIVE；管理员直通；成员直通；PUBLIC 空间对所有人开放。
    """
    from novamind.features.knowledge_space.models.knowledge_space import (
        SpaceStatus,
        SpaceVisibility,
    )
    from novamind.features.knowledge_space.repository.member_repository import (
        MemberRepository,
    )
    from novamind.features.knowledge_space.repository.space_repository import (
        SpaceRepository,
    )

    space = await SpaceRepository(db).get_by_id(space_id)
    if not space or space.is_deleted() or space.status != SpaceStatus.ACTIVE:
        return False
    if await is_admin_user(db, user_id):
        return True
    if await MemberRepository(db).is_member(space_id, user_id):
        return True
    return space.visibility == SpaceVisibility.PUBLIC


async def check_kb_access(
    db: AsyncSession,
    kb_id: int,
    user_id: int,
    write: bool = False,
):
    """校验 KB 存在且用户可访问空间；write 额外要求 EDITOR+ 角色。

    Returns: (kb, None) 或 (None, 错误消息)。
    """
    kb_repo = KnowledgeBaseRepository(db)
    kb = await kb_repo.get_by_id(kb_id)
    if not kb or kb.space_id is None:
        return None, f"知识库 {kb_id} 不存在"

    member = await MemberRepository(db).get_by_space_and_user(kb.space_id, user_id)
    admin = await is_admin_user(db, user_id)
    if member is None and not admin:
        return None, "无权访问该知识库所在空间"

    if write:
        checker = SpaceAccessChecker()
        if member is None or not checker.is_editor_or_above(member):
            return None, "写 Wiki 页面需要空间编辑者或更高权限"

    return kb, None


__all__ = ["check_kb_access", "check_space_access", "is_admin_user"]
