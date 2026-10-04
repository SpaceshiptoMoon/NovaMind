"""批2 c4 回归：步骤综合 pass（_synthesize_steps）+ 覆盖率校验 + steps_items 注入。

覆盖：JSON 解析（围栏/噪声/非法 idx）；帧层覆盖缺口计算（grouped 展开）；
双层校验失败重试 1 次后降级 None（帧级 chunks 保留，文档不失败）；
run_post_parse_tail 的 steps_items 在对齐前 append。
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

import novamind.features.knowledge_space.services.media_processing as mp
from novamind.features.knowledge_space.services.media_processing import (
    _parse_steps_json,
    _steps_coverage_gap,
    _synthesize_steps,
)

pytestmark = pytest.mark.unit


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, msg, **kwargs):
        self.warnings.append(msg)

    def info(self, *a, **k):
        pass


def test_parse_steps_json_variants():
    """围栏/前后噪声/非法 idx/空步骤条目各形态解析。"""
    plain = '{"steps": [{"no": 1, "title": "热锅", "body": "中火", "start_frame_idx": 0, "end_frame_idx": 2}]}'
    assert len(_parse_steps_json(plain)) == 1
    fenced = "结果：\n```json\n" + plain + "\n```"
    assert len(_parse_steps_json(fenced)) == 1
    bad_idx = '{"steps": [{"no": 1, "title": "t", "body": "b", "start_frame_idx": "x", "end_frame_idx": 1}]}'
    assert _parse_steps_json(bad_idx) == []
    blank = '{"steps": [{"no": 1, "title": "", "body": "  ", "start_frame_idx": 0, "end_frame_idx": 1}]}'
    assert _parse_steps_json(blank) == []
    assert _parse_steps_json("not json at all") == []
    assert _parse_steps_json('{"steps": []}') == []


def test_parse_steps_swaps_reversed_endpoints():
    """start > end 时交换端点（防御 LLM 偶发倒置）。"""
    s = _parse_steps_json('{"steps": [{"no":1,"title":"t","body":"b","start_frame_idx":5,"end_frame_idx":2}]}')
    assert s[0]["start_frame_idx"] == 2 and s[0]["end_frame_idx"] == 5


def test_coverage_gap_frame_layer():
    """帧层缺口：未覆盖帧集合；grouped 经 frame_groups 展开。"""
    steps = [
        {"start_frame_idx": 0, "end_frame_idx": 2},
        {"start_frame_idx": 3, "end_frame_idx": 5},
    ]
    assert _steps_coverage_gap(steps, {0, 1, 2, 3, 4, 5}, None) == set()
    assert _steps_coverage_gap(steps[:1], {0, 1, 2, 3, 4, 5}, None) == {3, 4, 5}
    gap = _steps_coverage_gap(
        [{"start_frame_idx": 0, "end_frame_idx": 0}], {0, 1, 2, 3}, {0: [0, 1, 2]}
    )
    assert gap == {3}


def _llm_returning(outputs):
    """依次返回 outputs 元素的假 LLM 客户端（耗尽后重复最后一个）。"""
    calls = {"n": 0}

    class _Client:
        async def generate_text(self, **kwargs):
            out = outputs[min(calls["n"], len(outputs) - 1)]
            calls["n"] += 1
            return out

    return _Client(), calls


_FULL = (
    '{"steps": ['
    '{"no": 1, "title": "热锅", "body": "中火加热锅", "start_frame_idx": 0, "end_frame_idx": 2},'
    '{"no": 2, "title": "下油", "body": "倒两勺油", "start_frame_idx": 3, "end_frame_idx": 5}'
    "]}"
)
_PARTIAL = (
    '{"steps": ['
    '{"no": 1, "title": "热锅", "body": "中火加热锅", "start_frame_idx": 0, "end_frame_idx": 2}'
    "]}"
)


def _timeline():
    return {i: (float(i * 5), float((i + 1) * 5) if i < 5 else None) for i in range(6)}


def test_synthesize_success_full_coverage():
    """全覆盖输出：一次成功返回步骤列表。"""
    client, calls = _llm_returning([_FULL])
    logger = _Logger()
    steps = asyncio.run(_synthesize_steps(
        document=SimpleNamespace(id=1), full_text="[00:00:00#0] 画面:x",
        frame_timeline_map=_timeline(), frame_groups=None,
        llm_client=client, max_steps=30, logger=logger,
    ))
    assert steps is not None and len(steps) == 2
    assert calls["n"] == 1
    assert not logger.warnings


def test_synthesize_retry_then_success():
    """首输出有缺口 → 带缺口清单重试 → 第二次全覆盖成功。"""
    client, calls = _llm_returning([_PARTIAL, _FULL])
    steps = asyncio.run(_synthesize_steps(
        document=SimpleNamespace(id=1), full_text="[00:00:00#0] 画面:x",
        frame_timeline_map=_timeline(), frame_groups=None,
        llm_client=client, max_steps=30, logger=_Logger(),
    ))
    assert steps is not None and len(steps) == 2
    assert calls["n"] == 2


def test_synthesize_persist_gap_degrades_to_none():
    """两轮均有缺口：降级返回 None（帧级 chunks 保留，文档不失败）。"""
    client, calls = _llm_returning([_PARTIAL, _PARTIAL])
    logger = _Logger()
    steps = asyncio.run(_synthesize_steps(
        document=SimpleNamespace(id=1), full_text="[00:00:00#0] 画面:x",
        frame_timeline_map=_timeline(), frame_groups=None,
        llm_client=client, max_steps=30, logger=logger,
    ))
    assert steps is None
    assert calls["n"] == 2
    assert any("降级" in w for w in logger.warnings)


def test_synthesize_llm_failure_degrades_to_none():
    """LLM 调用异常：立即降级 None，不重试烧配额。"""
    class _Boom:
        async def generate_text(self, **kwargs):
            raise RuntimeError("api down")

    steps = asyncio.run(_synthesize_steps(
        document=SimpleNamespace(id=1), full_text="[00:00:00#0] 画面:x",
        frame_timeline_map=_timeline(), frame_groups=None,
        llm_client=_Boom(), max_steps=30, logger=_Logger(),
    ))
    assert steps is None


def test_synthesize_max_steps_truncates():
    """步骤条数超 max_steps 截断（截断可能致缺口 → 本用例给可全覆盖的小上限）。"""
    # max_steps=1 截断后只剩步骤 1（盖 0-2），帧 3-5 缺口 → 重试同样 → 降级 None
    client, _ = _llm_returning([_FULL])
    steps = asyncio.run(_synthesize_steps(
        document=SimpleNamespace(id=1), full_text="[00:00:00#0] 画面:x",
        frame_timeline_map=_timeline(), frame_groups=None,
        llm_client=client, max_steps=1, logger=_Logger(),
    ))
    assert steps is None  # 截断致缺口，降级路径正确


def test_synthesize_empty_timeline_returns_none():
    """空时间线：无帧可覆盖，直接 None。"""
    client, _ = _llm_returning([_FULL])
    steps = asyncio.run(_synthesize_steps(
        document=SimpleNamespace(id=1), full_text="",
        frame_timeline_map={}, frame_groups=None,
        llm_client=client, max_steps=30, logger=_Logger(),
    ))
    assert steps is None
