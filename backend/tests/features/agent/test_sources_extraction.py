"""引用来源链路回归测试（对齐 QA SourceRef）。

背景：引用面板曾长期空数据，两个同根因 bug——
1. _handle_done 收 sources 参数但 save_message extra 不落库（只塞 WS 事件），
   运行中有、刷新即空；
2. knowledge_search 结果 filename 已扁平化到顶层，提取器仍读 file_info 包装，
   document_name 恒空串。

覆盖：双形态提取（扁平/旧包装协议）、_handle_done 落库 extra.sources。
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from novamind.engines.agent.agent_engine import AgentEvent
from novamind.features.agent.services.chat_service import AgentChatService

pytestmark = pytest.mark.unit


def _svc() -> AgentChatService:
    return AgentChatService.__new__(AgentChatService)


def _ks_result(results: list[dict]) -> str:
    """knowledge_search 真实结果形态（扁平 filename / content / score / chunk_id）。"""
    return json.dumps(
        {
            "query": "知识库", "total": len(results), "insufficient_evidence": False,
            "rewritten_query": "x", "results": results,
            "chapters": [], "video_overviews": [],
        },
        ensure_ascii=False,
    )


def _extract(results: list[dict]) -> list[dict]:
    svc = _svc()
    ev = AgentEvent(
        "tool_result", {"tool_name": "knowledge_search", "result": _ks_result(results)}
    )
    collected: list[dict] = []
    svc._extract_sources(ev, collected)
    return collected


# ==================== 双形态提取 ====================


def test_extract_flat_filename_form():
    """正：现役扁平形态（filename 在顶层）提取 document_name 非空——字段漂移回归。"""
    out = _extract([
        {"content": "片段", "score": 0.83, "document_id": 1008, "chunk_id": 42,
         "filename": "office_demo_2.mp4", "chapter": None},
    ])
    assert len(out) == 1
    assert out[0]["kind"] == "kb"
    assert out[0]["document_name"] == "office_demo_2.mp4"
    assert out[0]["score"] == 0.83 and out[0]["chunk_id"] == 42


def test_extract_file_info_wrapped_form_still_supported():
    """反：旧 file_info 包装协议不误伤（QA SourceRef 旧形态仍提取出名字）。"""
    out = _extract([
        {"content": "片段", "score": 0.6, "document_id": 5, "chunk_id": 9,
         "file_info": {"filename": "旧协议.md"}, "chapter": None},
    ])
    assert out[0]["document_name"] == "旧协议.md"


def test_extract_without_any_filename_falls_back_empty_name():
    """无名结果仍产出条目（document_name 空 → 前端显示「来源 N」兜底），不丢 index/score。"""
    out = _extract([{"content": "匿名片段", "score": 0.4}])
    assert out[0]["document_name"] == ""
    assert out[0]["index"] == 1 and out[0]["score"] == 0.4


def test_extract_web_form_unchanged():
    """web_search 分支形态不受本次修改影响。"""
    svc = _svc()
    ev = AgentEvent("tool_result", {
        "tool_name": "web_search",
        "result": json.dumps({"results": [{"title": "T", "url": "https://x", "snippet": "s"}]}),
    })
    collected: list[dict] = []
    svc._extract_sources(ev, collected)
    assert collected[0]["kind"] == "web" and collected[0]["document_name"] == "T"


# ==================== done 落库 extra.sources ====================


@pytest.mark.asyncio
async def test_handle_done_persists_sources_in_extra():
    """正：sources 非空时写入 assistant extra（刷新/历史回放引用面板的数据源）。"""
    svc = _svc()
    conv = SimpleNamespace(id=1, user_id=7, title="已有标题", message_count=9, extra_config={})
    saved: dict = {}
    svc.agent_service = SimpleNamespace(
        save_message=AsyncMock(side_effect=lambda **kw: saved.update(kw) or SimpleNamespace(id=99)),
        update_session_stats=AsyncMock(),
    )
    svc.session_repo = SimpleNamespace(update=AsyncMock())
    svc.db = SimpleNamespace(refresh=AsyncMock(), commit=AsyncMock())

    sources = [{"index": 1, "kind": "kb", "document_name": "a.md"}]
    event = AgentEvent("done", {"total_tokens": 100})
    await svc._handle_done(event, conv, "问题", "回答", sources=sources, iteration=1)

    assert saved["extra"]["sources"] == sources
    assert event.data["sources"] == sources  # WS 事件仍携带（运行中前端渲染源）


@pytest.mark.asyncio
async def test_handle_done_empty_sources_keeps_extra_clean():
    """反：无引用时 extra 不带空 sources 键（保持 usage/duration 原口径）。"""
    svc = _svc()
    conv = SimpleNamespace(id=1, user_id=7, title="已有标题", message_count=9, extra_config={})
    saved: dict = {}
    svc.agent_service = SimpleNamespace(
        save_message=AsyncMock(side_effect=lambda **kw: saved.update(kw) or SimpleNamespace(id=99)),
        update_session_stats=AsyncMock(),
    )
    svc.session_repo = SimpleNamespace(update=AsyncMock())
    svc.db = SimpleNamespace(refresh=AsyncMock(), commit=AsyncMock())

    event = AgentEvent("done", {"total_tokens": 100, "last_iteration_usage": {"total_tokens": 100}})
    await svc._handle_done(event, conv, "问题", "回答", sources=None, iteration=1)

    assert "sources" not in (saved["extra"] or {})
    assert saved["extra"]["usage"] == {"total_tokens": 100}
