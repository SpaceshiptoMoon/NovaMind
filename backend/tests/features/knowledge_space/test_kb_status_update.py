"""知识库归档/激活状态更新的回归测试。

覆盖 PUT /knowledge-bases/{kb_id} 的 status 通道（前端归档按钮的真实链路）：
1. 活跃库 PUT status=2 → 落库为 ARCHIVED（正用例：归档生效）。
2. 归档库 PUT status=1 → 恢复 ACTIVE（正用例：激活是归档库唯一放行的写出口）。
3. 活跃库 PUT status=1（同值）/归档库 PUT status=2（同值）→ 无状态变化的幂等提交放行。
4. service 层状态机拒绝非法迁移（相邻正常场景不误伤：名称更新不带 status 照常工作）。
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytest.importorskip("aiosqlite")

from novamind.core.database.base import Base
from novamind.features.knowledge_space.exceptions import InvalidParameterError
from novamind.features.knowledge_space.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseStatus,
)
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.services.knowledge_base_service import (
    KnowledgeBaseService,
)

pytestmark = pytest.mark.unit


async def _make_service(seed: list[KnowledgeBase]):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # 只建本测试涉及的表（全量 create_all 有既存元数据问题，见 tests README）
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[KnowledgeBase.__table__]
            )
        )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    session = maker()
    session.add_all(seed)
    await session.commit()
    svc = KnowledgeBaseService.__new__(KnowledgeBaseService)
    svc.session = session
    svc.kb_repo = KnowledgeBaseRepository(session)
    # 权限链打桩：空间成员存在且可管理
    svc.member_repo = SimpleNamespace(
        get_by_space_and_user=AsyncMock(
            return_value=SimpleNamespace(
                is_active=lambda: True, is_admin=lambda: True
            )
        )
    )
    svc.permission_service = SimpleNamespace(
        can_manage_knowledge_base=lambda m: True, is_admin=lambda m: True
    )
    svc.logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
    try:
        yield svc
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.parametrize(
    "start,target,expected",
    [
        (KnowledgeBaseStatus.ACTIVE, 2, KnowledgeBaseStatus.ARCHIVED),
        (KnowledgeBaseStatus.ARCHIVED, 1, KnowledgeBaseStatus.ACTIVE),
        # 幂等：提交与当前一致的状态不构成迁移，放行
        (KnowledgeBaseStatus.ACTIVE, 1, KnowledgeBaseStatus.ACTIVE),
        (KnowledgeBaseStatus.ARCHIVED, 2, KnowledgeBaseStatus.ARCHIVED),
    ],
)
def test_status_transition_persists(start, target, expected):
    async def run():
        async for svc in _make_service(
            [KnowledgeBase(id=1, space_id=1, name="kb", creator_id=1, config={}, status=start)]
        ):
            return await svc.update_knowledge_base(kb_id=1, user_id=1, data={"status": target})

    kb = asyncio.run(run())
    assert kb.status == expected


def test_delete_status_value_rejected():
    """schema 层 Literal[1,2] 之外的值在请求解析期即被拒（service 层兜底校验同判）。"""
    async def run():
        async for svc in _make_service(
            [KnowledgeBase(id=1, space_id=1, name="kb", creator_id=1, config={})]
        ):
            with pytest.raises(InvalidParameterError):
                await svc.update_knowledge_base(kb_id=1, user_id=1, data={"status": 0})

    asyncio.run(run())


def test_name_update_without_status_untouched():
    """不带 status 的常规更新（改名）不触发状态机，name 正常落库。"""
    async def run():
        async for svc in _make_service(
            [KnowledgeBase(id=1, space_id=1, name="old", creator_id=1, config={})]
        ):
            return await svc.update_knowledge_base(kb_id=1, user_id=1, data={"name": "new"})

    kb = asyncio.run(run())
    assert kb.name == "new"
    assert kb.status == KnowledgeBaseStatus.ACTIVE
