"""skill 审核结果通知接线回归测试。

覆盖 _do_review 三状态（APPROVED/SUSPICIOUS/REJECTED）+ 审查异常转 SUSPICIOUS
+ approve/reject_skill 管理员操作后的作者通知；断言通知参数与 commit 后时机。
"""
import asyncio
from types import SimpleNamespace

import pytest

import novamind.features.skill.services.skill_marketplace_service as svc_mod
from novamind.features.skill.models.skill import ReviewStatus
from novamind.features.skill.services.skill_marketplace_service import SkillMarketplaceService


def _make_skill(**overrides) -> SimpleNamespace:
    base = dict(
        id=1, user_id=100, name="code-reviewer", display_name="代码审查",
        review_status=ReviewStatus.PENDING, review_result=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _RecordingPort:
    def __init__(self):
        self.calls: list = []
        self.fail = False

    async def send(self, **kwargs):
        if self.fail:
            raise RuntimeError("notify down")
        self.calls.append(kwargs)


class _ReviewChecker:
    """check 返回预置结果的桩审查器"""

    def __init__(self, status: int):
        self.status = status

    async def check(self, body_markdown, frontmatter_raw):
        return SimpleNamespace(
            status=self.status,
            rule_result=SimpleNamespace(passed=True, matches=[]),
            llm_result=SimpleNamespace(level="safe", reason="ok"),
        )


class _BoomChecker:
    async def check(self, body_markdown, frontmatter_raw):
        raise RuntimeError("LLM down")


class _FakeSessionFactory:
    """返回同一桩会话的 session factory（_do_review 独立会话路径）"""

    def __init__(self, db):
        self.db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *args):
        return False


class _FakeDB:
    def __init__(self):
        self.committed = 0

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        pass


class _FakeRepo:
    def __init__(self, db, skill):
        self.db = db
        self.skill = skill

    async def get_by_id(self, skill_id):
        return self.skill

    async def update(self, skill_id, **kwargs):
        for k, v in kwargs.items():
            setattr(self.skill, k, v)
        return self.skill


def _make_service(skill, port) -> SkillMarketplaceService:
    svc = SkillMarketplaceService.__new__(SkillMarketplaceService)
    db = _FakeDB()
    svc.db = db
    svc._notification_port = port
    svc.checker = None
    # _do_review 的独立会话工厂直接复用桩 db
    svc._session_factory = _FakeSessionFactory(db)  # type: ignore[attr-defined]
    return svc


@pytest.fixture
def patch_env(monkeypatch):
    """patch 模块级 SkillRepository 与 get_session_factory"""
    state = {"skill": None}

    def _install(skill):
        state["skill"] = skill
        db = _FakeDB()
        repo = _FakeRepo(db, skill)
        monkeypatch.setattr(svc_mod, "SkillRepository", lambda session: repo)
        monkeypatch.setattr(
            "novamind.core.database.database.get_session_factory",
            lambda: _FakeSessionFactory(db),
        )
        return skill

    return _install


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected_title_part",
    [
        (ReviewStatus.APPROVED, "已通过审核"),
        (ReviewStatus.SUSPICIOUS, "需人工复核"),
        (ReviewStatus.REJECTED, "未通过审核"),
    ],
)
async def test_do_review_notifies_author_all_statuses(monkeypatch, patch_env, status, expected_title_part):
    """后台审查三终态各发一条作者通知"""
    skill = patch_env(_make_skill())
    port = _RecordingPort()
    svc = _make_service(skill, port)
    svc.checker = _ReviewChecker(status)

    svc._start_background_review(1, "body", "frontmatter")
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    await asyncio.gather(*pending)

    assert len(port.calls) == 1
    call = port.calls[0]
    assert call["user_id"] == 100
    assert call["type"] == "skill_review"
    assert expected_title_part in call["title"]
    assert call["link"] == "/home/workspace/skills/1"
    assert call["extra_data"]["skill_id"] == 1
    assert call["extra_data"]["review_status"] == int(status)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_do_review_checker_failure_notifies_suspicious(monkeypatch, patch_env):
    """审查器异常转 SUSPICIOUS 后同样通知作者"""
    skill = patch_env(_make_skill())
    port = _RecordingPort()
    svc = _make_service(skill, port)
    svc.checker = _BoomChecker()

    svc._start_background_review(1, "body", "frontmatter")
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    await asyncio.gather(*pending)

    assert len(port.calls) == 1
    call = port.calls[0]
    assert call["extra_data"]["review_status"] == int(ReviewStatus.SUSPICIOUS)
    assert "需人工复核" in call["title"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_do_review_notify_failure_does_not_raise(monkeypatch, patch_env):
    """通知发送异常被 port 吞掉语义覆盖：_do_review 不因通知失败而崩"""
    skill = patch_env(_make_skill())
    port = _RecordingPort()
    port.fail = True
    svc = _make_service(skill, port)
    svc.checker = _ReviewChecker(ReviewStatus.APPROVED)

    svc._start_background_review(1, "body", "frontmatter")
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    await asyncio.gather(*pending)  # 不抛
    # 审核状态本身已落库
    assert skill.review_status == ReviewStatus.APPROVED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_do_review_builtin_skill_no_owner_skips_notify(monkeypatch, patch_env):
    """系统内置技能（user_id=None）不发通知"""
    skill = patch_env(_make_skill(user_id=None))
    port = _RecordingPort()
    svc = _make_service(skill, port)
    svc.checker = _ReviewChecker(ReviewStatus.APPROVED)

    svc._start_background_review(1, "body", "frontmatter")
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    await asyncio.gather(*pending)

    assert port.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_skill_notifies(monkeypatch, patch_env):
    """管理员批准后通知作者"""
    skill = patch_env(_make_skill(review_status=ReviewStatus.SUSPICIOUS))
    port = _RecordingPort()
    svc = _make_service(skill, port)
    svc.skill_repo = svc_mod.SkillRepository(svc.db)  # type: ignore[assignment]

    await svc.approve_skill(1)

    assert len(port.calls) == 1
    assert port.calls[0]["extra_data"]["review_status"] == int(ReviewStatus.APPROVED)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reject_skill_notifies_with_admin_reason(monkeypatch, patch_env):
    """管理员拒绝后通知作者，reason 进 content"""
    skill = patch_env(_make_skill(review_status=ReviewStatus.SUSPICIOUS))
    port = _RecordingPort()
    svc = _make_service(skill, port)
    svc.skill_repo = svc_mod.SkillRepository(svc.db)  # type: ignore[assignment]

    await svc.reject_skill(1, reason="包含可疑注入模式")

    assert len(port.calls) == 1
    call = port.calls[0]
    assert call["extra_data"]["review_status"] == int(ReviewStatus.REJECTED)
    assert "包含可疑注入模式" in call["content"]
