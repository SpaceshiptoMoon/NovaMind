"""技能指令注入链路回归测试。

P0 修复背景：``skill__{id}_{name}`` 的 name 可含下划线/连字符（如
``skill__5_code-reviewer``、``skill__9_my_skill``），旧实现用
``split("_", 2)`` 解析得到空字符串 parts[1]，``int('')`` 必抛 ValueError
被 except 吞掉，导致技能指令永远注入不进 system prompt。
"""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import novamind.features.skill.repository.skill_repository as skill_repo_mod
from novamind.features.agent.services.chat_service import AgentChatService
from novamind.features.skill.models.skill import SkillStatus, ReviewStatus


def _make_skill(skill_id: int, name: str, display_name: str = "技能"):
    """构造 PUBLISHED+APPROVED 的技能对象"""
    return SimpleNamespace(
        id=skill_id,
        name=name,
        display_name=display_name,
        body_markdown="## 指令\n按步骤执行",
        status=SkillStatus.PUBLISHED,
        review_status=ReviewStatus.APPROVED,
    )


@contextmanager
def _patched_repo(skill_def):
    """把 SkillRepository 替换为返回 skill_def 的桩仓储（函数内延迟导入，须 patch 源模块）"""

    class _Repo:
        def __init__(self, session):
            pass

        async def get_by_id(self, skill_id):
            return skill_def

    original = skill_repo_mod.SkillRepository
    skill_repo_mod.SkillRepository = _Repo  # type: ignore[misc]
    try:
        yield
    finally:
        skill_repo_mod.SkillRepository = original  # type: ignore[misc]


def _make_service() -> AgentChatService:
    svc = AgentChatService.__new__(AgentChatService)
    svc.db = SimpleNamespace()  # _collect_skill_fragments 会用 self.db 构造仓储
    return svc


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "skill_id,name",
    [
        (5, "code-reviewer"),   # 连字符 name
        (9, "my_skill"),        # 下划线 name
        (1, "a"),               # 无分隔符最短 name
    ],
)
async def test_collect_skill_fragments_parses_ref_correctly(skill_id, name) -> None:
    """skill__{id}_{name} 各形态都能正确解析出 id 并注入技能指令"""
    skill_def = _make_skill(skill_id, name)
    with _patched_repo(skill_def):
        svc = _make_service()
        fragments = await svc._collect_skill_fragments([f"skill__{skill_id}_{name}"])
    assert len(fragments) == 1, f"技能 {name} 的指令应被注入"
    assert fragments[0].startswith("## 技能:")
    assert skill_def.body_markdown in fragments[0]


@pytest.mark.asyncio
async def test_collect_skill_fragments_skips_non_skill_refs() -> None:
    """非 skill__ 前缀的工具名直接跳过，不查库不报错"""
    with _patched_repo(_make_skill(5, "code-reviewer")):
        svc = _make_service()
        fragments = await svc._collect_skill_fragments(["web_search", "echo"])
    assert fragments == []


@pytest.mark.asyncio
async def test_collect_skill_fragments_skips_malformed_refs() -> None:
    """残缺 ref（无 id 段 / id 非数字）静默跳过"""
    with _patched_repo(_make_skill(5, "code-reviewer")):
        svc = _make_service()
        for bad in ["skill__", "skill__abc_name"]:
            fragments = await svc._collect_skill_fragments([bad])
            assert fragments == [], f"残缺 ref {bad!r} 不应注入"


@pytest.mark.asyncio
async def test_collect_skill_fragments_filters_unpublished() -> None:
    """DRAFT 或未过审的技能不注入"""
    draft = _make_skill(5, "code-reviewer")
    draft.status = SkillStatus.DRAFT
    with _patched_repo(draft):
        svc = _make_service()
        assert await svc._collect_skill_fragments(["skill__5_code-reviewer"]) == []

    rejected = _make_skill(5, "code-reviewer")
    rejected.review_status = ReviewStatus.REJECTED
    with _patched_repo(rejected):
        svc = _make_service()
        assert await svc._collect_skill_fragments(["skill__5_code-reviewer"]) == []


@pytest.mark.asyncio
async def test_collect_skill_fragments_missing_skill() -> None:
    """技能已被删除（get_by_id 返回 None）不报错不注入"""
    with _patched_repo(None):
        svc = _make_service()
        assert await svc._collect_skill_fragments(["skill__5_code-reviewer"]) == []
