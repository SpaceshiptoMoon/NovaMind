"""知识检索工具叙事章节上下文测试。

验证命中视频块所在叙事章节（narrative_synthesis 产物）在工具结果中的
格式化行为：结果行引用 + 章节去重 + 全片梗概去重 + 截断与非法输入兜底，
以及质量管线出口（_pipeline_search）的完整 JSON 结构。
"""
import json

import pytest

from novamind.engines.agent.context_types import KnowledgeSearchItem
from novamind.engines.agent.tool.builtins.knowledge_search import (
    _CHAPTER_SUMMARY_MAX_CHARS,
    _format_hits_with_chapters,
    _fmt_ts,
    KnowledgeSearchTool,
)


def _item(
    content: str = "帧描述",
    chunk_id: str | None = "995_1",
    narrative: dict | None = None,
    filename: str | None = "sintel.mp4",
) -> KnowledgeSearchItem:
    return KnowledgeSearchItem(
        content=content,
        score=0.9,
        document_id=995,
        chunk_id=chunk_id,
        file_info={"filename": filename} if filename else None,
        narrative_chapter=narrative,
    )


def _chapter(title: str = "龙穴绝境", overview: str = "全片梗概") -> dict:
    return {
        "title": title,
        "start_time": 498.0,
        "end_time": 615.0,
        "summary": "少年与黑龙在龙穴殊死搏杀" * 3,
        "overview": overview,
    }


class TestFmtTs:
    def test_seconds_formats(self):
        assert _fmt_ts(0) == "00:00"
        assert _fmt_ts(59) == "00:59"
        assert _fmt_ts(60) == "01:00"
        assert _fmt_ts(498.0) == "08:18"
        assert _fmt_ts(3661) == "1:01:01"

    def test_invalid_inputs_return_empty(self):
        assert _fmt_ts(None) == ""
        assert _fmt_ts("abc") == ""
        assert _fmt_ts("") == ""


class TestFormatHitsWithChapters:
    def test_hit_with_chapter_gets_reference_and_chapter_row(self):
        rows, chapters, overviews = _format_hits_with_chapters(
            [_item(narrative=_chapter())]
        )
        assert rows[0]["chapter"] == 0
        assert len(chapters) == 1
        assert chapters[0]["title"] == "龙穴绝境"
        assert chapters[0]["time_range"] == "08:18-10:15"
        assert "龙穴殊死搏杀" in chapters[0]["summary"]
        # 全片梗概进顶层 overviews，不挤占结果行
        assert len(overviews) == 1
        assert overviews[0]["document_id"] == 995

    def test_same_chapter_hits_deduplicated(self):
        rows, chapters, _ = _format_hits_with_chapters(
            [
                _item(chunk_id="995_1", narrative=_chapter()),
                _item(chunk_id="995_2", narrative=_chapter()),
            ]
        )
        assert len(chapters) == 1
        assert rows[0]["chapter"] == rows[1]["chapter"] == 0

    def test_different_chapters_get_distinct_refs(self):
        _, chapters, _ = _format_hits_with_chapters(
            [
                _item(chunk_id="995_1", narrative=_chapter(title="章一")),
                _item(chunk_id="995_2", narrative=_chapter(title="章二")),
            ]
        )
        assert len(chapters) == 2
        assert [c["chapter"] for c in chapters] == [0, 1]

    def test_hits_without_chapter_stay_clean(self):
        rows, chapters, overviews = _format_hits_with_chapters([_item()])
        assert "chapter" not in rows[0]
        assert chapters == []
        assert overviews == []

    def test_overview_deduplicated_per_document(self):
        _, _, overviews = _format_hits_with_chapters(
            [
                _item(chunk_id="995_1", narrative=_chapter(title="章一")),
                _item(chunk_id="995_2", narrative=_chapter(title="章二")),
            ]
        )
        assert len(overviews) == 1

    def test_long_summary_truncated(self):
        nc = _chapter()
        nc["summary"] = "很长的章节摘要" * 500
        _, chapters, _ = _format_hits_with_chapters([_item(narrative=nc)])
        assert len(chapters[0]["summary"]) == _CHAPTER_SUMMARY_MAX_CHARS

    def test_missing_time_anchors_omit_time_range(self):
        nc = _chapter()
        nc["start_time"] = None
        nc["end_time"] = None
        _, chapters, _ = _format_hits_with_chapters([_item(narrative=nc)])
        assert "time_range" not in chapters[0]


class TestPipelineSearchChapterOutput:
    """质量管线出口的完整 JSON 结构（结果行 + chapters + video_overviews）。"""

    @pytest.mark.asyncio
    async def test_output_includes_chapters_and_overviews(self):
        tool = KnowledgeSearchTool()

        async def fake_pipeline_search(**kwargs):
            return {
                "items": [
                    KnowledgeSearchItem(
                        content="少年驯龙画面",
                        score=0.92,
                        document_id=995,
                        chunk_id="995_52",
                        file_info={"filename": "sintel.mp4"},
                        narrative_chapter=_chapter(),
                    ),
                    KnowledgeSearchItem(
                        content="普通文本块",
                        score=0.7,
                        document_id=100,
                        chunk_id="100_0",
                        file_info={"filename": "notes.md"},
                    ),
                ],
                "rewritten_query": "黑龙",
                "rewrite_degraded": False,
                "grade_traces": [],
                "insufficient_evidence": False,
                "raw_count": 2,
            }

        class _Port:
            pipeline_search = staticmethod(fake_pipeline_search)

        out = await tool._pipeline_search(
            _Port(),
            {"space_id": 38, "query": "黑龙", "top_k": 5},
            {},
            {"user_id": 1},
        )
        payload = json.loads(out)
        assert payload["total"] == 2
        # 视频块带章节引用，普通块不带
        assert payload["results"][0]["chapter"] == 0
        assert "chapter" not in payload["results"][1]
        assert payload["chapters"][0]["title"] == "龙穴绝境"
        assert payload["video_overviews"][0]["document_id"] == 995
