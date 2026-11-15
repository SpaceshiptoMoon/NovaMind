"""B4 缺② 调用点回归测试（矛盾检测部分）。

验证 contradiction_detector 的 JSON 提取加固：
1. 围栏 JSON 判矛盾成立；非 JSON 返回 None（宁漏勿误语义不变）；
2. 请求带 response_format=json_object。
（原文件还覆盖 grade_retrier / testset_generation，二者已随 2026-11-15
工作台剥离移除，对应测试类随之删除。）
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class FakeLLM:
    """记录调用参数并按序回放响应的最小 LLM 桩。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate_text(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _run(coro):
    import asyncio

    return asyncio.run(coro)


class TestContradictionDetector:
    def _check(self, llm: FakeLLM):
        from novamind.features.knowledge_ops.services.contradiction_detector import (
            _llm_check_contradiction,
        )
        return _run(_llm_check_contradiction(llm, "内容A", "内容B"))

    def test_fenced_contradiction_detected(self):
        """正例：围栏包裹的矛盾判定仍成立（旧 re 清洗实现可过，收敛后不回归）。"""
        llm = FakeLLM(['```json\n{"contradiction": true, "reason": "数字冲突 7 天 vs 15 天"}\n```'])
        assert self._check(llm) == "数字冲突 7 天 vs 15 天"
        assert llm.calls[0]["response_format"] == {"type": "json_object"}

    def test_nested_reason_with_brace(self):
        """reason 内嵌 } 的响应：旧 re.sub+loads 实现会炸，extract_json_obj 兜住。"""
        llm = FakeLLM(['{"contradiction": true, "reason": "A 说支持 } 结尾，B 说不支持"}'])
        assert "不支持" in self._check(llm)

    def test_non_contradiction_returns_none(self):
        llm = FakeLLM(['{"contradiction": false, "reason": "语义一致"}'])
        assert self._check(llm) is None

    def test_garbage_returns_none_mercy_skip(self):
        """宁漏勿误：垃圾输出返回 None，不建建议。"""
        llm = FakeLLM(["完全不是 JSON"])
        assert self._check(llm) is None
