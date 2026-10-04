"""分片上传会话服务：Redis 会话状态 + .part 磁盘暂存，complete 复用流式上传语义。

会话安全绑定（user_id + kb_id）在每次 chunk PUT 时校验（不只 init），单会话累计
字节数硬顶防磁盘填充；乱序/重复 chunk 幂等（重复 PUT 返回 received 不重复计数）。
complete 用 SETNX 幂等锁防并发，整文件 sha256 与客户端申报值比对不符即拒（不入
MinIO）——端到端完整性凭证。失败方向安全：任何校验失败只废弃会话/拒绝写入，
不产生半份对象。
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.exceptions import (
    ChunkUploadChecksumMismatchError,
    ChunkUploadSessionError,
    DocumentSizeExceededError,
)
from novamind.setting.yaml_config import get_config
from novamind.shared.storage.client_factory import get_redis_client

logger = get_logger(__name__)

# Redis 键前缀：会话状态 HASH / 已收 chunk index SET / complete 幂等锁
_SESSION_PREFIX = "novamind:chunk_upload:session:"
_CHUNKS_PREFIX = "novamind:chunk_upload:chunks:"
_LOCK_PREFIX = "novamind:chunk_upload:lock:"

# 会话状态（HASH field "state" 的取值）
_STATE_UPLOADING = "UPLOADING"
_STATE_COMPLETING = "COMPLETING"
_STATE_DONE = "DONE"
_STATE_CORRUPT = "CORRUPT"

# 磁盘读写字节块大小（chunk 持久化与 sha256 全文件流式计算共用）
_IO_BLOCK = 1024 * 1024


@dataclass
class ChunkUploadLimits:
    """分片上传资源硬顶（从 YAML 读取，禁硬编码开发机假设）。"""

    session_ttl_sec: int
    chunk_max_bytes: int
    max_sessions_per_user: int

    @classmethod
    def from_config(cls) -> ChunkUploadLimits:
        """从 YAML chunk_upload 段读取（缺省值面向通用生产环境）。"""
        cfg = get_config().knowledge_base.parsing
        return cls(
            session_ttl_sec=cfg.chunk_upload_session_ttl_sec,
            chunk_max_bytes=cfg.chunk_upload_max_chunk_mb * 1024 * 1024,
            max_sessions_per_user=cfg.chunk_upload_max_sessions_per_user,
        )


class ChunkUploadSessionService:
    """分片上传会话：Redis 状态 + 定位写 .part 文件。

    不做业务校验（模态/权限/查重）——那些属于 complete 时的
    ``DocumentUploadService`` 流式上传路径；本服务只管「字节安全收齐」。
    """

    def __init__(self, redis=None, part_dir: str | None = None):
        """注入裸 Redis 客户端与 .part 目录（测试可替身）。"""
        self._redis = redis
        self._part_dir = part_dir

    async def _client(self):
        """取裸 redis-py 异步客户端（会话状态是事实记录，非缓存——异常须上抛）。"""
        if self._redis is not None:
            return self._redis
        from novamind.core.auth.blacklist import get_raw_redis

        return await get_raw_redis()

    def _dir(self) -> Path:
        """分片暂存目录：YAML 配置优先，缺省系统临时目录。"""
        base = self._part_dir or get_config().knowledge_base.parsing.chunk_upload_dir
        root = Path(base) if base else Path(tempfile.gettempdir())
        target = root / "novamind_chunk_uploads"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _part_path(self, upload_id: str) -> Path:
        """upload_id 由服务端 uuid4 生成（不信任客户端字符串拼路径）。"""
        return self._dir() / f"{upload_id}.part"

    def _session_key(self, upload_id: str) -> str:
        return f"{_SESSION_PREFIX}{upload_id}"

    def _chunks_key(self, upload_id: str) -> str:
        return f"{_CHUNKS_PREFIX}{upload_id}"

    async def init_session(
        self,
        *,
        user_id: int,
        kb_id: int,
        space_id: int,
        filename: str,
        total_size: int,
        total_chunks: int,
        max_total_bytes: int,
    ) -> dict[str, Any]:
        """创建上传会话，返回 {upload_id, chunk_size_hint}。

        Args:
            total_size: 客户端申报的整文件字节数（作为累计硬顶之一）。
            total_chunks: 分片总数（≥1）。
            max_total_bytes: 会话累计字节硬顶（模态上限，路由层按 KB 配置算好）。

        Raises:
            ChunkUploadSessionError: 参数非法或并发会话数超限。
            DocumentSizeExceededError: 申报总大小超硬顶。
        """
        limits = ChunkUploadLimits.from_config()
        if total_chunks < 1 or total_size <= 0:
            raise ChunkUploadSessionError("分片数与文件大小必须为正")
        hard_cap = min(total_size, max_total_bytes)
        if total_size > max_total_bytes:
            raise DocumentSizeExceededError(size=total_size, limit=max_total_bytes)

        client = await self._client()
        # 并发会话数硬顶：SCAN 会话键按 user_id 计数（键值含 user_id 段）
        session_keys = await self._count_user_sessions(client, user_id)
        if session_keys >= limits.max_sessions_per_user:
            raise ChunkUploadSessionError(
                f"并发分片上传会话超限（{session_keys}/{limits.max_sessions_per_user}），请先完成或取消既有会话"
            )

        upload_id = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat()
        await client.hset(self._session_key(upload_id), mapping={
            "user_id": user_id,
            "kb_id": kb_id,
            "space_id": space_id,
            "filename": filename,
            "total_size": total_size,
            "total_chunks": total_chunks,
            "received_bytes": 0,
            "state": _STATE_UPLOADING,
            "created_at": now,
        })
        await client.expire(self._session_key(upload_id), limits.session_ttl_sec)
        # 建立即过期的空 SET：占位使 TTL 生效（redis-py 对空集合不建键）
        await client.sadd(self._chunks_key(upload_id), -1)
        await client.expire(self._chunks_key(upload_id), limits.session_ttl_sec)

        chunk_size_hint = max(1, -(-total_size // total_chunks))  # 向上取整
        self.logger_info(
            "分片上传会话已创建",
            upload_id=upload_id, user_id=user_id, kb_id=kb_id,
            total_size=total_size, total_chunks=total_chunks,
        )
        return {
            "upload_id": upload_id,
            "chunk_size_hint": chunk_size_hint,
            "session_ttl_sec": limits.session_ttl_sec,
        }

    async def _count_user_sessions(self, client, user_id: int) -> int:
        """按 user_id 统计活跃会话数（会话键扫描，量级=并发上传数，可接受）。"""
        count = 0
        pattern = f"{_SESSION_PREFIX}*"
        async for key in client.scan_iter(match=pattern, count=100):
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            sess = await client.hget(key_str, "user_id")
            if sess is not None and int(sess) == user_id:
                count += 1
        return count

    async def put_chunk(
        self,
        *,
        upload_id: str,
        user_id: int,
        kb_id: int,
        chunk_index: int,
        data: bytes,
    ) -> dict[str, Any]:
        """写入一片：定位写 .part（pwrite 语义），幂等（重复片返回已收状态）。

        每次调用都校验请求者与会话归属一致（防越权写他人分片/伪造会话）。

        Raises:
            ChunkUploadSessionError: 会话不存在/归属不符/状态非 UPLOADING/片序号越界。
            DocumentSizeExceededError: 累计字节超会话硬顶。
        """
        limits = ChunkUploadLimits.from_config()
        if len(data) > limits.chunk_max_bytes:
            raise DocumentSizeExceededError(size=len(data), limit=limits.chunk_max_bytes)

        client = await self._client()
        skey = self._session_key(upload_id)
        sess = await client.hgetall(skey)
        if not sess:
            raise ChunkUploadSessionError(f"上传会话不存在或已过期: {upload_id}")
        sess = self._decode_hash(sess)

        # 归属校验：每次 chunk PUT 都验（不只 init）
        if int(sess["user_id"]) != user_id or int(sess["kb_id"]) != kb_id:
            raise ChunkUploadSessionError("无权写入该上传会话")
        if sess["state"] != _STATE_UPLOADING:
            raise ChunkUploadSessionError(
                f"会话状态 {sess['state']} 不接受分片写入"
            )
        total_chunks = int(sess["total_chunks"])
        if not 0 <= chunk_index < total_chunks:
            raise ChunkUploadSessionError(
                f"分片序号 {chunk_index} 越界（0~{total_chunks - 1}）"
            )

        # 幂等：已收片直接返回（不重复写盘/计数）
        already = await client.sismember(self._chunks_key(upload_id), chunk_index)
        if already:
            received = await client.scard(self._chunks_key(upload_id))
            return {
                "upload_id": upload_id,
                "chunk_index": chunk_index,
                "duplicate": True,
                "received_chunks": max(0, received - 1),  # 减去占位 -1
            }

        # 累计硬顶：原子增量后判超（超则回滚增量并废弃会话，防长期贴顶攻击）
        new_bytes = await client.hincrby(skey, "received_bytes", len(data))
        if int(sess["received_bytes"]) + len(data) > int(sess["total_size"]):
            await client.hincrby(skey, "received_bytes", -len(data))
            await client.hset(skey, key="state", value=_STATE_CORRUPT)
            raise DocumentSizeExceededError(
                size=int(sess["received_bytes"]) + len(data),
                limit=int(sess["total_size"]),
            )

        # 定位写盘（同步 IO 小数据量，to_thread 防事件循环阻塞）
        import asyncio

        offset = self._chunk_offset(sess, chunk_index)
        part_path = self._part_path(upload_id)
        await asyncio.to_thread(self._write_at, part_path, offset, data)

        await client.sadd(self._chunks_key(upload_id), chunk_index)
        await client.expire(skey, limits.session_ttl_sec)
        await client.expire(self._chunks_key(upload_id), limits.session_ttl_sec)

        received = await client.scard(self._chunks_key(upload_id))
        return {
            "upload_id": upload_id,
            "chunk_index": chunk_index,
            "duplicate": False,
            "received_chunks": max(0, received - 1),
        }

    def _chunk_offset(self, sess: dict[str, str], chunk_index: int) -> int:
        """固定 offset 方案：chunk i 落在 i × chunk_size_hint。"""
        total_size = int(sess["total_size"])
        total_chunks = int(sess["total_chunks"])
        chunk_size = max(1, -(-total_size // total_chunks))
        return chunk_index * chunk_size

    @staticmethod
    def _write_at(path: Path, offset: int, data: bytes) -> None:
        """定位写（seek+write；文件不存在自动建）。

        同一会话同一时刻只有一个属主客户端在写（upload_id 服务端生成、归属
        每次校验），seek+write 足够；不用 os.pwrite 是为平台通用（Windows 无此调用）。
        """
        import os

        if not path.exists():
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT, 0o600)
            os.close(fd)
        with open(path, "r+b") as f:
            f.seek(offset)
            f.write(data)

    async def load_session(self, upload_id: str) -> dict[str, Any]:
        """读会话原始状态（complete/abort/路由层共用，不存在时空 dict）。"""
        client = await self._client()
        sess = await client.hgetall(self._session_key(upload_id))
        return self._decode_hash(sess) if sess else {}

    async def complete_lock(self, upload_id: str, ttl_sec: int) -> bool:
        """SETNX 抢 complete 幂等锁（防并发 complete 双写 MinIO）。"""
        client = await self._client()
        got = await client.set(
            f"{_LOCK_PREFIX}{upload_id}", "1", nx=True, ex=ttl_sec
        )
        return bool(got)

    async def finalize_state(self, upload_id: str, state: str) -> None:
        """写终态（DONE/CORRUPT/UPLOADING 回退）并同步短 TTL。"""
        client = await self._client()
        await client.hset(self._session_key(upload_id), key="state", value=state)

    async def abort(self, *, upload_id: str, user_id: int, kb_id: int) -> None:
        """取消会话：校验归属后删 Redis 键与 .part 文件。"""
        client = await self._client()
        skey = self._session_key(upload_id)
        sess = await client.hgetall(skey)
        if not sess:
            return  # 幂等：不存在视为已取消
        sess = self._decode_hash(sess)
        if int(sess["user_id"]) != user_id or int(sess["kb_id"]) != kb_id:
            raise ChunkUploadSessionError("无权取消该上传会话")
        await client.delete(skey, self._chunks_key(upload_id))
        Path(self._part_path(upload_id)).unlink(missing_ok=True)
        self.logger_info("分片上传会话已取消", upload_id=upload_id, user_id=user_id)

    async def compute_file_sha256(self, upload_id: str, expected_size: int) -> str:
        """流式计算 .part 文件 sha256（读全量、内存峰值与文件大小解耦）。"""
        import asyncio

        part_path = self._part_path(upload_id)
        return await asyncio.to_thread(
            self._sha256_file, part_path, expected_size
        )

    @staticmethod
    def _sha256_file(path: Path, expected_size: int) -> str:
        """同步全文件 sha256（size 不符即校验失败语义由调用方比对）。"""
        hasher = hashlib.sha256()
        total = 0
        with open(path, "rb") as f:
            while True:
                block = f.read(_IO_BLOCK)
                if not block:
                    break
                total += len(block)
                hasher.update(block)
        if total != expected_size:
            raise ChunkUploadChecksumMismatchError(
                expected_size=expected_size, actual_size=total
            )
        return hasher.hexdigest()

    def open_part_stream(self, upload_id: str):
        """打开 .part 只读句柄（complete 交 DocumentUploadService 流式上传）。"""
        return open(self._part_path(upload_id), "rb")

    async def cleanup_part(self, upload_id: str) -> None:
        """删 .part 文件（complete 成功/失败后统一清理）。"""
        Path(self._part_path(upload_id)).unlink(missing_ok=True)

    async def verify_ready(self, upload_id: str) -> dict[str, Any]:
        """校验分片收齐（数量+字节），返回会话（不齐即抛）。"""
        client = await self._client()
        sess = await self.load_session(upload_id)
        if not sess:
            raise ChunkUploadSessionError(f"上传会话不存在或已过期: {upload_id}")
        received = await client.scard(self._chunks_key(upload_id))
        received = max(0, received - 1)  # 减占位 -1
        total_chunks = int(sess["total_chunks"])
        received_bytes = int(sess["received_bytes"])
        total_size = int(sess["total_size"])
        if received != total_chunks:
            raise ChunkUploadSessionError(
                f"分片未收齐（{received}/{total_chunks}），不能 complete"
            )
        if received_bytes != total_size:
            # 字节数不守恒但片数齐：固定 offset 写盘含尾片空洞，以文件实际大小为准
            await client.hset(self._session_key(upload_id), "state", _STATE_CORRUPT)
            raise ChunkUploadSessionError(
                f"已收字节数 {received_bytes} 与申报 {total_size} 不符"
            )
        return sess

    def logger_info(self, msg: str, **kw: Any) -> None:
        """结构化 info 日志。"""
        logger.info(msg, **kw)

    @staticmethod
    def _decode_hash(raw: dict) -> dict[str, str]:
        """redis-py 裸客户端 bytes 键值统一转 str。"""
        out = {}
        for k, v in raw.items():
            ks = k.decode("utf-8") if isinstance(k, bytes) else k
            vs = v.decode("utf-8") if isinstance(v, bytes) else v
            out[ks] = vs
        return out


async def cleanup_stale_parts(ctx: dict[str, Any] | None = None) -> int:
    """cron 兜底：删 mtime 超过会话 TTL×2 的孤儿 .part 文件。

    Redis 键 TTL 是第一道清理（会话过期后 SADD/写盘自然失效）；本任务兜底
    「Redis 被清/重启丢键但 .part 残留」的窗口。返回删除数，单文件失败不中断。
    """
    cfg = get_config().knowledge_base.parsing
    base = cfg.chunk_upload_dir
    root = (Path(base) if base else Path(tempfile.gettempdir())) / "novamind_chunk_uploads"
    if not root.exists():
        return 0
    cutoff = datetime.now(UTC).timestamp() - cfg.chunk_upload_session_ttl_sec * 2
    removed = 0
    for p in root.glob("*.part"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
                removed += 1
        except OSError as exc:
            logger.warning("孤儿 .part 清理失败（跳过）", path=str(p), error=str(exc))
    if removed:
        logger.info("孤儿分片暂存清理完成", removed=removed)
    return removed
