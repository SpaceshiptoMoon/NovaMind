"""research_done / resume_completed / password_reset 通知接线回归测试。"""
import pytest

import novamind.features.app.tasks.resume_tasks as resume_tasks


class _RecordingPort:
    def __init__(self):
        self.calls = []

    async def send(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture
def capture(monkeypatch):
    port = _RecordingPort()
    monkeypatch.setattr(
        "novamind.features.notification.adapters.notification_port_adapter.as_notification_port",
        lambda db: port,
    )
    return port


# ==================== research_done ====================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_research_done(capture):
    """DeepResearchService._notify_research_done：commit 后发通知，参数完整"""
    from types import SimpleNamespace
    from novamind.features.deep_research.services.deep_research_service import (
        DeepResearchService,
    )

    svc = DeepResearchService.__new__(DeepResearchService)
    svc._notification_port = capture
    svc.logger = SimpleNamespace(warning=lambda *a, **k: None)

    ctx = SimpleNamespace(
        user_id=5, session_id="sess-abc", space_id=3,
        research_topic="RAG 检索优化",
        params=SimpleNamespace(query="RAG"),
    )
    await svc._notify_research_done(ctx, elapsed_seconds=120)

    assert len(capture.calls) == 1
    call = capture.calls[0]
    assert call["user_id"] == 5
    assert call["type"] == "research_done"
    assert "RAG 检索优化" in call["title"]
    assert "120" in call["content"]
    assert call["link"] == "/home/workspace/research/3/history"
    assert call["extra_data"]["session_id"] == "sess-abc"
    assert call["extra_data"]["elapsed_seconds"] == 120


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_research_done_topic_fallback(capture):
    """research_topic 为空时回退 params.query"""
    from types import SimpleNamespace
    from novamind.features.deep_research.services.deep_research_service import (
        DeepResearchService,
    )

    svc = DeepResearchService.__new__(DeepResearchService)
    svc._notification_port = capture
    svc.logger = SimpleNamespace(warning=lambda *a, **k: None)

    ctx = SimpleNamespace(
        user_id=5, session_id="s", space_id=1,
        research_topic=None,
        params=SimpleNamespace(query="向量数据库对比"),
    )
    await svc._notify_research_done(ctx, elapsed_seconds=30)

    assert "向量数据库对比" in capture.calls[0]["title"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_research_done_port_none_noop():
    """未注入 port 时不发通知不报错"""
    from types import SimpleNamespace
    from novamind.features.deep_research.services.deep_research_service import (
        DeepResearchService,
    )

    svc = DeepResearchService.__new__(DeepResearchService)
    svc._notification_port = None

    ctx = SimpleNamespace(
        user_id=5, session_id="s", space_id=1, research_topic="t",
        params=SimpleNamespace(query="q"),
    )
    await svc._notify_research_done(ctx, elapsed_seconds=1)  # 不抛


# ==================== resume_completed ====================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_resume_completed(capture):
    """成功终态：link 指向会话详情页"""
    await resume_tasks._notify_resume_terminal(
        "completed", user_id=11, session_id="rs-1", filename="张三简历.pdf",
    )

    call = capture.calls[0]
    assert call["user_id"] == 11
    assert call["type"] == "resume_completed"
    assert "张三简历.pdf" in call["content"]
    assert call["link"] == "/home/apps/resume/session/rs-1"
    assert call["extra_data"]["status"] == "completed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_resume_failed(capture):
    """最终失败终态：link 指向历史列表"""
    await resume_tasks._notify_resume_terminal(
        "failed", user_id=11, session_id="rs-1", filename="张三简历.pdf",
    )

    call = capture.calls[0]
    assert "失败" in call["title"]
    assert call["link"] == "/home/apps/resume/history"
    assert call["extra_data"]["status"] == "failed"
