"""技能广场服务层权限与状态机回归测试。

覆盖两个 P0 修复：
1. ``update_skill_version``：已发布技能更新版本后，除 status 回 DRAFT 外
   还须同步回退 visibility=PRIVATE —— 否则 get_skill/download_skill 仅按
   visibility 判定，任何人可查看/下载未经审查的新版内容。
2. ``install_skill``：系统级预置 Agent（user_id=None）仅管理员可安装，
   与 uninstall_skill 的管理口径一致 —— 否则任意用户可篡改系统 Agent 的
   enabled_tools。
"""
import asyncio
import io
import zipfile
from types import SimpleNamespace

import pytest

from novamind.features.skill.exceptions import SkillAccessDeniedError
from novamind.features.skill.models.skill import (
    SkillSource, SkillStatus, SkillVisibility, ReviewStatus,
)
from novamind.features.skill.services.skill_marketplace_service import SkillMarketplaceService


def _make_skill(**overrides) -> SimpleNamespace:
    base = dict(
        id=1,
        user_id=100,
        name="code-reviewer",
        display_name="代码审查",
        description="d",
        version=1,
        status=SkillStatus.PUBLISHED,
        visibility=SkillVisibility.PUBLIC,
        review_status=ReviewStatus.APPROVED,
        skill_source=SkillSource.CUSTOM,
        allowed_tools=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeAgentRegistryPort:
    """按 agent_id 返回预置 Agent 摘要，记录 enabled_tools 更新"""

    def __init__(self, agents: dict):
        self._agents = agents
        self.updated_tools: dict = {}

    async def get_agent(self, agent_id: int):
        return self._agents.get(agent_id)

    async def update_enabled_tools(self, agent_id: int, tools: list) -> None:
        self.updated_tools[agent_id] = tools


class _FakeSkillRepo:
    """记录 update kwargs 的桩仓储"""

    def __init__(self, skill):
        self.skill = skill
        self.updates: dict = {}

    async def get_by_id(self, skill_id):
        return self.skill

    async def update(self, skill_id, **kwargs):
        self.updates.update(kwargs)
        return self.skill

    async def increment_install_count(self, skill_id):
        pass


class _FakeInstallRepo:
    async def get_by_skill_and_agent(self, skill_id, agent_id):
        return None

    async def create(self, **kwargs):
        return SimpleNamespace(**kwargs)

    async def list_by_agent(self, agent_id):
        return []


class _FakeDB:
    async def commit(self):
        pass


def _make_service(skill, port) -> SkillMarketplaceService:
    svc = SkillMarketplaceService.__new__(SkillMarketplaceService)
    svc.skill_repo = _FakeSkillRepo(skill)
    svc.version_repo = None
    svc.review_repo = None
    svc.install_repo = _FakeInstallRepo()
    svc.db = _FakeDB()
    svc._agent_registry_port = port
    svc._notification_port = None
    svc.checker = None
    svc.minio = None
    svc.model_config_service = None
    return svc


def _skill_zip(name: str = "code-reviewer") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", f"---\nname: {name}\ndescription: d\n---\n\nnew body")
    return buf.getvalue()


async def _fake_upload(skill_id, version, extracted):
    return []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_published_skill_resets_visibility_to_private():
    """已发布技能更新版本：status→DRAFT 且 visibility→PRIVATE（否则审查期内容可被公众下载）"""
    skill = _make_skill(status=SkillStatus.PUBLISHED, visibility=SkillVisibility.PUBLIC)
    svc = _make_service(skill, _FakeAgentRegistryPort({}))

    async def _vr_create(**kwargs):
        return None

    svc.version_repo = SimpleNamespace()
    svc.version_repo.create = _vr_create
    svc._upload_skill_files = _fake_upload  # type: ignore[assignment]

    await svc.update_skill_version(user_id=100, skill_id=1, zip_bytes=_skill_zip())

    repo: _FakeSkillRepo = svc.skill_repo
    assert repo.updates["status"] == SkillStatus.DRAFT
    assert repo.updates["visibility"] == SkillVisibility.PRIVATE


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_draft_skill_keeps_visibility():
    """草稿技能更新版本：不触碰 status/visibility"""
    skill = _make_skill(status=SkillStatus.DRAFT, visibility=SkillVisibility.PRIVATE)
    svc = _make_service(skill, _FakeAgentRegistryPort({}))

    async def _vr_create(**kwargs):
        return None

    svc.version_repo = SimpleNamespace()
    svc.version_repo.create = _vr_create
    svc._upload_skill_files = _fake_upload  # type: ignore[assignment]

    await svc.update_skill_version(user_id=100, skill_id=1, zip_bytes=_skill_zip())

    repo: _FakeSkillRepo = svc.skill_repo
    assert "status" not in repo.updates
    assert "visibility" not in repo.updates


@pytest.mark.unit
@pytest.mark.asyncio
async def test_install_to_system_agent_requires_admin():
    """普通用户向系统级 Agent（user_id=None）安装技能被拒"""
    skill = _make_skill()
    port = _FakeAgentRegistryPort({7: SimpleNamespace(id=7, user_id=None, enabled_tools=[])})
    svc = _make_service(skill, port)

    with pytest.raises(SkillAccessDeniedError):
        await svc.install_skill(user_id=100, skill_id=1, agent_id=7, is_admin=False)
    assert 7 not in port.updated_tools, "拒绝时不得修改 enabled_tools"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_install_to_system_agent_admin_allowed():
    """管理员可向系统级 Agent 安装技能，enabled_tools 正确追加 skill ref"""
    skill = _make_skill()
    port = _FakeAgentRegistryPort({7: SimpleNamespace(id=7, user_id=None, enabled_tools=[])})
    svc = _make_service(skill, port)

    await svc.install_skill(user_id=1, skill_id=1, agent_id=7, is_admin=True)
    assert port.updated_tools[7] == ["skill__1_code-reviewer"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_install_to_other_users_agent_denied():
    """他人私有 Agent 安装被拒（回归原有语义）"""
    skill = _make_skill()
    port = _FakeAgentRegistryPort({8: SimpleNamespace(id=8, user_id=200, enabled_tools=[])})
    svc = _make_service(skill, port)

    with pytest.raises(SkillAccessDeniedError):
        await svc.install_skill(user_id=100, skill_id=1, agent_id=8, is_admin=False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_install_to_own_agent_appends_skill_ref():
    """自有 Agent 安装成功，enabled_tools 追加 skill ref（回归原有语义）"""
    skill = _make_skill()
    port = _FakeAgentRegistryPort({9: SimpleNamespace(id=9, user_id=100, enabled_tools=[])})
    svc = _make_service(skill, port)

    await svc.install_skill(user_id=100, skill_id=1, agent_id=9, is_admin=False)
    assert port.updated_tools[9] == ["skill__1_code-reviewer"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reject_persists_admin_reason_without_review_result():
    """review_result 为 None 时管理员拒绝原因不丢失（原实现静默丢弃）"""
    skill = _make_skill(review_status=ReviewStatus.SUSPICIOUS, review_result=None)
    svc = _make_service(skill, _FakeAgentRegistryPort({}))

    await svc.reject_skill(skill_id=1, reason="包含可疑注入模式")

    repo: _FakeSkillRepo = svc.skill_repo
    assert repo.updates["review_status"] == ReviewStatus.REJECTED
    assert repo.updates["review_result"] == {"admin_reason": "包含可疑注入模式"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reject_merges_admin_reason_into_existing_result():
    """已有 review_result 时管理员原因合并写入，原审查数据保留"""
    skill = _make_skill(
        review_status=ReviewStatus.SUSPICIOUS,
        review_result={"rules": {"passed": True, "matches": []}, "llm": {"level": "suspicious", "reason": "r"}},
    )
    svc = _make_service(skill, _FakeAgentRegistryPort({}))

    await svc.reject_skill(skill_id=1, reason="人工确认")

    repo: _FakeSkillRepo = svc.skill_repo
    result = repo.updates["review_result"]
    assert result["admin_reason"] == "人工确认"
    assert result["llm"]["level"] == "suspicious", "原 LLM 审查数据应保留"


# ==================== 后台审查失败兜底 ====================

class _ExplodingChecker:
    """check 必抛异常的审查器"""

    async def check(self, body_markdown, frontmatter_raw):
        raise RuntimeError("LLM 连接失败")


class _CapturingRepo:
    """捕获 update kwargs 的桩仓储"""

    last_update: dict = {}

    async def update(self, skill_id, **kwargs):
        type(self).last_update = {"skill_id": skill_id, **kwargs}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_background_review_failure_marks_suspicious(monkeypatch):
    """后台审查任务异常时技能转 SUSPICIOUS（人工出口），而非永久卡 PENDING"""
    import novamind.features.skill.services.skill_marketplace_service as svc_mod

    updated: dict = {}

    class _Repo:
        async def update(self, skill_id, **kwargs):
            updated.update(kwargs)

    class _SessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        svc_mod, "SkillRepository", lambda db: _Repo(), raising=False,
    )
    monkeypatch.setattr(
        "novamind.core.database.database.get_session_factory", lambda: _SessionFactory(),
    )

    svc = _make_service(_make_skill(), _FakeAgentRegistryPort({}))
    svc.checker = _ExplodingChecker()

    svc._start_background_review(1, "body", "frontmatter")
    # _start_background_review 用 ensure_future 起任务，取到它并等待完成
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    await asyncio.gather(*pending)

    assert updated.get("review_status") == ReviewStatus.SUSPICIOUS
    assert "自动审查失败" in updated.get("review_result", {}).get("error", "")
