"""资源清单跨代累积回归测试（pi 式 readFiles/modifiedFiles 累积的 NovaMind 适配）。

覆盖：
- 提取：从被压缩区 assistant.tool_calls 确定性提取三类资源调用，去重保序；
  非 tracking 工具、坏 JSON、缺关键字段不产生行；
- 跨代继承：旧摘要带 <compacted-resources> 段 → 新摘要合并旧清单 + 新提取
  （carried 从旧摘要解析而非新 LLM 输出——LLM 丢段不丢传承）；
- 渲染/解析往返：_resources_section 输出可被 _parse_carried_resources 完整还原；
- 静态降级（摘要 LLM 失败）不携带清单段；
- _previous_summary 与持久化形态一致（带清单段）。
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from novamind.engines.agent.memory.context_compressor import (
    ContextCompressor,
    SUMMARY_PREFIX,
)
from novamind.engines.agent.memory.interfaces import MemoryMessage
from novamind.engines.agent.memory.token_budget import TokenBudget

pytestmark = pytest.mark.unit

_BUDGET = TokenBudget("gpt-4")


def _tc(name: str, args: dict) -> dict:
    return {
        "id": f"call_{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


def _assistant_with(*tool_calls: dict) -> MemoryMessage:
    return MemoryMessage(role="assistant", content=None, tool_calls=list(tool_calls))


# ==================== 提取 ====================


def test_extract_resource_usages_dedup_and_order() -> None:
    turns = [
        MemoryMessage(role="user", content="q1"),
        _assistant_with(
            _tc("read_attachment", {"attachment_id": 1, "filename": "手册.pdf"}),
            _tc("knowledge_search", {"space_id": 2, "query": "部署要求"}),
        ),
        MemoryMessage(role="tool", content="...", tool_call_id="call_read_attachment"),
        _assistant_with(_tc("read_attachment", {"attachment_id": 1, "filename": "手册.pdf"})),
        MemoryMessage(role="user", content="q2"),
        _assistant_with(_tc("web_search", {"query": "nova release"})),
    ]
    lines = ContextCompressor._extract_resource_usages(turns)
    assert lines == [
        'read_attachment("手册.pdf")',
        'knowledge_search("部署要求")',
        'web_search("nova release")',
    ]


def test_extract_skips_non_tracking_and_malformed() -> None:
    turns = [
        _assistant_with(
            _tc("code_execution", {"code": "print(1)"}),       # 非 tracking
            _tc("read_attachment", {"attachment_id": 1}),        # 无 filename
        ),
        _assistant_with({
            "id": "c3", "type": "function",
            "function": {"name": "knowledge_search", "arguments": "{bad json"},
        }),
    ]
    assert ContextCompressor._extract_resource_usages(turns) == []


# ==================== 渲染/解析往返 ====================


def test_resources_section_roundtrip() -> None:
    lines = ['read_attachment("a.pdf")', 'web_search("q")']
    section = ContextCompressor._resources_section(lines)
    assert "<compacted-resources>" in section
    assert ContextCompressor._parse_carried_resources("前文" + section) == lines
    # 空清单不渲染
    assert ContextCompressor._resources_section([]) == ""
    # 无段时解析为空
    assert ContextCompressor._parse_carried_resources("无段摘要") == []


# ==================== compress 主流程集成 ====================


def _make_compressor_with_summary(capture: dict, old_summary: str | None = None):
    """stub 摘要 LLM + 可选旧摘要 store。"""
    async def _gen(prompt, **kwargs):
        capture["prompt"] = prompt
        return "## Active Task\n任务"
    async def factory():
        return SimpleNamespace(generate_text=_gen)
    store = None
    if old_summary is not None:
        store = SimpleNamespace(
            get_latest_summary=AsyncMock(return_value=SimpleNamespace(
                summary_text=old_summary,
            )),
            save_summary=AsyncMock(),
        )
    return ContextCompressor(
        llm_client_factory=factory, summary_store=store,
    )


def _oversized_conversation() -> list[MemoryMessage]:
    """user/assistant 交替 + 带资源调用的 assistant，总量超小预算强制压缩。

    结尾垫 tool 消息：使压缩边界落在 tail 首条为 tool 的位置——
    _pick_summary_role(head_last="assistant", tail_first="tool") 选 "user"，
    摘要作为独立消息插入 compressed[0]，断言形态稳定。
    """
    msgs: list[MemoryMessage] = []
    for i in range(8):
        msgs.append(MemoryMessage(role="user", content=f"问题{i}" + "细" * 200))
        if i == 2:
            msgs.append(_assistant_with(
                _tc("read_attachment", {"attachment_id": 9, "filename": "规范.docx"}),
            ))
            msgs.append(MemoryMessage(role="tool", content="附件内容" * 100,
                                      tool_call_id="call_read_attachment"))
        else:
            msgs.append(MemoryMessage(role="assistant", content="答" * 200))
    # 尾部 tool 消息（对齐边界用的 dummy call_id，_sanitise_tool_pairs 会清孤儿）
    msgs.append(_assistant_with(_tc("code_execution", {"code": "1+1"})))
    msgs.append(MemoryMessage(role="tool", content="2", tool_call_id="call_code_execution"))
    return msgs


@pytest.mark.asyncio
async def test_compress_appends_and_carries_resources() -> None:
    """首次压缩：摘要尾部追加本代新提取清单；持久化/缓存形态带段。

    注：摘要消息可能走独立消息分支（带 system_injection 元数据）或双角色
    冲突的合并分支（摘要并入 tail[0]）——断言以「含 <system-compaction> 的
    消息携带清单段」为准，不绑定分支形态。
    """
    capture: dict = {}
    comp = _make_compressor_with_summary(capture)
    msgs = _oversized_conversation()

    compressed, did, ratio = await comp.compress(
        msgs, available_tokens=1500, token_budget=_BUDGET, conversation_id=1,
    )
    assert did is True
    summary_msg = next(
        m for m in compressed if (m.content or "").startswith("<system-compaction>")
    )
    assert '<compacted-resources>' in summary_msg.content
    assert 'read_attachment("规范.docx")' in summary_msg.content
    # _previous_summary 与持久化形态一致（含清单段），下次迭代不丢段
    assert comp._previous_summary is not None
    assert "<compacted-resources>" in comp._previous_summary


@pytest.mark.asyncio
async def test_compress_merges_carried_from_old_summary() -> None:
    """迭代压缩：旧摘要已携带的资源行保留、新提取行合并、去重。"""
    capture: dict = {}
    old = (
        SUMMARY_PREFIX + "\n## Active Task\n旧任务\n"
        '<compacted-resources>\n'
        '- read_attachment("旧文件.pdf")\n'
        "- knowledge_search(\"旧查询\")\n"
        "</compacted-resources>"
    )
    comp = _make_compressor_with_summary(capture, old_summary=old)
    msgs = _oversized_conversation()
    # 追加本代新调用（与旧清单部分重叠）
    msgs.insert(3, _assistant_with(
        _tc("read_attachment", {"attachment_id": 9, "filename": "规范.docx"}),
        _tc("web_search", {"query": "旧查询"}),  # query 与旧 knowledge_search 不同行——不合并
    ))

    compressed, did, _ = await comp.compress(
        msgs, available_tokens=1500, token_budget=_BUDGET, conversation_id=1,
    )
    assert did is True
    content = compressed[0].content
    assert 'read_attachment("旧文件.pdf")' in content   # 旧清单继承
    assert 'knowledge_search("旧查询")' in content       # 旧清单继承
    assert 'read_attachment("规范.docx")' in content     # 本代新提取
    # 继承行排在新提取行之前
    assert content.index('read_attachment("旧文件.pdf")') < content.index('read_attachment("规范.docx")')


@pytest.mark.asyncio
async def test_static_fallback_carries_no_resources_section() -> None:
    """摘要 LLM 失败（静态降级）→ 不追加清单段（防止破坏解析）。"""
    async def _fail_gen(prompt, **kwargs):
        raise RuntimeError("LLM 不可用")
    async def factory():
        return SimpleNamespace(generate_text=_fail_gen)
    comp = ContextCompressor(llm_client_factory=factory)
    msgs = _oversized_conversation()

    compressed, did, _ = await comp.compress(
        msgs, available_tokens=1500, token_budget=_BUDGET, conversation_id=1,
    )
    assert did is True
    assert "<compacted-resources>" not in compressed[0].content


@pytest.mark.asyncio
async def test_db_persists_section_for_cross_request_carryover() -> None:
    """DB 持久化存带清单段的最终形态（跨请求传承的唯一载体）。

    compressor 每请求新建实例，_previous_summary 内存缓存帮不上下一次请求——
    若 DB 只存裸 summary，新实例从 DB 加载旧摘要时清单段已丢，跨代传承断裂。
    """
    saved: dict = {}

    async def _gen(prompt, **kwargs):
        return "## Active Task\n任务"

    async def factory():
        return SimpleNamespace(generate_text=_gen)

    async def save_summary(**kwargs):
        saved.update(kwargs)

    store = SimpleNamespace(
        get_latest_summary=AsyncMock(return_value=None),
        save_summary=AsyncMock(side_effect=save_summary),
    )
    comp = ContextCompressor(llm_client_factory=factory, summary_store=store)
    msgs = _oversized_conversation()

    await comp.compress(
        msgs, available_tokens=1500, token_budget=_BUDGET, conversation_id=1,
    )
    assert saved.get("summary_text") is not None
    assert "<compacted-resources>" in saved["summary_text"]
    assert 'read_attachment("规范.docx")' in saved["summary_text"]
    # token_count 口径与存储文本一致（按带段最终形态计）
    assert saved["token_count"] == _BUDGET.count_text_tokens(saved["summary_text"])
