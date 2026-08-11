"""视频帧去重引擎：none / frame_diff（直方图相似度）/ embedding（预留）。

纯逻辑层，不 import features/setting/ORM。``dedup_frame_diff`` 用相邻帧归一化灰度直方图
卡方距离判断相似度，相似帧丢弃后者、保留组首；去重后 frame_idx 重映射为连续序号，
与后续 ``format_time_anchor(ts, idx)`` 锚点对齐。

去重在「描述」之前执行，因此重映射后的连续 idx 即锚点 ``#idx``，``align_chunk_times``
反查时一一对应。``dedup_embedding`` 为预留枚举位，待图像 embedding 模型类型引入后实现。
"""
from __future__ import annotations

import io
import logging
from typing import Any, List, Optional, Tuple

from novamind.engines.document.media.video.frame_extraction import (
    _compute_gray_histogram,
    _histogram_chi_square,
)

logger = logging.getLogger(__name__)

# 默认相似度阈值：卡方距离归一化到 [0,1]，相似度 = 1 - 距离。
# 0.95 对应距离 0.05，仅极相似帧（近乎静止）被去重，保守避免误丢信息。
_DEFAULT_SIMILARITY_THRESHOLD = 0.95


def dedup_none(
    frames: List[Tuple[bytes, float, int]],
) -> List[Tuple[bytes, float, int]]:
    """不去重，原样返回（frame_idx 保持不变）。"""
    return list(frames)


def dedup_frame_diff(
    frames: List[Tuple[bytes, float, int]],
    *,
    similarity_threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
) -> List[Tuple[bytes, float, int]]:
    """相邻帧直方图相似度去重，保留组首帧。

    遍历帧序列，每帧与「上一个已保留帧」算归一化卡方距离；距离 ``<= 1 - similarity_threshold``
    判为相似 → 丢弃后者；否则保留。frame_idx 重映射为从 0 起的连续序号（与锚点 ``#idx`` 对齐）。

    返回去重后的 ``[(jpeg_bytes, timestamp, new_frame_idx), ...]``。
    """
    from PIL import Image

    if not frames:
        return []

    distance_cutoff = 1.0 - similarity_threshold
    kept: List[Tuple[bytes, float, int]] = []
    last_hist: Optional[Any] = None

    for frame_bytes, ts, _orig_idx in frames:
        try:
            pil = _decode_jpeg(frame_bytes)
            hist = _compute_gray_histogram(pil)
        except Exception as e:
            logger.warning("去重时帧解码失败，保留该帧", error=str(e))
            # 解码失败不能判定相似性，安全起见保留
            kept.append((frame_bytes, ts, len(kept)))
            continue

        if last_hist is None:
            kept.append((frame_bytes, ts, len(kept)))
            last_hist = hist
            continue

        dist = _histogram_chi_square(last_hist, hist)
        if dist <= distance_cutoff:
            # 相似，丢弃后者
            logger.debug("帧去重：相似帧丢弃", distance=round(dist, 4), ts=ts)
            continue

        kept.append((frame_bytes, ts, len(kept)))
        last_hist = hist

    return kept


def dedup_embedding(
    frames: List[Tuple[bytes, float, int]],
    *,
    embedding_client: Any = None,
    similarity_threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
) -> List[Tuple[bytes, float, int]]:
    """图像 embedding 去重（预留，首批不实现）。

    待 IMAGE_EMBEDDING 模型类型单独引入后实现：对每帧算图像 embedding，
    余弦相似度 ``>= similarity_threshold`` 判为相似，丢弃后者。
    当前抛 ``NotImplementedError``，由 features 编排层转 ``DocumentProcessingError``
    提示用户「该策略暂未实现，请选其他策略」。
    """
    raise NotImplementedError(
        "图像 embedding 去重尚未引入，待 IMAGE_EMBEDDING 模型类型支持；"
        "请改用 dedup_frame_diff 或 dedup_none 策略"
    )


def _decode_jpeg(frame_bytes: bytes):
    """从 JPEG bytes 解码为 PIL 图像（供 dedup 算直方图）。"""
    from PIL import Image

    return Image.open(io.BytesIO(frame_bytes))