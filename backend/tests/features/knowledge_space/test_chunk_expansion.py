"""检索期上下文扩展回归测试：句窗口扩窗 + 父子回带 + 幂等/兜底/存量直通。

验证核心不变量：
1. 扩窗：命中 content 替换为邻居拼接、原文保留进 metadata.expansion；
2. 窗口合并：同文档重叠窗口合并为单结果（保留高分），结果数不膨胀；
3. 回带：子块 content 替换为父块全文；
4. 失败方向安全：父块缺失/拉取失败/扩展异常 → 保留原子块不抛错；
5. 存量直通：无扩展元数据的命中零改动；
6. 幂等：已扩展（metadata.expansion 存在）跳过；
7. _build_kb_filter：父块召回排除（must_not chunk_role=parent）+ 存量不受影响。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.services.chunk_expansion_service import (
    expand_search_results,
)
from novamind.shared.storage.elasticsearch_client import ElasticsearchClient

pytestmark = pytest.mark.unit


class _FakeEsClient:
    """最小 ES 客户端替身：文档分块表 + 单块表，可注入失败。"""

    def __init__(self, doc_chunks: list[dict] | None = None, chunks_by_id: dict | None = None,
                 fail_doc_fetch: bool = False, fail_get_chunk: bool = False):
        self._doc_chunks = doc_chunks or []
        self._chunks_by_id = chunks_by_id or {}
        self._fail_doc_fetch = fail_doc_fetch
        self._fail_get_chunk = fail_get_chunk

    async def get_document_chunks(self, space_id, document_id, skip=0, limit=100):
        if self._fail_doc_fetch:
            raise RuntimeError("es down")
        return {"items": self._doc_chunks, "total": len(self._doc_chunks)}

    async def get_chunk(self, space_id, chunk_id):
        if self._fail_get_chunk:
            raise RuntimeError("es down")
        return self._chunks_by_id.get(chunk_id)


def _hit(chunk_index: int, content: str, score: float = 0.9, **meta_extra) -> dict:
    meta = {"expansion_type": "sentence_window", "expansion_window_size": 1}
    meta.update(meta_extra)
    return {
        "chunk_id": f"61_{chunk_index}", "document_id": 61, "chunk_index": chunk_index,
        "content": content, "score": score, "metadata": meta,
    }


# ===== 句子窗口扩窗 =====


@pytest.mark.asyncio
async def test_window_hit_expands_with_neighbors():
    """正例：命中 content 变为「原子块 + 前后邻居」拼接，原文进 expansion。"""
    es = _FakeEsClient(doc_chunks=[
        {"chunk_index": 0, "content": "前句。"},
        {"chunk_index": 1, "content": "命中句。"},
        {"chunk_index": 2, "content": "后句。"},
    ])
    results = [_hit(1, "命中句。")]
    out = await expand_search_results(es, 1, results)
    assert out[0]["content"] == "命中句。\n前句。\n后句。"
    assert out[0]["metadata"]["expansion"]["retrieved_content"] == "命中句。"
    assert out[0]["metadata"]["expansion"]["type"] == "sentence_window"
    assert out[0]["metadata"]["expansion"]["window_chunk_range"] == [0, 2]


@pytest.mark.asyncio
async def test_overlapping_windows_merge_keep_higher_score():
    """重叠窗口合并：两命中窗口重叠 → 保留高分者，低分者剔除，结果数不膨胀。"""
    es = _FakeEsClient(doc_chunks=[
        {"chunk_index": 0, "content": "句零。"},
        {"chunk_index": 1, "content": "句一。"},
        {"chunk_index": 2, "content": "句二。"},
        {"chunk_index": 3, "content": "句三。"},
    ])
    results = [_hit(1, "高分句。", score=0.9), _hit(2, "低分句。", score=0.5)]
    out = await expand_search_results(es, 1, results)
    assert len(out) == 1
    assert out[0]["content"].startswith("高分句。")


@pytest.mark.asyncio
async def test_window_fetch_failure_keeps_original():
    """失败方向安全：邻居拉取异常 → 保留原子块文本，不抛错。"""
    es = _FakeEsClient(fail_doc_fetch=True)
    results = [_hit(1, "命中句。")]
    out = await expand_search_results(es, 1, results)
    assert out[0]["content"] == "命中句。"
    assert "expansion" not in out[0]["metadata"]


@pytest.mark.asyncio
async def test_window_zero_size_no_expansion():
    """window_size=0 是「不扩窗」合法配置：命中零改动。"""
    es = _FakeEsClient(doc_chunks=[{"chunk_index": 0, "content": "邻居。"}])
    results = [_hit(1, "命中句。")]
    results[0]["metadata"]["expansion_window_size"] = 0
    out = await expand_search_results(es, 1, results)
    assert out[0]["content"] == "命中句。"
    assert "expansion" not in out[0]["metadata"]


# ===== 父子回带 =====


def _child_hit(content: str = "子块命中。", parent_id: str = "61_0", score: float = 0.9) -> dict:
    return {
        "chunk_id": "61_1", "document_id": 61, "chunk_index": 1,
        "content": content, "score": score,
        "metadata": {"chunk_role": "child", "parent_chunk_id": parent_id},
    }


@pytest.mark.asyncio
async def test_parent_child_hit_returns_parent_content():
    """正例：子块 content 替换为父块全文，子块原文进 expansion。"""
    es = _FakeEsClient(chunks_by_id={"61_0": {"content": "父块全文。"}})
    results = [_child_hit()]
    out = await expand_search_results(es, 1, results)
    assert out[0]["content"] == "父块全文。"
    assert out[0]["metadata"]["expansion"]["retrieved_content"] == "子块命中。"
    assert out[0]["metadata"]["expansion"]["parent_chunk_id"] == "61_0"


@pytest.mark.asyncio
async def test_parent_missing_keeps_child_content():
    """父块缺失（未索引/被清）→ 保留子块原文，不抛错。"""
    es = _FakeEsClient(chunks_by_id={})
    results = [_child_hit()]
    out = await expand_search_results(es, 1, results)
    assert out[0]["content"] == "子块命中。"
    assert "expansion" not in out[0]["metadata"]


@pytest.mark.asyncio
async def test_get_chunk_failure_keeps_child_content():
    """get_chunk 异常 → expand_search_results 整体兜底，原结果返回。"""
    es = _FakeEsClient(fail_get_chunk=True)
    results = [_child_hit()]
    out = await expand_search_results(es, 1, results)
    assert out[0]["content"] == "子块命中。"


# ===== 存量直通与幂等 =====


@pytest.mark.asyncio
async def test_hits_without_expansion_metadata_untouched():
    """相邻正常场景：存量命中（无扩展元数据）零改动直通。"""
    plain = {
        "chunk_id": "61_5", "document_id": 61, "chunk_index": 5,
        "content": "普通 recursive 块。", "score": 0.8, "metadata": {"page_number": 1},
    }
    es = _FakeEsClient(doc_chunks=[{"chunk_index": 4, "content": "邻居。"}])
    out = await expand_search_results(es, 1, [plain])
    assert out[0]["content"] == "普通 recursive 块。"
    assert "expansion" not in out[0]["metadata"]


@pytest.mark.asyncio
async def test_already_expanded_results_idempotent():
    """幂等护栏：metadata.expansion 已存在的命中跳过（缓存复入/重复调用）。"""
    hit = _hit(1, "已扩展句。")
    hit["metadata"]["expansion"] = {"type": "sentence_window", "retrieved_content": "原句。"}
    es = _FakeEsClient(doc_chunks=[{"chunk_index": 0, "content": "邻居。"}])
    out = await expand_search_results(es, 1, [hit])
    assert out[0]["content"] == "已扩展句。"
    assert out[0]["metadata"]["expansion"]["retrieved_content"] == "原句。"


@pytest.mark.asyncio
async def test_empty_results_passthrough():
    """空结果直通（零 ES 调用）。"""
    es = _FakeEsClient()
    assert await expand_search_results(es, 1, []) == []


# ===== _build_kb_filter 父块召回排除 =====


class TestKbFilter:
    def _client(self) -> ElasticsearchClient:
        """__new__ 绕过 init + 最小 _schema 桩（filter 只消费 field_names.kb_id）。"""
        client = ElasticsearchClient.__new__(ElasticsearchClient)
        client._schema = SimpleNamespace(
            field_names=SimpleNamespace(kb_id="kb_id"),
        )
        return client

    def test_filter_excludes_parent_role(self):
        """must_not 含 chunk_role=parent（父块是回带容器不是召回单元）。"""
        filters = self._client()._build_kb_filter(kb_id=7)
        assert {"term": {"kb_id": 7}} in filters
        must_not = filters[-1]["bool"]["must_not"]
        assert {"terms": {"lifecycle_status": ["superseded", "archived"]}} in must_not
        assert {"term": {"metadata.chunk_role": "parent"}} in must_not

    def test_filter_without_kb_id_still_excludes_parent(self):
        """kb_id=None（跨库模式）时父块排除仍生效。"""
        filters = self._client()._build_kb_filter(kb_id=None)
        must_not = filters[-1]["bool"]["must_not"]
        assert {"term": {"metadata.chunk_role": "parent"}} in must_not
