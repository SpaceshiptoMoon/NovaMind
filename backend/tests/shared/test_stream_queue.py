"""stream_queue 契约单测（fake stream port，不触真实 Redis）。

验证解析任务流封装的语义契约：
1. 派发：payload JSON 序列化 + MAXLEN 近似修剪参数透传；
2. 消费：载荷反序列化、损坏载荷跳过不阻塞、空读返回空列表；
3. ACK：消息 id 原样透传；
4. 延迟 zset：score=到期毫秒、只取到期条目、取出即移除、坏条目丢弃。
"""
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class FakeStreamPool:
    """stream 原语的内存替身：读取/认领返回预置条目，xadd 记录入流。"""

    def __init__(self):
        self.streams: dict[str, list] = {}
        self.read_results: list = []  # 每次 xreadgroup 弹出一组 (mid, fields)
        self.claim_results: list = []
        self.xacked: list = []
        self.xadd_calls: list = []
        self.zadds: list = []
        self.zrems: list = []
        self.zadds_scored: dict = {}

    async def xadd(self, key, fields, **kwargs):
        self.xadd_calls.append((key, dict(fields), kwargs))
        return "1-0"

    async def xgroup_create(self, key, group, id="0", mkstream=False):
        return "OK"

    async def xreadgroup(self, group, consumer, streams, count=None, block=None):
        if self.read_results:
            entries = self.read_results.pop(0)
            return [[list(streams)[0], entries]]
        return []

    async def xack(self, key, group, *ids):
        self.xacked.extend(ids)
        return len(ids)

    async def xautoclaim(self, key, group, consumer, min_idle_time, start_id="0-0", count=None):
        if self.claim_results:
            entries = self.claim_results.pop(0)
            next_id = "0-0"
            return (next_id, entries, [])
        return ("0-0", [], [])

    async def zadd(self, key, mapping, **kwargs):
        self.zadds.append((key, dict(mapping)))
        return len(mapping)

    async def zrangebyscore(self, key, lo, hi, start=None, num=None):
        m = self.zadds_scored.setdefault(key, {})
        lo_v = float('-inf') if lo == '-inf' else float(lo)
        hi_v = float('inf') if hi == '+inf' else float(hi)
        hit = [k for k, s in sorted(m.items(), key=lambda x: x[1]) if lo_v <= s <= hi_v]
        return hit[: num or len(hit)]

    async def zrem(self, key, member):
        m = self.zadds_scored.setdefault(key, {})
        if member in m:
            m.pop(member)
            return 1
        return 0

    # zrangebyscore/zrem 消费的记分 zset（与 zadds 分开便于断言）
    zadds_scored: dict = {}


@pytest.fixture
def pool():
    return FakeStreamPool()


def _payload(i: int) -> dict:
    return {"task_id": i, "document_id": i, "kb_id": 1, "space_id": 1}


async def test_xadd_serializes_payload_and_sets_maxlen(pool):
    from novamind.shared.mq.stream_queue import PARSE_STREAM_MAXLEN, xadd_parse_task

    await xadd_parse_task(pool, _payload(7))

    key, fields, kwargs = pool.xadd_calls[0]
    assert key == "nm:parse:tasks"
    import json

    assert json.loads(fields["payload"]) == _payload(7)
    assert kwargs["maxlen"] == PARSE_STREAM_MAXLEN
    assert kwargs["approximate"] is True


async def test_xreadgroup_decodes_payloads(pool):
    from novamind.shared.mq.stream_queue import xreadgroup_parse

    pool.read_results.append([
        ("1-0", {"payload": '{"task_id": 1}'}),
        ("2-0", {"payload": '{"task_id": 2}'}),
    ])

    out = await xreadgroup_parse(pool, "worker-1", count=10, block_ms=0)

    assert [(mid, p["task_id"]) for mid, p in out] == [("1-0", 1), ("2-0", 2)]


async def test_xreadgroup_skips_corrupt_payload(pool):
    """载荷损坏（非法 JSON）跳过该条不阻塞消费循环。"""
    from novamind.shared.mq.stream_queue import xreadgroup_parse

    pool.read_results.append([
        ("1-0", {"payload": "not-json{{{"}),
        ("2-0", {"payload": '{"task_id": 2}'}),
    ])

    out = await xreadgroup_parse(pool, "worker-1", count=10, block_ms=0)

    assert [mid for mid, _ in out] == ["2-0"], "损坏载荷被跳过，合法载荷正常返回"


async def test_xreadgroup_empty_returns_empty_list(pool):
    from novamind.shared.mq.stream_queue import xreadgroup_parse

    assert await xreadgroup_parse(pool, "worker-1", count=10, block_ms=0) == []


async def test_xack_passes_message_ids(pool):
    from novamind.shared.mq.stream_queue import xack_parse

    assert await xack_parse(pool, "1-0") == 1
    assert pool.xacked == ["1-0"]


async def test_xautoclaim_decodes_claimed_entries(pool):
    from novamind.shared.mq.stream_queue import xclaim_stalled

    pool.claim_results.append([
        ("9-0", {"payload": '{"task_id": 9}'}),
    ])

    out = await xclaim_stalled(pool, "worker-2", min_idle_ms=300_000, count=10)

    assert [(mid, p["task_id"]) for mid, p in out] == [("9-0", 9)]


async def test_zadd_delayed_scores_by_due_time(pool):
    from novamind.shared.mq.stream_queue import zadd_delayed

    await zadd_delayed(pool, _payload(1), delay_seconds=60)
    await zadd_delayed(pool, _payload(2), delay_seconds=5)

    assert len(pool.zadds) == 2
    assert all(key == "nm:parse:delayed" for key, _ in pool.zadds)
    scores = sorted(s for _, mapping in pool.zadds for s in mapping.values())
    assert scores[1] - scores[0] == 55_000, "延迟差应体现在 score（毫秒到期时间）差上"


async def test_pop_due_returns_only_due_and_removes(pool):
    import time as _time

    from novamind.shared.mq.stream_queue import pop_due_delayed

    now = int(_time.time() * 1000)
    # 直接管 scored zset 模拟到期/未到期（score 为 epoch 毫秒）
    m = pool.zadds_scored.setdefault("nm:parse:delayed", {})
    m['{"task_id": 1}'] = now - 1000   # 已到期
    m['{"task_id": 2}'] = now - 2000   # 已到期
    m['{"task_id": 3}'] = now + 999999  # 未到期

    payloads = await pop_due_delayed(pool, limit=10)

    assert sorted(p["task_id"] for p in payloads) == [1, 2], "到期条目全部返回（顺序非契约）"
    assert '{"task_id": 3}' in m, "未到期条目必须保留"


async def test_pop_due_respects_limit(pool):
    from novamind.shared.mq.stream_queue import pop_due_delayed

    m = pool.zadds_scored.setdefault("nm:parse:delayed", {})
    for i in range(5):
        m[f'{{"task_id": {i}}}'] = 1000 + i

    payloads = await pop_due_delayed(pool, limit=2)

    assert len(payloads) == 2
    assert len(m) == 3, "超出 limit 的到期条目留在 zset，下一轮搬运"


async def test_pop_due_deserialization_failure_drops_entry(pool):
    from novamind.shared.mq.stream_queue import pop_due_delayed

    pool.zadds_scored.setdefault("nm:parse:delayed", {})["bad-member"] = 1000

    payloads = await pop_due_delayed(pool, limit=10)

    assert payloads == []
    assert "bad-member" not in pool.zadds_scored["nm:parse:delayed"], "坏条目取出即丢弃"
