"""resume _split_sections 解析降级重试回归测试。

背景：原实现裸 json.loads(extract_json_str(...)) 无 try——围栏/噪声输出
直接上抛中断整个简历解析任务。修复后复用 _parse_section 的降级样板：
两轮重试（第二轮去 response_format + prompt 加显式约束）；两轮均失败仍
抛出（静默空 sections 是"错误结果"，保持原失败语义）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.resume.resume_parser import ResumeParser
from novamind.shared.logging import get_logger

pytestmark = pytest.mark.unit


class ScriptedLLM:
    """按脚本返回、记录每次调用的桩。"""

    def __init__(self, responses: list[str | Exception]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def generate_text(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _StubPrompts:
    def format(self, key: str, **kwargs: str) -> str:
        return f"[{key}]"


def _parser(llm: ScriptedLLM) -> ResumeParser:
    return ResumeParser(
        llm,  # type: ignore[arg-type]
        prompt_provider=_StubPrompts(),  # type: ignore[arg-type]
        logger=get_logger("test-resume-split"),
    )


_VALID = '{"sections": [{"type": "education", "start_line": 1, "end_line": 2}]}'
_RUN = asyncio.run


class TestSplitSectionsRetry:
    def test_first_round_fenced_succeeds(self):
        """正例：围栏输出首轮即成功（旧实现直接上抛）。"""
        llm = ScriptedLLM([f'```json\n{_VALID}\n```'])
        sections = _RUN(_parser(llm)._split_sections("第一行\n第二行"))
        assert "education" in sections

    def test_first_garbage_second_succeeds_without_format(self):
        """首轮垃圾 → 第二轮重试：无 response_format + prompt 追加约束。"""
        llm = ScriptedLLM(["完全不是 JSON", _VALID])
        sections = _RUN(_parser(llm)._split_sections("第一行\n第二行"))
        assert "education" in sections
        assert len(llm.calls) == 2
        assert llm.calls[0]["response_format"] == {"type": "json_object"}
        assert llm.calls[1]["response_format"] is None
        assert "请只输出合法 JSON" in llm.calls[1]["prompt"]

    def test_both_fail_raises(self):
        """反例：两轮全失败仍抛（不静默返回空 sections）。"""
        llm = ScriptedLLM(["垃圾1", "垃圾2"])
        with pytest.raises(Exception):
            _RUN(_parser(llm)._split_sections("第一行"))
        assert len(llm.calls) == 2
