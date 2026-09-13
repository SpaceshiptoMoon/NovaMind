"""core/ws/stream WS 流式推送测试。

回归背景：QA chat_stream 的 user_message/done 事件曾直塞 ORM ``created_at``
（datetime），WS ``send_json`` 裸 ``json.dumps`` 抛 ``TypeError: Object of type
datetime is not JSON serializable``，打崩整个 ASGI 连接（客户端仅看到静默断连）。
修复两层：service 层 datetime 显式 ``isoformat()``（精确）；传输层
``dumps_event`` 兜底 ``default=str``（防御）。
"""
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List

import pytest

from novamind.core.ws import dumps_event, envelope, run_stream_to_ws


class FakeWebSocket:
    """记录 send_text/send_json 调用的假 WS（不真正连 transport）。"""

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []
        self.closed = False

    async def send_text(self, text: str) -> None:
        import json

        self.sent.append(json.loads(text))

    async def send_json(self, data: Dict[str, Any]) -> None:
        # 与 starlette 行为一致：裸 json.dumps，datetime 直接抛 TypeError
        import json

        text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        self.sent.append(json.loads(text))

    async def close(self) -> None:
        self.closed = True


async def _gen_from(events: List[Dict[str, Any]]) -> AsyncGenerator[Dict[str, Any], None]:
    for e in events:
        yield e


@pytest.mark.unit
class TestDumpsEvent:
    def test_plain_event_fast_path(self) -> None:
        """纯 JSON 类型事件正常序列化，输出与 send_json 等价。"""
        event = envelope("content", {"content": "你好"})
        text = dumps_event(event)
        assert '"type":"content"' in text
        assert '"content":"你好"' in text

    def test_datetime_fallback_to_str(self) -> None:
        """事件含 datetime 时兜底 default=str 降级序列化，不抛 TypeError。"""
        event = envelope("user_message", {
            "id": 1,
            "created_at": datetime(2026, 9, 11, 12, 0, 0),
        })
        text = dumps_event(event)
        assert "2026-09-11 12:00:00" in text

    def test_mixed_payload(self) -> None:
        """混合类型（嵌套 datetime + 普通 dict/list）整体可序列化。"""
        event = envelope("done", {
            "created_at": datetime(2026, 9, 11),
            "sources": [{"index": 1, "score": 0.9}],
        })
        assert dumps_event(event)


@pytest.mark.unit
class TestRunStreamToWs:
    @pytest.mark.asyncio
    async def test_events_pushed_in_order(self) -> None:
        """事件按序推送，内容无损。"""
        ws = FakeWebSocket()
        events = [envelope("content", {"content": "a"}), envelope("done", {"id": 1})]
        await run_stream_to_ws(ws, _gen_from(events))
        assert ws.sent == events

    @pytest.mark.asyncio
    async def test_datetime_event_does_not_kill_stream(self) -> None:
        """回归：事件含 datetime 时流不中断，后续事件仍推到客户端。

        修复前该场景抛 TypeError 一路传到 ASGI 层，整个连接崩掉。
        """
        ws = FakeWebSocket()
        events = [
            envelope("user_message", {"created_at": datetime(2026, 9, 11)}),
            envelope("content", {"content": "后续内容"}),
        ]
        await run_stream_to_ws(ws, _gen_from(events))
        assert len(ws.sent) == 2
        assert ws.sent[1] == {"type": "content", "data": {"content": "后续内容"}}

    @pytest.mark.asyncio
    async def test_custom_send_fn_still_respected(self) -> None:
        """传 send_fn（locked_send 场景）时优先用调用方实现。"""
        received: List[Dict[str, Any]] = []

        async def send_fn(event: Dict[str, Any]) -> None:
            received.append(event)

        events = [envelope("heartbeat", {})]
        await run_stream_to_ws(FakeWebSocket(), _gen_from(events), send_fn=send_fn)
        assert received == events
