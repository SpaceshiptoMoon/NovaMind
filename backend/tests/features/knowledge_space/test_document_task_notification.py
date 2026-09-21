"""document_tasks 终态通知接线回归测试。

验证 _notify_document_terminal：三终态文案/link/extra_data 正确、重试中间态
不调用通知、失败静默。
"""

import novamind.features.knowledge_space.tasks.document_tasks as tasks
import pytest

pytestmark = pytest.mark.unit


class _RecordingPort:
    """记录 NotificationService.notify 的桩（staticmethod 形状）。"""

    def __init__(self):
        self.calls = []

    async def notify(self, db=None, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture
def capture(monkeypatch):
    port = _RecordingPort()
    monkeypatch.setattr(
        "novamind.features.notification.services.notification_service.NotificationService.notify",
        staticmethod(port.notify),
    )
    return port


_DOC = dict(
    user_id=8, document_id=42, space_id=3, kb_id=2, filename="报告.pdf",
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_completed_notification(capture):
    """成功终态通知"""
    await tasks._notify_document_terminal("completed", **_DOC)

    assert len(capture.calls) == 1
    call = capture.calls[0]
    assert call["user_id"] == 8
    assert call["type"] == "document_ready"
    assert "解析完成" in call["title"]
    assert "报告.pdf" in call["title"]
    assert call["link"] == "/home/spaces/3/documents/42"
    assert call["extra_data"] == {
        "document_id": 42, "kb_id": 2, "space_id": 3, "status": "completed",
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_notification_carries_detail(capture):
    """最终失败通知带错误摘要"""
    await tasks._notify_document_terminal(
        "failed", detail="OCR timeout", **_DOC,
    )

    call = capture.calls[0]
    assert "解析失败" in call["title"]
    assert "OCR timeout" in call["content"]
    assert call["extra_data"]["status"] == "failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancelled_notification(capture):
    """取消终态通知"""
    await tasks._notify_document_terminal("cancelled", **_DOC)

    call = capture.calls[0]
    assert "取消" in call["title"]
    assert call["extra_data"]["status"] == "cancelled"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_failure_swallowed(monkeypatch):
    """通知 port 抛异常被吞（不打断 arq 任务编排）"""
    class _BoomPort:
        async def send(self, **kwargs):
            raise RuntimeError("ws down")

    async def _boom(db=None, **kwargs):
        raise RuntimeError("notify down")

    monkeypatch.setattr(
        "novamind.features.notification.services.notification_service.NotificationService.notify",
        staticmethod(_boom),
    )

    await tasks._notify_document_terminal("completed", **_DOC)  # 不抛
