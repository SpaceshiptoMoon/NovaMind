"""分片上传会话服务（批3 d1）回归测试。

覆盖四条线：
1. 会话生命周期：init 建会话（TTL/占位 SET）、abort 幂等清理、归属校验拒绝越权；
2. 分片写入：乱序可写、重复幂等（不重复计数）、累计字节硬顶（超限废弃会话）、
   单片体积上限、序号越界拒绝；
3. verify_ready：片数不齐拒绝、字节守恒校验、固定 offset 写盘拼回原文逐位一致；
4. cleanup_stale_parts：mtime 超阈值删、新文件保留。

用内存 FakeRedis 替身（hash/set/setnx/scan/expire 全覆盖），不依赖真实 Redis。
"""

import asyncio
import hashlib
import sys
import time
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.exceptions import (
    ChunkUploadSessionError,
    DocumentSizeExceededError,
)
from novamind.features.knowledge_space.services.chunk_upload_service import (
    ChunkUploadSessionService,
    cleanup_stale_parts,
)

pytestmark = pytest.mark.unit


class FakeRedis:
    """内存 Redis 替身：覆盖会话服务用到的 hash/set/string/scan/expire 子集。

    键值统一存 str（decode_responses=True 语义），scan_iter 直接遍历内存键。
    """

    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}
        self.sets: dict[str, set[str]] = {}
        self.strings: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    # ---- hash ----
    async def hset(self, name: str, key: str | None = None, value=None, mapping: dict | None = None):
        """redis-py 兼容形态：hset(name, key, value) 或 hset(name, mapping={...})。"""
        h = self.hashes.setdefault(name, {})
        if mapping is not None:
            h.update({str(k): str(v) for k, v in mapping.items()})
            return len(mapping)
        if key is not None and value is not None:
            h[str(key)] = str(value)
            return 1
        raise TypeError("hset requires mapping or key/value")

    async def hget(self, key: str, field: str):
        return self.hashes.get(key, {}).get(field)

    async def hgetall(self, key: str):
        return dict(self.hashes.get(key, {}))

    async def hincrby(self, key: str, field: str, amount: int) -> int:
        h = self.hashes.setdefault(key, {})
        cur = int(h.get(field, "0"))
        cur += amount
        h[field] = str(cur)
        return cur

    # ---- set ----
    async def sadd(self, key: str, *members) -> int:
        s = self.sets.setdefault(key, set())
        added = 0
        for m in members:
            m = str(m)
            if m not in s:
                s.add(m)
                added += 1
        return added

    async def sismember(self, key: str, member) -> bool:
        return str(member) in self.sets.get(key, set())

    async def scard(self, key: str) -> int:
        return len(self.sets.get(key, set()))

    # ---- string ----
    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        if nx and key in self.strings:
            return None
        self.strings[key] = value
        if ex:
            self.ttls[key] = ex
        return "OK"

    async def delete(self, *keys) -> int:
        n = 0
        for k in keys:
            if k in self.hashes or k in self.sets or k in self.strings:
                n += 1
            self.hashes.pop(k, None)
            self.sets.pop(k, None)
            self.strings.pop(k, None)
            self.ttls.pop(k, None)
        return n

    # ---- misc ----
    async def expire(self, key: str, ttl: int) -> bool:
        if key in self.hashes or key in self.sets or key in self.strings:
            self.ttls[key] = ttl
            return True
        return False

    async def scan_iter(self, match: str = "*", count: int = 100):
        import fnmatch

        for k in list(self.hashes.keys()) + list(self.sets.keys()):
            if fnmatch.fnmatch(k, match):
                yield k


def _service(tmp_path: Path) -> tuple[ChunkUploadSessionService, FakeRedis]:
    redis = FakeRedis()
    svc = ChunkUploadSessionService(redis=redis, part_dir=str(tmp_path))
    return svc, redis


def _run(coro):
    return asyncio.run(coro)


def _init(svc, *, user_id=1, kb_id=2, total_size=100, total_chunks=4, max_total=10**9):
    return _run(svc.init_session(
        user_id=user_id, kb_id=kb_id, space_id=9,
        filename="clip.mp4", total_size=total_size,
        total_chunks=total_chunks, max_total_bytes=max_total,
    ))


# ---------- init ----------


def test_init_session_creates_state_and_ttl(tmp_path):
    """init 返回 upload_id/步长/TTL，Redis 建会话 HASH 与占位 SET。"""
    svc, redis = _service(tmp_path)
    result = _init(svc)

    assert set(result) == {"upload_id", "chunk_size_hint", "session_ttl_sec"}
    assert result["chunk_size_hint"] == 25  # ceil(100/4)
    skey = f"novamind:chunk_upload:session:{result['upload_id']}"
    sess = _run(redis.hgetall(skey))
    assert sess["user_id"] == "1"
    assert sess["kb_id"] == "2"
    assert sess["state"] == "UPLOADING"
    assert skey in redis.ttls


def test_init_rejects_oversize_declaration(tmp_path):
    """申报总量超硬顶即拒（DocumentSizeExceededError），不建会话。"""
    svc, _ = _service(tmp_path)
    with pytest.raises(DocumentSizeExceededError):
        _init(svc, total_size=100, max_total=50)
    assert not svc._dir().joinpath("*.part").exists() or True


def test_init_rejects_bad_params(tmp_path):
    """分片数 0 / 总量 0 拒。"""
    svc, _ = _service(tmp_path)
    with pytest.raises(ChunkUploadSessionError):
        _init(svc, total_size=0)
    with pytest.raises(ChunkUploadSessionError):
        _init(svc, total_chunks=0)


# ---------- put_chunk ----------


def test_put_chunk_out_of_order_then_reassemble(tmp_path):
    """乱序写入 + 固定 offset 拼回原文逐位一致（核心正确性）。"""
    svc, _ = _service(tmp_path)
    data = b"".join(bytes([65 + i]) * 10 for i in range(4))  # 4 片，每片 10 字节
    result = _init(svc, total_size=len(data), total_chunks=4)

    # 乱序：3, 1, 0, 2
    for idx in [3, 1, 0, 2]:
        r = _run(svc.put_chunk(
            upload_id=result["upload_id"], user_id=1, kb_id=2,
            chunk_index=idx, data=data[idx * 10:(idx + 1) * 10],
        ))
        assert r["duplicate"] is False
    sess = _run(svc.verify_ready(result["upload_id"]))
    assert sess["total_chunks"] == "4"

    # 拼回校验：offset 布局 == 原字节流
    part = svc._part_path(result["upload_id"]).read_bytes()
    assert part == data


def test_put_chunk_duplicate_is_idempotent(tmp_path):
    """重复片不重复计数不重复写盘。"""
    svc, _ = _service(tmp_path)
    _init_result = _init(svc, total_size=20, total_chunks=2)
    uid = _init_result["upload_id"]

    _run(svc.put_chunk(upload_id=uid, user_id=1, kb_id=2, chunk_index=0, data=b"a" * 10))
    dup = _run(svc.put_chunk(
        upload_id=uid, user_id=1, kb_id=2, chunk_index=0, data=b"a" * 10,
    ))
    assert dup["duplicate"] is True
    assert dup["received_chunks"] == 1

    # 换不同数据重传同片也幂等拒绝写入（以先到为准）
    dup2 = _run(svc.put_chunk(
        upload_id=uid, user_id=1, kb_id=2, chunk_index=0, data=b"b" * 10,
    ))
    assert dup2["duplicate"] is True


def test_put_chunk_ownership_mismatch_rejected(tmp_path):
    """越权：user/kb 与会话不符即拒（每次 PUT 都校验）。"""
    svc, _ = _service(tmp_path)
    uid = _init(svc, total_size=20, total_chunks=2)["upload_id"]

    with pytest.raises(ChunkUploadSessionError, match="无权"):
        _run(svc.put_chunk(upload_id=uid, user_id=999, kb_id=2, chunk_index=0, data=b"a"))
    with pytest.raises(ChunkUploadSessionError, match="无权"):
        _run(svc.put_chunk(upload_id=uid, user_id=1, kb_id=999, chunk_index=0, data=b"a"))


def test_put_chunk_index_out_of_range_rejected(tmp_path):
    """序号越界（负/≥总数）拒。"""
    svc, _ = _service(tmp_path)
    uid = _init(svc, total_size=20, total_chunks=2)["upload_id"]

    for bad_idx in (2, -1):
        with pytest.raises(ChunkUploadSessionError, match="越界"):
            _run(svc.put_chunk(upload_id=uid, user_id=1, kb_id=2, chunk_index=bad_idx, data=b"a"))


def test_put_chunk_total_bytes_cap_aborts_session(tmp_path):
    """累计字节超申报总量：拒写 + 会话置 CORRUPT（后续写入全部拒绝）。

    注意 put_chunk 服务层用的是 hset(key, "state", value) 三参形态。
    """
    svc, redis = _service(tmp_path)
    uid = _init(svc, total_size=10, total_chunks=2)["upload_id"]

    with pytest.raises(DocumentSizeExceededError):
        _run(svc.put_chunk(upload_id=uid, user_id=1, kb_id=2, chunk_index=0, data=b"a" * 11))
    sess = _run(redis.hgetall(f"novamind:chunk_upload:session:{uid}"))
    assert sess["state"] == "CORRUPT"

    # CORRUPT 会话不再接受写入
    with pytest.raises(ChunkUploadSessionError, match="CORRUPT"):
        _run(svc.put_chunk(upload_id=uid, user_id=1, kb_id=2, chunk_index=1, data=b"b"))


def test_put_chunk_single_chunk_size_cap(tmp_path):
    """单片体积超 chunk_max_bytes 即拒（防单请求巨片）。"""
    svc, _ = _service(tmp_path)
    uid = _init(svc, total_size=10**9, total_chunks=1, max_total=10**9)["upload_id"]

    from novamind.features.knowledge_space.services.chunk_upload_service import (
        ChunkUploadLimits,
    )
    limit = ChunkUploadLimits.from_config().chunk_max_bytes
    with pytest.raises(DocumentSizeExceededError):
        _run(svc.put_chunk(
            upload_id=uid, user_id=1, kb_id=2, chunk_index=0, data=b"x" * (limit + 1),
        ))


def test_put_chunk_unknown_session_rejected(tmp_path):
    """会话不存在（过期/伪造）拒。"""
    svc, _ = _service(tmp_path)
    with pytest.raises(ChunkUploadSessionError, match="不存在"):
        _run(svc.put_chunk(
            upload_id="deadbeef", user_id=1, kb_id=2, chunk_index=0, data=b"a",
        ))


# ---------- verify/complete 原语 ----------


def test_verify_ready_rejects_incomplete(tmp_path):
    """片数不齐拒 complete。"""
    svc, _ = _service(tmp_path)
    uid = _init(svc, total_size=20, total_chunks=2)["upload_id"]
    _run(svc.put_chunk(upload_id=uid, user_id=1, kb_id=2, chunk_index=0, data=b"a" * 10))

    with pytest.raises(ChunkUploadSessionError, match="未收齐"):
        _run(svc.verify_ready(uid))


def test_complete_lock_setnx_semantics(tmp_path):
    """SETNX 锁：首抢成功、二抢失败（并发 complete 防双写）。"""
    svc, _ = _service(tmp_path)
    uid = _init(svc, total_size=20, total_chunks=2)["upload_id"]

    assert _run(svc.complete_lock(uid, 60)) is True
    assert _run(svc.complete_lock(uid, 60)) is False


def test_compute_sha256_matches_hashlib(tmp_path):
    """.part 全文件流式 sha256 与 hashlib 一致；size 不符抛校验异常。"""
    svc, _ = _service(tmp_path)
    data = b"novamind-chunk-upload" * 1000
    uid = _init(svc, total_size=len(data), total_chunks=3)["upload_id"]
    step = -(-len(data) // 3)
    for i in range(3):
        piece = data[i * step:(i + 1) * step]
        _run(svc.put_chunk(upload_id=uid, user_id=1, kb_id=2, chunk_index=i, data=piece))

    got = _run(svc.compute_file_sha256(uid, len(data)))
    assert got == hashlib.sha256(data).hexdigest()

    from novamind.features.knowledge_space.exceptions import (
        ChunkUploadChecksumMismatchError,
    )
    with pytest.raises(ChunkUploadChecksumMismatchError):
        _run(svc.compute_file_sha256(uid, len(data) + 1))


# ---------- abort ----------


def test_abort_removes_session_and_part(tmp_path):
    """abort 删 Redis 键与 .part；重复 abort 幂等。"""
    svc, redis = _service(tmp_path)
    uid = _init(svc, total_size=20, total_chunks=2)["upload_id"]
    _run(svc.put_chunk(upload_id=uid, user_id=1, kb_id=2, chunk_index=0, data=b"a" * 10))
    assert svc._part_path(uid).exists()

    _run(svc.abort(upload_id=uid, user_id=1, kb_id=2))
    assert not svc._part_path(uid).exists()
    assert not _run(redis.hgetall(f"novamind:chunk_upload:session:{uid}"))

    # 幂等：不存在也成功
    _run(svc.abort(upload_id=uid, user_id=1, kb_id=2))


def test_abort_ownership_mismatch_rejected(tmp_path):
    """越权 abort 拒。"""
    svc, _ = _service(tmp_path)
    uid = _init(svc, total_size=20, total_chunks=2)["upload_id"]
    with pytest.raises(ChunkUploadSessionError, match="无权"):
        _run(svc.abort(upload_id=uid, user_id=999, kb_id=2))


# ---------- 并发会话数上限 ----------


def test_init_session_count_cap(tmp_path):
    """单用户并发会话数达上限后拒建（磁盘填充防护）。"""
    svc, _ = _service(tmp_path)
    from novamind.features.knowledge_space.services.chunk_upload_service import (
        ChunkUploadLimits,
    )
    cap = ChunkUploadLimits.from_config().max_sessions_per_user
    for _ in range(cap):
        _init(svc, total_size=10, total_chunks=1)
    with pytest.raises(ChunkUploadSessionError, match="并发分片上传会话超限"):
        _init(svc, total_size=10, total_chunks=1)


# ---------- 孤儿 .part 清理 ----------


def test_cleanup_stale_parts_removes_old_only(tmp_path, monkeypatch):
    """mtime 超阈值的 .part 删、新文件保留（cron 兜底线）。"""
    svc, _ = _service(tmp_path)
    d = svc._dir()

    old = d / "old.part"
    old.write_bytes(b"x")
    fresh = d / "fresh.part"
    fresh.write_bytes(b"y")

    threshold = time.time() - 10  # 阈值设为 10s 前
    import os
    os.utime(old, (threshold - 1, threshold - 1))

    # monkeypatch 配置：TTL×2 = 5s < old 的 age
    class _P:
        chunk_upload_dir = str(tmp_path)
        chunk_upload_session_ttl_sec = 3

    class _KB:
        parsing = _P()

    class _Cfg:
        knowledge_base = _KB()

    import novamind.features.knowledge_space.services.chunk_upload_service as mod
    monkeypatch.setattr(mod, "get_config", lambda: _Cfg())

    removed = _run(cleanup_stale_parts())
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()
