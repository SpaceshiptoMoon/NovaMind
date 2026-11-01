"""用户自定义文档标签（free-form）后端契约测试。

覆盖：标签规范化纯函数、打标请求 schema、打标服务双写（DB 落值 + ES chunk
同步，失败回滚 DB）、解析尾段从文档行回填（build_es_chunks）、检索过滤
schema（SearchFilters）。
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.features.knowledge_space.schemas.document_schema import (
    DocumentTagsUpdateRequest,
)
from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.schemas.search_schema import (
    SearchFilters,
    SearchRequest,
)
from novamind.features.knowledge_space.services.pipeline_steps import build_es_chunks
from novamind.features.knowledge_space.services.tag_service import (
    MAX_TAGS_PER_DOC,
    DocumentTagService,
    normalize_tags,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# normalize_tags 纯函数
# ---------------------------------------------------------------------------


def test_normalize_tags_trims_dedups_and_casefolds():
    """trim/压缩空白/casefold/去重保序。"""
    out = normalize_tags(["  财报  ", "财报", "Q3  规划", "q3 规划", "", None, "  "])
    assert out == ["财报", "q3 规划"]


def test_normalize_tags_caps_count_and_length():
    """去重后截断到 20 个；单标签截断到 50 字符。"""
    many = [f"tag{i}" for i in range(40)]
    out = normalize_tags(many)
    assert len(out) == MAX_TAGS_PER_DOC
    long_tag = "x" * 80
    assert normalize_tags([long_tag]) == ["x" * 50]


def test_normalize_tags_rejects_non_string():
    """非字符串项静默跳过（Pydantic 已拦截，防御二次入口）。"""
    assert normalize_tags([123, None, "ok"]) == ["ok"]


def test_tags_update_request_schema():
    """打标请求：默认空列表（= 清空标签）；非字符串项被 Pydantic 拒绝。"""
    assert DocumentTagsUpdateRequest().tags == []
    req = DocumentTagsUpdateRequest(tags=["财报", " Q3 "])
    assert req.tags == ["财报", " Q3 "]
    with pytest.raises(Exception):
        DocumentTagsUpdateRequest(tags=[1, 2])


def test_search_filters_schema():
    """检索过滤：缺省 None 零破坏；tags OR 语义列表。"""
    assert SearchRequest(query="q").filters is None
    r = SearchRequest(query="q", filters=SearchFilters(tags=["a", "b"]))
    assert r.filters.tags == ["a", "b"]


# ---------------------------------------------------------------------------
# DocumentTagService：双写 + 失败回滚
# ---------------------------------------------------------------------------


class _FakeSession:
    """记录 commit 次数的会话桩。"""

    def __init__(self) -> None:
        self.commit_calls = 0

    def begin_nested(self):
        return self

    async def flush(self) -> None:
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self) -> None:
        self.commit_calls += 1


class _FakeEs:
    """ES 客户端桩：generate_index_name + 底层 update_by_query/search。"""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[dict] = []

    def generate_index_name(self, space_id: int) -> str:
        return f"space_{space_id}"

    @property
    def es_client(self):
        outer = self

        class _Inner:
            async def update_by_query(self, **kw):
                outer.calls.append(kw)
                if outer.fail:
                    raise ConnectionError("es down")
                return {"updated": 3}

            async def search(self, **kw):
                return {
                    "aggregations": {
                        "doc_tags": {"buckets": [{"key": "财报", "doc_count": 7}]}
                    }
                }

        return _Inner()


def _doc():
    return SimpleNamespace(
        id=980, space_id=38, kb_id=108, tags=["旧标签"],
    )


@pytest.mark.asyncio
async def test_set_tags_writes_db_and_es():
    """打标成功：规范化后落 DB、update_by_query 同步 chunk、返回规范化结果。"""
    doc = _doc()
    session = _FakeSession()
    service = DocumentTagService(session)
    service._sync_es_chunks = AsyncMock(return_value=3)  # 直接桩同步层，隔离 ES 细节

    out = await service.set_document_tags(doc, ["  财报 ", "财报", "Q3"])

    assert out == ["财报", "q3"]
    assert doc.tags == ["财报", "q3"]
    assert session.commit_calls >= 1
    service._sync_es_chunks.assert_awaited_once_with(doc.space_id, doc.id, out)


@pytest.mark.asyncio
async def test_set_tags_es_failure_rolls_back_db():
    """ES 同步失败：DB 标签回滚到改标前，抛 RuntimeError（不留下 DB/ES 分裂）。"""
    doc = _doc()
    session = _FakeSession()
    service = DocumentTagService(session)
    service._sync_es_chunks = AsyncMock(side_effect=ConnectionError("es down"))

    with pytest.raises(RuntimeError, match="回滚"):
        await service.set_document_tags(doc, ["新标签"])

    assert doc.tags == ["旧标签"], "失败方向安全：检索面保持旧值"


# ---------------------------------------------------------------------------
# 解析尾段回填（build_es_chunks）
# ---------------------------------------------------------------------------


def test_build_es_chunks_backfills_doc_tags():
    """chunk 写入时冗余文档级标签到 metadata.doc_tags（写入时打标原则）。"""
    document = SimpleNamespace(
        id=980, space_id=38, kb_id=108,
        file_hash="h" * 64, filename="v.mp4", file_type="mp4",
        storage={"minio_object_name": "obj"},
        lifecycle_status="active",
        tags=["财报", "q3"],
    )
    chunks = build_es_chunks(document, [("描述", {})], ChunkType.VIDEO)
    assert chunks[0]["metadata"]["doc_tags"] == ["财报", "q3"]

    document.tags = None
    chunks = build_es_chunks(document, [("描述", {})], ChunkType.VIDEO)
    assert chunks[0]["metadata"]["doc_tags"] == []


@pytest.mark.asyncio
async def test_aggregate_kb_tags_returns_buckets():
    """标签聚合：terms agg 结果映射为 [{tag, count}]（KB 级作用域数据源）。"""
    service = DocumentTagService(_FakeSession())
    es = _FakeEs()
    service.aggregate_kb_tags.__self__  # noqa: B018 确认方法存在
    # 直接替换 ES 客户端获取点
    import novamind.features.knowledge_space.services.tag_service as ts

    class _Client:
        def generate_index_name(self, space_id):
            return f"space_{space_id}"
        es_client = _FakeEs().es_client

    async def fake_get_es():
        return _Client()

    ts_get = ts  # 模块引用
    from novamind.features.knowledge_space.api import dependencies as deps

    orig = deps.get_elasticsearch_client
    deps.get_elasticsearch_client = fake_get_es
    try:
        out = await service.aggregate_kb_tags(38, 108)
    finally:
        deps.get_elasticsearch_client = orig
    assert out == [{"tag": "财报", "count": 7}]


def test_kb_filter_doc_tags_uses_keyword_subfield():
    """过滤拼装走 .keyword 子字段：标签字段在存量索引被 dynamic 映射固定为 text
    （中文被标准分词切成单字 token），terms 精确匹配必须走子字段（真机回归）。"""
    import json as _json

    from novamind.shared.storage.elasticsearch_client import ElasticsearchClient
    from novamind.shared.storage.index_schema import DefaultIndexSchema

    client = ElasticsearchClient.__new__(ElasticsearchClient)
    client._schema = DefaultIndexSchema()
    filters = client._build_kb_filter(108, doc_tags=["彩条测试"])
    blob = _json.dumps(filters, ensure_ascii=False)
    assert "metadata.doc_tags.keyword" in blob
    # 必须不再出现主字段直接 terms（text 主字段会按分词 token 匹配而漏命中）
    assert '"metadata.doc_tags"' not in blob
