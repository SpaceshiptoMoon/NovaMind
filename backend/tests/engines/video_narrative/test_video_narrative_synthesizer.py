"""视频叙事合成引擎回归测试：Map-Reduce 合成、降级、JSON 容错、markdown 渲染。"""
import pytest

from novamind.engines.video_narrative.service import (
    NarrativeBlock,
    NarrativeSynthesisError,
    VideoNarrativeSynthesizer,
    _parse_json_object,
)

pytestmark = pytest.mark.unit


class ScriptedLLM:
    """按 prompt 关键词路由响应的假 LLM：Map 批返回 JSON，Reduce 返回梗概。"""

    def __init__(self, map_responses=None, overview="全片梗概。", fail_map_batches=()):
        self.map_responses = list(map_responses or [])
        self.overview = overview
        self.fail_map_batches = set(fail_map_batches)
        self.calls = []

    async def generate_text(self, **kwargs):
        prompt = kwargs.get("prompt", "")
        self.calls.append(prompt)
        if "章节摘要" in prompt:
            idx = len([c for c in self.calls if "章节摘要" in c]) - 1
            if idx in self.fail_map_batches:
                raise RuntimeError("map batch failure")
            return self.map_responses[idx] if idx < len(self.map_responses) else \
                '{"title": "默认章节", "summary": "默认摘要。"}'
        return self.overview


def _blocks(n=5):
    return [NarrativeBlock(start_time=i * 10.0, end_time=(i + 1) * 10.0,
                           text=f"描述{i}", chunk_index=i) for i in range(n)]


@pytest.mark.asyncio
async def test_synthesize_maps_batches_and_keeps_chunk_indices():
    """正例：5 块按 batch_size=2 分 3 批，章节保留原始块索引且按时间升序。"""
    llm = ScriptedLLM(map_responses=[
        '{"title": "章一", "summary": "s1"}',
        '{"title": "章二", "summary": "s2"}',
        '{"title": "章三", "summary": "s3"}',
    ])
    doc = await VideoNarrativeSynthesizer(llm, batch_size=2).synthesize(_blocks(5))
    assert [c.title for c in doc.chapters] == ["章一", "章二", "章三"]
    assert doc.chapters[0].chunk_indices == [0, 1]
    assert doc.chapters[2].chunk_indices == [4]
    assert doc.overview == "全片梗概。"


@pytest.mark.asyncio
async def test_map_batch_failure_degrades_without_aborting():
    """中间批失败：其余章节保留，整体不失败（降级跳过该时间窗）。"""
    llm = ScriptedLLM(map_responses=[
        '{"title": "章A", "summary": "a"}',
        '',  # 空响应 → 无 summary → 该批返回 None 跳过
        '{"title": "章C", "summary": "c"}',
    ])
    doc = await VideoNarrativeSynthesizer(llm, batch_size=2).synthesize(_blocks(6))
    assert [c.title for c in doc.chapters] == ["章A", "章C"]


@pytest.mark.asyncio
async def test_all_batches_failed_raises():
    """反例：全部批失败 → NarrativeSynthesisError。"""
    llm = ScriptedLLM(fail_map_batches={0, 1, 2})
    with pytest.raises(NarrativeSynthesisError):
        await VideoNarrativeSynthesizer(llm, batch_size=2).synthesize(_blocks(5))


@pytest.mark.asyncio
async def test_empty_blocks_raises():
    with pytest.raises(NarrativeSynthesisError):
        await VideoNarrativeSynthesizer(ScriptedLLM()).synthesize([])


def test_parse_json_object_tolerates_fence_and_prose():
    assert _parse_json_object('```json\n{"title": "t", "summary": "s"}\n```') == {
        "title": "t", "summary": "s",
    }
    assert _parse_json_object('前缀杂文 {"title": "t"} 后缀') == {"title": "t"}
    assert _parse_json_object(None) == {}
    assert _parse_json_object('不是 JSON') == {}


@pytest.mark.asyncio
async def test_markdown_renders_timeline_and_details():
    llm = ScriptedLLM(map_responses=['{"title": "开场", "summary": "开场内容"}'])
    doc = await VideoNarrativeSynthesizer(llm, batch_size=5).synthesize(_blocks(3))
    md = doc.to_markdown("测试视频")
    assert "# 测试视频" in md
    assert "## 章节时间轴" in md
    assert "0:00" in md and "开场" in md
