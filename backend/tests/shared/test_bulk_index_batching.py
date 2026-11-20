"""bulk_index_chunks 分批回归测试（红队 B11）。

历史缺陷：整文档 actions 一次性单请求 bulk——千块 × 1024 维向量单请求体
可逼近 ES http.max_content_length，且失败粒度为整文档（差一块即全量重试）。
修复后按 batch_size 分片循环，返回语义（总成功数）不变。
"""
import asyncio
from unittest.mock import AsyncMock

import pytest
from novamind.shared.storage.elasticsearch_client import ElasticsearchClient

pytestmark = pytest.mark.unit


def _make_client(capture: list):
    """构造绕过 __init__ 的客户端实例（探针注入 fake ES，ensure_index_exists 打桩）。"""
    client = ElasticsearchClient.__new__(ElasticsearchClient)

    class _FakeES:
        async def bulk(self, operations):
            capture.append(operations)
            return {
                "items": [
                    {"index": {"status": 201}} for _ in range(len(operations) // 2)
                ]
            }

    client.es_client = _FakeES()
    client.ensure_index_exists = AsyncMock(return_value="space_7")
    return client


def _chunk(i: int) -> dict:
    return {"chunk_id": f"42_{i}", "content": f"c{i}", "embedding": [0.1] * 8}


def test_bulk_index_chunks_splits_into_batches():
    """600 chunk、batch_size=250 → 3 次 bulk（250/250/100），成功总数聚合。"""
    chunks = [_chunk(i) for i in range(600)]
    capture: list = []
    client = _make_client(capture)

    success = asyncio.run(
        client.bulk_index_chunks(7, chunks, embedding_dim=1024, batch_size=250)
    )

    assert success == 600, "全部 chunk 成功时返回总数"
    assert len(capture) == 3, "600/250 必须拆 3 次 bulk 请求"
    assert [len(ops) // 2 for ops in capture] == [250, 250, 100]


def test_bulk_index_chunks_single_batch_when_under_limit():
    """少量 chunk 单请求行为与修复前一致（batch 默认 250）。"""
    chunks = [_chunk(i) for i in range(10)]
    capture: list = []
    client = _make_client(capture)

    success = asyncio.run(client.bulk_index_chunks(7, chunks, embedding_dim=1024))

    assert success == 10
    assert len(capture) == 1


def test_bulk_index_chunks_empty_noop():
    """空列表 no-op：不触 ensure_index_exists，不发生 bulk。"""
    client = _make_client([])
    success = asyncio.run(client.bulk_index_chunks(7, [], embedding_dim=1024))
    assert success == 0


def test_bulk_index_chunks_partial_failure_returns_aggregate():
    """某批部分失败：成功数跨批累计，调用方凭总数 < len 门槛走重试路径。"""
    chunks = [_chunk(i) for i in range(500)]

    class _PartialES:
        def __init__(self):
            self.calls = 0

        async def bulk(self, operations):
            self.calls += 1
            # 第一批成功 250；第二批丢 1 条
            if self.calls == 1:
                return {"items": [{"index": {"status": 201}} for _ in range(250)]}
            return {"items": [{"index": {"status": 201}} for _ in range(249)]
                    + [{"index": {"status": 400}}]}

    client = ElasticsearchClient.__new__(ElasticsearchClient)
    fake = _PartialES()
    client.es_client = fake
    client.ensure_index_exists = AsyncMock(return_value="space_7")

    success = asyncio.run(
        client.bulk_index_chunks(7, chunks, embedding_dim=1024, batch_size=250)
    )
    assert success == 499
    assert fake.calls == 2
