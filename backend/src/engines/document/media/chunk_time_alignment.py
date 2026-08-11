"""媒体 chunk 时间元数据对齐引擎（音视频通用，纯逻辑，无 feature 依赖）。

拼接 md 时每帧/段首带双锚点 ``[HH:MM:SS#idx]``：时间戳给人看，``#idx``（帧/segment 序号）
给机器唯一反查（避免 ``frame_interval < 1s`` 时 int 秒时间戳撞锚点）。通用切分器切字符串后，
:func:`align_chunk_times` 正则提取 ``#idx`` → 查 timeline_map → 填 ``start_time``/``end_time``/
``frame_indices`` + 剥离锚点，得到进 embedding 的纯描述 content（消除时间戳噪声污染）。

本模块属 engines 纯逻辑层，不 import features/setting/ORM；timeline_map 由 features 装配点
（媒体解析流程）构建后注入。
"""
import re
from typing import Any, Dict, List, Optional, Tuple

# 切分后反查用：匹配 chunk 文本里的 [HH:MM:SS#idx] 双锚点（提取 idx）。
_ANCHOR_RE = re.compile(r"\[\d{2}:\d{2}:\d{2}#(\d+)\]")
# 锚点前缀剥离用：匹配 [HH:MM:SS#idx] 及其后空白，用于把 content 还原成纯描述。
_ANCHOR_PREFIX_RE = re.compile(r"\[\d{2}:\d{2}:\d{2}#\d+\]\s*")


def format_time(seconds: float) -> str:
    """格式化秒数为 ``HH:MM:SS``（int 秒，供锚点时间戳展示）。"""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_time_anchor(seconds: float, idx: int) -> str:
    """生成双锚点 ``[HH:MM:SS#idx]``。

    - ``seconds`` 取 int 秒展示（人读时间）；
    - ``idx`` 用帧/segment 序号（机器唯一反查，不受时间戳精度限制）。
    """
    return f"[{format_time(seconds)}#{idx}]"


def build_frame_timeline_map(
    descriptions: List[Tuple[str, float, int]],
) -> Dict[int, Tuple[Optional[float], Optional[float]]]:
    """从帧描述列表构建 ``{frame_idx: (start_sec, end_sec)}``。

    ``descriptions`` 为 ``[(desc, timestamp, frame_idx), ...]``，按 frame_idx 升序排序后，
    每帧 ``end`` = 下一帧 ``timestamp``（末帧 ``end=None``，视频末尾开放区间）。

    用 dict 而非 list：个别帧 VLM 失败被跳过时 frame_idx 仍递增、可能不连续，dict 按 idx 精确反查。
    """
    sorted_desc = sorted(descriptions, key=lambda d: d[2])  # 按 frame_idx 升序
    timeline: Dict[int, Tuple[Optional[float], Optional[float]]] = {}
    for i, (_, ts, frame_idx) in enumerate(sorted_desc):
        end_ts = sorted_desc[i + 1][1] if i + 1 < len(sorted_desc) else None
        timeline[frame_idx] = (ts, end_ts)
    return timeline


def build_segment_timeline_map(
    segments: List[Dict[str, Any]],
) -> Dict[int, Tuple[Optional[float], Optional[float]]]:
    """从 ASR segments 构建 ``{seg_idx: (start, end)}``。

    ``seg_idx`` 用 ``enumerate`` 原始 segments 顺序（跳过空文本的 seg 仍占原序号，保持与拼接锚点
    ``#seg_idx`` 一致）；ASR segment 自带 ``start``/``end``，直接取用。
    """
    timeline: Dict[int, Tuple[Optional[float], Optional[float]]] = {}
    for seg_idx, seg in enumerate(segments):
        if not seg.get("text", "").strip():
            continue
        timeline[seg_idx] = (seg.get("start", 0), seg.get("end"))
    return timeline


def align_chunk_times(
    chunk_items: List[Tuple[str, Dict[str, Any]]],
    timeline_map: Dict[int, Tuple[Optional[float], Optional[float]]],
    is_video: bool,
) -> List[Tuple[str, Dict[str, Any]]]:
    """切分后块到帧/segment 的时间对齐 + 剥离锚点。

    - 正则提取每个 chunk 文本里的 ``#idx`` 锚点 → 查 ``timeline_map`` 取 ``(start, end)``；
      chunk 时间区间 = ``[min(starts), max(ends)]``，视频填 ``frame_indices``。
    - 剥离 ``[HH:MM:SS#idx]`` 锚点前缀，返回纯描述文本（进 embedding，无时间戳噪声）。
    - 无锚点的块（单段超 chunk_size 被切成尾部块等罕见情形）start/end 填 None，前端标「时间未知」。
    - chunk 含 timeline_map 里没有的 idx（帧丢失等）被静默忽略，不报错。
    """
    aligned: List[Tuple[str, Dict[str, Any]]] = []
    for text, meta in chunk_items:
        idxs = [int(m) for m in _ANCHOR_RE.findall(text)]
        new_meta = dict(meta)
        if idxs:
            starts = [
                timeline_map[i][0]
                for i in idxs
                if i in timeline_map and timeline_map[i][0] is not None
            ]
            ends = [
                timeline_map[i][1]
                for i in idxs
                if i in timeline_map and timeline_map[i][1] is not None
            ]
            new_meta["start_time"] = min(starts) if starts else None
            new_meta["end_time"] = max(ends) if ends else None
            if is_video:
                new_meta["frame_indices"] = [i for i in idxs if i in timeline_map]
        else:
            new_meta.setdefault("start_time", None)
            new_meta.setdefault("end_time", None)
        clean_text = _ANCHOR_PREFIX_RE.sub("", text).strip()
        aligned.append((clean_text, new_meta))
    return aligned