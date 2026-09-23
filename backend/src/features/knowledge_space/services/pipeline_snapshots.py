"""文档管道步骤快照：指纹计算 + MinIO 快照存取 + 级联失效。

为「断点续跑」提供基础设施：管道每完成一个可缓存步骤（parse/split/embed），
把产物快照到 MinIO，并在 ``document.storage["pipeline_snapshots"]`` 记录指纹指针；
重试时重新计算指纹，匹配则直接复用快照，跳过已成功的昂贵步骤（VLM/OCR/ASR/Embedding）。

指纹链：parse_fp → split_fp → embed_fp，上级指纹进入下级指纹计算，
任一环配置变化即从该环级联失效下游（parse 变 → 全部重做；split 变 → split+embed 重做）。
指纹等价是复用的唯一判据：失效清理只是存储卫生，清不掉也不会导致错误复用
（resume 前总会用当前配置重算指纹并比对）。

- 快照挂 document.storage JSON 列 + MinIO 对象，无 DB 迁移。
- 全链路 fail-open：快照缺失/损坏/上传失败只降级为全量重跑，绝不因快照让任务失败。
- 本模块属 feature 层：依赖 Document.storage 语义，minio_client/session 由调用方注入。
"""

import hashlib
import json
from typing import Any

from novamind.features.knowledge_space.models.document import Document
from novamind.shared.logging import get_logger
from novamind.shared.utils.time_utils import now_china
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# 总开关：置 False 全局关闭快照与续跑（旧文档无 pipeline_snapshots 键，天然走全量路径）
SNAPSHOTS_ENABLED = True

SNAPSHOT_VERSION = 1
FINGERPRINT_VERSION = 1

# Embedding 客户端实现签名：进入 embed 指纹。凡影响向量取值的客户端改动
# （预处理/归一化等）必须 bump 使已有向量快照失效、强制重算；
# 仅重试/容错类修复（不影响向量取值）不需要 bump。
# v2 (2026-09-07)：新增控制字符清洗——送入模型的文本变了，向量取值随之改变。
EMBEDDING_CLIENT_SIGNATURE = "openai-compatible-v2-sanitize"

# document.storage 中快照指针的键名
SNAPSHOT_STORAGE_KEY = "pipeline_snapshots"


# ========== 指纹计算 ==========


def canonical_sha256(payload: Any) -> str:
    """对任意 JSON 可序列化 payload 计算规范化 sha256。

    键排序 + 紧凑分隔符 + 不转义非 ASCII，保证同语义 payload 哈希稳定；
    不可序列化对象经 ``default=str`` 兜底（如 datetime）。
    """
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_json(payload: Any) -> str:
    """与 canonical_sha256 同一套规范化的 JSON 串（用于配置漂移比对）。"""
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    )


def compute_parse_fingerprint(document: Document, parsing_config: dict[str, Any]) -> str:
    """解析指纹：文件内容哈希/类型 + 解析配置任一变化即失效。"""
    return canonical_sha256({
        "v": FINGERPRINT_VERSION,
        "kind": "parse",
        "file_hash": getattr(document, "file_hash", "") or "",
        "file_type": (getattr(document, "file_type", "") or "").lower(),
        "parsing_config": parsing_config,
    })


def compute_split_fingerprint(
    parse_fingerprint: str,
    split_mode: str,
    splitting_config: dict[str, Any],
) -> str:
    """切分指纹：解析指纹进入计算，parse 失效自动级联 split。"""
    return canonical_sha256({
        "v": FINGERPRINT_VERSION,
        "kind": "split",
        "parse_fingerprint": parse_fingerprint,
        "split_mode": split_mode,
        "splitting_config": splitting_config,
    })


def compute_embed_fingerprint(split_fingerprint: str, embedding_config: dict[str, Any]) -> str:
    """向量指纹：只取向量语义相关字段 + 客户端实现签名。

    刻意不纳入 api_key/base_url 等连接凭据：凭据轮换不应使已有向量失效。
    batch_size 虽理论上不影响单条向量取值，但部分服务商按批内文长摊派行为存在差异，
    保守纳入以避免跨批次配置的向量混用。
    """
    cfg = embedding_config or {}
    return canonical_sha256({
        "v": FINGERPRINT_VERSION,
        "kind": "embed",
        "split_fingerprint": split_fingerprint,
        "model": cfg.get("model"),
        "dimension": cfg.get("dimension"),
        "batch_size": cfg.get("batch_size"),
        "client_signature": EMBEDDING_CLIENT_SIGNATURE,
    })


# ========== storage 指针读取 ==========


def _snapshot_state(document: Document) -> dict[str, Any]:
    storage = getattr(document, "storage", None) or {}
    state = storage.get(SNAPSHOT_STORAGE_KEY)
    return state if isinstance(state, dict) else {}


def _base_object_name(document: Document) -> str:
    storage = getattr(document, "storage", None) or {}
    return storage.get("minio_object_name", "") or ""


def parse_meta_object_name(document: Document) -> str:
    return f"{_base_object_name(document)}_parsed/parse_meta.json"


def chunks_object_name(document: Document) -> str:
    return f"{_base_object_name(document)}_artifacts/chunks.json"


def embeddings_object_name(document: Document) -> str:
    return f"{_base_object_name(document)}_artifacts/embeddings.json"


def snapshot_fingerprint(document: Document, level: str) -> str:
    """读取已记录的指纹；无快照或层级未知返回空串。

    level ∈ {"parse", "split", "embed"}。
    """
    key_map = {"parse": "parse_fingerprint", "split": "split_fingerprint", "embed": "embed_fingerprint"}
    key = key_map.get(level)
    if not key:
        return ""
    return str(_snapshot_state(document).get(key) or "")


# ========== MinIO JSON 存取 ==========


async def _upload_json(minio_client, object_name: str, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    await minio_client.upload_file(object_name, data, "application/json; charset=utf-8")


async def _download_json(document: Document, minio_client, object_name: str) -> dict[str, Any]:
    """下载并反序列化快照 JSON。对象缺失/网络错误向上抛，由调用方 fail-open。"""
    bucket = document.get_minio_bucket()
    if not bucket:
        raise ValueError(f"文档 {document.id} 无 minio_bucket，无法读取快照")
    raw = await minio_client.download_document(bucket_name=bucket, object_name=object_name)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("快照内容不是 JSON 对象")
    return payload


# ========== 快照保存（fail-open） ==========


async def _save_snapshot(
    document: Document,
    session: AsyncSession,
    logger,
    *,
    minio_client,
    object_name: str,
    payload: dict[str, Any],
    state_patch: dict[str, Any],
) -> bool:
    """上传快照 JSON → 更新 storage 指针 → commit。失败返回 False 不影响主流程。"""
    if not SNAPSHOTS_ENABLED:
        return False
    try:
        await _upload_json(minio_client, object_name, payload)
        storage = getattr(document, "storage", None) or {}
        state = dict(storage.get(SNAPSHOT_STORAGE_KEY) or {})
        state.update(state_patch)
        state["version"] = SNAPSHOT_VERSION
        state["updated_at"] = now_china().isoformat()
        document.storage = {**storage, SNAPSHOT_STORAGE_KEY: state}
        await session.commit()
        logger.info(
            "管道快照已保存",
            document_id=document.id,
            object_name=object_name,
        )
        return True
    except Exception as exc:
        logger.warning(
            "管道快照保存失败（降级为无快照，不影响主流程）",
            document_id=document.id,
            object_name=object_name,
            error=str(exc),
        )
        return False


def build_parse_snapshot_payload(
    *,
    parse_fingerprint: str,
    full_text: str,
    parse_metadata: dict[str, Any] | None = None,
    prechunked_items: list[tuple[str, dict[str, Any]]] | None = None,
    time_alignment: dict[str, Any] | None = None,
    frame_paths: dict[int, str] | None = None,
    splitting_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 parse_meta.json payload，各模态分支共用同一结构。

    - full_text：**占位符未替换**的解析全文（figure 占位符在 resume 时重签 URL
      后再替换；存已替换版会让 1 小时时效的预签名 URL 焊死在快照/ES 里）
    - prechunked_items：结构化分块 [[text, per_chunk_meta], ...]（DeepDoc 等）
    - time_alignment / frame_paths：音视频的时间对齐与帧路径
    - splitting_config：产出 prechunked_items 时的生效切分配置。文本切分实际
      发生在 parse 阶段内（DeepDoc rechunk），而 parse 指纹不含切分配置——
      resume 时据此比对：切分配置变了就从 full_text 重切，不采纳旧分块
      （审计 P1#3：否则改切分配置+RETRY 静默复用旧切分还白烧 embedding）。
    """
    payload: dict[str, Any] = {
        "version": SNAPSHOT_VERSION,
        "parse_fingerprint": parse_fingerprint,
        "full_text": full_text,
        "parse_metadata": parse_metadata or {},
        "prechunked_items": [[text, dict(meta or {})] for text, meta in (prechunked_items or [])],
    }
    if splitting_config is not None:
        payload["splitting_config"] = splitting_config
    if time_alignment:
        payload["time_alignment"] = time_alignment
    if frame_paths:
        # 键为 int，JSON 序列化自动转 str；读取时用 restore_frame_paths 还原
        payload["frame_paths"] = {str(k): v for k, v in frame_paths.items()}
    return payload


async def save_parse_snapshot(
    document: Document,
    session: AsyncSession,
    logger,
    *,
    minio_client,
    parse_fingerprint: str,
    payload: dict[str, Any],
) -> bool:
    """保存解析快照到 ``{base}_parsed/parse_meta.json`` 并记录指针。"""
    object_name = parse_meta_object_name(document)
    return await _save_snapshot(
        document, session, logger,
        minio_client=minio_client,
        object_name=object_name,
        payload=payload,
        state_patch={
            "parse_fingerprint": parse_fingerprint,
            "parse_meta_object": object_name,
        },
    )


async def save_split_snapshot(
    document: Document,
    session: AsyncSession,
    logger,
    *,
    minio_client,
    split_fingerprint: str,
    chunk_items: list[tuple[str, dict[str, Any]]],
    alignment_applied: bool = False,
) -> bool:
    """保存切分快照到 ``{base}_artifacts/chunks.json``。

    ``alignment_applied`` 标记快照是否已含时间对齐结果（音视频对齐发生在切分后，
    防止 resume 时对已对齐的 chunk 二次对齐）。
    """
    payload = {
        "version": SNAPSHOT_VERSION,
        "split_fingerprint": split_fingerprint,
        "alignment_applied": bool(alignment_applied),
        "chunk_items": [[text, dict(meta or {})] for text, meta in chunk_items],
    }
    object_name = chunks_object_name(document)
    return await _save_snapshot(
        document, session, logger,
        minio_client=minio_client,
        object_name=object_name,
        payload=payload,
        state_patch={
            "split_fingerprint": split_fingerprint,
            "chunks_object": object_name,
        },
    )


def _round_embeddings(embeddings: list[list[float] | None]) -> list[list[float] | None]:
    """向量降精度到 6 位小数：1k×1024 维约 10-12MB，肉眼无损召回，显著省存储。"""
    rounded: list[list[float] | None] = []
    for vec in embeddings:
        if vec is None:
            rounded.append(None)
        else:
            rounded.append([round(float(v), 6) for v in vec])
    return rounded


async def save_embeddings_snapshot(
    document: Document,
    session: AsyncSession,
    logger,
    *,
    minio_client,
    embed_fingerprint: str,
    embeddings: list[list[float] | None],
    embedding_model: str = "",
) -> bool:
    """保存向量快照到 ``{base}_artifacts/embeddings.json``。"""
    payload = {
        "version": SNAPSHOT_VERSION,
        "embed_fingerprint": embed_fingerprint,
        "embedding_model": embedding_model,
        "embeddings": _round_embeddings(embeddings),
    }
    object_name = embeddings_object_name(document)
    return await _save_snapshot(
        document, session, logger,
        minio_client=minio_client,
        object_name=object_name,
        payload=payload,
        state_patch={
            "embed_fingerprint": embed_fingerprint,
            "embeddings_object": object_name,
            "embedding_model": embedding_model,
        },
    )


# ========== 快照读取（fail-open） ==========


def payload_fingerprint_matches(payload: dict[str, Any], fingerprint_key: str, expected: str) -> bool:
    """校验快照 payload 内嵌指纹与重算指纹一致。

    只比 DB 指针（storage 里的指纹）不比 payload 内嵌指纹时，同文档双 worker
    交错写同名对象可能让指针 A 配上对象内容 B，静默采纳错位产物（审计 P2）。
    """
    if not expected:
        return True  # 调用方未启用指纹比对时跳过（与历史行为一致）
    actual = str(payload.get(fingerprint_key) or "")
    return actual == expected


async def load_parse_snapshot(
    document: Document,
    minio_client,
    logger,
) -> dict[str, Any] | None:
    """读取解析快照 payload。指针缺失/下载失败/坏 JSON → warning + None。"""
    state = _snapshot_state(document)
    object_name = state.get("parse_meta_object")
    if not object_name:
        return None
    try:
        return await _download_json(document, minio_client, str(object_name))
    except Exception as exc:
        logger.warning(
            "解析快照读取失败，按无快照处理（将全量重跑解析）",
            document_id=document.id,
            object_name=str(object_name),
            error=str(exc),
        )
        return None


async def load_split_snapshot(
    document: Document,
    minio_client,
    logger,
) -> dict[str, Any] | None:
    """读取切分快照，返回 {split_fingerprint, alignment_applied, chunk_items} 或 None。"""
    state = _snapshot_state(document)
    object_name = state.get("chunks_object")
    if not object_name:
        return None
    try:
        payload = await _download_json(document, minio_client, str(object_name))
        raw_items = payload.get("chunk_items")
        if not isinstance(raw_items, list):
            raise ValueError("chunk_items 缺失或格式异常")
        chunk_items = [(str(text), dict(meta or {})) for text, meta in raw_items]
        return {
            "split_fingerprint": str(payload.get("split_fingerprint") or ""),
            "alignment_applied": bool(payload.get("alignment_applied", False)),
            "chunk_items": chunk_items,
        }
    except Exception as exc:
        logger.warning(
            "切分快照读取失败，按无快照处理（将重跑切分）",
            document_id=document.id,
            object_name=str(object_name),
            error=str(exc),
        )
        return None


async def load_embeddings_snapshot(
    document: Document,
    minio_client,
    logger,
) -> dict[str, Any] | None:
    """读取向量快照，返回 {embed_fingerprint, embedding_model, embeddings} 或 None。"""
    state = _snapshot_state(document)
    object_name = state.get("embeddings_object")
    if not object_name:
        return None
    try:
        payload = await _download_json(document, minio_client, str(object_name))
        embeddings = payload.get("embeddings")
        if not isinstance(embeddings, list):
            raise ValueError("embeddings 缺失或格式异常")
        return {
            "embed_fingerprint": str(payload.get("embed_fingerprint") or ""),
            "embedding_model": str(payload.get("embedding_model") or ""),
            "embeddings": embeddings,
        }
    except Exception as exc:
        logger.warning(
            "向量快照读取失败，按无快照处理（将重算向量）",
            document_id=document.id,
            object_name=str(object_name),
            error=str(exc),
        )
        return None


# ========== 级联失效 ==========


# 各失效层级要删的 MinIO 对象指针键 与 要剪的 storage 状态键
_INVALIDATION_MAP = {
    "parse": (
        ("parse_meta_object", "chunks_object", "embeddings_object"),
        frozenset({
            "parse_fingerprint", "split_fingerprint", "embed_fingerprint",
            "parse_meta_object", "chunks_object", "embeddings_object", "embedding_model",
        }),
    ),
    "split": (
        ("chunks_object", "embeddings_object"),
        frozenset({
            "split_fingerprint", "embed_fingerprint",
            "chunks_object", "embeddings_object", "embedding_model",
        }),
    ),
    "embed": (
        ("embeddings_object",),
        frozenset({"embed_fingerprint", "embeddings_object", "embedding_model"}),
    ),
}


async def invalidate_snapshots_from(
    document: Document,
    minio_client,
    session: AsyncSession,
    logger,
    *,
    level: str,
) -> None:
    """从指定层级开始级联删除快照对象并剪掉 storage 指针。

    - parse → 删 parse_meta + chunks + embeddings，清空全部快照状态
    - split → 删 chunks + embeddings，剪 split/embed 指针
    - embed → 删 embeddings，剪 embed 指针

    清理失败不抛：指纹等价才是复用判据，残留对象最多浪费存储、不会导致错误复用。
    """
    state = _snapshot_state(document)
    mapping = _INVALIDATION_MAP.get(level)
    if not state or not mapping:
        if not mapping:
            logger.warning("未知快照层级，跳过失效", document_id=document.id, level=level)
        return

    object_keys, state_keys = mapping
    try:
        bucket = document.get_minio_bucket()
        if bucket:
            for key in object_keys:
                object_name = state.get(key)
                if not object_name:
                    continue
                try:
                    await minio_client.delete_document(
                        bucket_name=bucket, object_name=str(object_name)
                    )
                except Exception as exc:
                    logger.warning(
                        "快照对象删除失败（忽略）",
                        document_id=document.id,
                        object_name=str(object_name),
                        error=str(exc),
                    )

        storage = getattr(document, "storage", None) or {}
        new_state = {k: v for k, v in state.items() if k not in state_keys}
        new_storage = dict(storage)
        # 只剩 version/updated_at 等元数据（无任何指纹/对象指针）时，整个键一起删
        _META_KEYS = {"version", "updated_at"}
        has_pointers = any(k not in _META_KEYS for k in new_state)
        if has_pointers:
            new_storage[SNAPSHOT_STORAGE_KEY] = new_state
        else:
            new_storage.pop(SNAPSHOT_STORAGE_KEY, None)
        document.storage = new_storage
        await session.commit()
        logger.info("管道快照已失效", document_id=document.id, level=level)
    except Exception as exc:
        logger.warning(
            "管道快照失效失败（忽略，resume 以指纹比对为准）",
            document_id=document.id,
            level=level,
            error=str(exc),
        )


# ========== figure 图片 URL 重签 ==========


async def refresh_figure_image_urls(
    document: Document,
    parse_meta_payload: dict[str, Any],
    minio_client,
    logger,
    *,
    expires: int = 3600,
) -> dict[str, str]:
    """按 minio_object_name 重新签发 figure 图片的预签名 URL。

    快照保存的 parse_metadata.figure_regions 带有各图片的 minio_object_name 与
    当时的预签名 URL；预签名 URL 有时效，resume 复用快照时必须重签。
    原地更新 payload 中 figure_regions 的 image_url，返回 {artifact_id: new_url}，
    供调用方对全文/分块里的残留占位符做二次替换。
    """
    url_map: dict[str, str] = {}
    metadata = parse_meta_payload.get("parse_metadata")
    regions = metadata.get("figure_regions") if isinstance(metadata, dict) else None
    if not isinstance(regions, list):
        return url_map

    bucket = document.get_minio_bucket() or getattr(
        minio_client, "default_bucket", "knowledge-base"
    )
    for region in regions:
        if not isinstance(region, dict):
            continue
        object_name = region.get("minio_object_name")
        artifact_id = str(region.get("artifact_id") or "")
        if not object_name or not artifact_id:
            continue
        try:
            new_url = await minio_client.get_file_url(
                bucket_name=bucket, object_name=str(object_name), expires=expires,
            )
            region["image_url"] = new_url
            url_map[artifact_id] = new_url
        except Exception as exc:
            logger.warning(
                "figure 图片预签名 URL 重签失败（保留旧值）",
                document_id=document.id,
                artifact_id=artifact_id,
                error=str(exc),
            )
    return url_map


def restore_frame_paths(raw: dict[str, Any] | None) -> dict[int, str]:
    """把 JSON 里 str 键的 frame_paths 还原为 {int: str}（视频帧索引）。"""
    result: dict[int, str] = {}
    for key, value in (raw or {}).items():
        try:
            result[int(key)] = str(value)
        except (TypeError, ValueError):
            continue
    return result


def restore_time_alignment(
    raw: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """把快照里的 time_alignment 还原为 _run_post_parse_tail 期望的形状。

    - timeline_map 的 int 键经 JSON 序列化变 str，需还原为 {int: (start, end)}
    - frame_groups 同理还原为 {int: List[int]}
    - is_video 透传
    """
    if not isinstance(raw, dict) or "timeline_map" not in raw:
        return None
    timeline_map: dict[int, Any] = {}
    for key, value in (raw.get("timeline_map") or {}).items():
        try:
            timeline_map[int(key)] = value
        except (TypeError, ValueError):
            continue
    restored: dict[str, Any] = {
        "timeline_map": timeline_map,
        "is_video": bool(raw.get("is_video", False)),
    }
    raw_groups = raw.get("frame_groups")
    if isinstance(raw_groups, dict):
        frame_groups: dict[int, list[int]] = {}
        for key, members in raw_groups.items():
            try:
                frame_groups[int(key)] = [int(m) for m in (members or [])]
            except (TypeError, ValueError):
                continue
        restored["frame_groups"] = frame_groups
    return restored


# 快照状态里可能出现的全部键（除元数据外），parse 级失效时整体核对
_SNAPSHOT_POINTER_KEYS = frozenset({
    "parse_fingerprint", "parse_meta_object",
    "split_fingerprint", "chunks_object",
    "embed_fingerprint", "embeddings_object", "embedding_model",
})


def snapshot_has_level(document: Document, level: str) -> bool:
    """storage 中是否记录了指定层级的快照指针（不含指纹是否仍有效）。"""
    state = _snapshot_state(document)
    key_map = {
        "parse": ("parse_fingerprint", "parse_meta_object"),
        "split": ("split_fingerprint", "chunks_object"),
        "embed": ("embed_fingerprint", "embeddings_object"),
    }
    keys = key_map.get(level)
    if not keys:
        return False
    return any(state.get(k) for k in keys)
