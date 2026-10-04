"""媒体 chunk 时间元数据对齐引擎（音视频通用，纯逻辑，无 feature 依赖）。
双锚点 [HH:MM:SS#idx]：时间戳给人看，#idx 防帧间隔小于 1 秒时秒级时间戳撞锚点；切分后按 #idx 反查 timeline_map 回填时间区间并剥离锚点。
"""
import re
from typing import Any

# 切分后反查用：匹配 chunk 文本里的 [HH:MM:SS#idx] 双锚点（提取 idx）。
_ANCHOR_RE = re.compile(r"\[\d{2}:\d{2}:\d{2}#(\d+)\]")
# 锚点前缀剥离用：匹配 [HH:MM:SS#idx] 及其后空白，用于把 content 还原成纯描述。
_ANCHOR_PREFIX_RE = re.compile(r"\[\d{2}:\d{2}:\d{2}#\d+\]\s*")


def format_time(seconds: float) -> str:
    """格式化秒数为 ``HH:MM:SS``（int 秒，供锚点时间戳展示）。

    Args:
        seconds: 秒数（按 int 截断）。

    Returns:
        补零 HH:MM:SS 字符串。
    """
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_time_anchor(seconds: float, idx: int) -> str:
    """生成双锚点 ``[HH:MM:SS#idx]``。

    - ``seconds`` 取 int 秒展示（人读时间）；
    - ``idx`` 用帧/segment 序号（机器唯一反查，不受时间戳精度限制）。
    """
    return f"[{format_time(seconds)}#{idx}]"


def extract_anchor_indices(text: str) -> list[int]:
    """提取文本中所有 ``[HH:MM:SS#idx]`` 锚点的 idx，按出现顺序返回。

    供 rewrite 策略后处理校验：LLM 重写后锚点 idx 集合应与输入帧 idx 一致，
    不一致则回退原逐帧描述，保兜底。
    """
    return [int(m) for m in _ANCHOR_RE.findall(text)]


def build_frame_timeline_map(
    descriptions: list[tuple[str, float, int]],
) -> dict[int, tuple[float | None, float | None]]:
    """从帧描述列表构建 ``{frame_idx: (start_sec, end_sec)}``。

    ``descriptions`` 为 ``[(desc, timestamp, frame_idx), ...]``，按 frame_idx 升序排序后，
    每帧 ``end`` = 下一帧 ``timestamp``（末帧 ``end=None``，视频末尾开放区间）。

    用 dict 而非 list：个别帧 VLM 失败被跳过时 frame_idx 仍递增、可能不连续，dict 按 idx 精确反查。
    """
    sorted_desc = sorted(descriptions, key=lambda d: d[2])  # 按 frame_idx 升序
    timeline: dict[int, tuple[float | None, float | None]] = {}
    for i, (_, ts, frame_idx) in enumerate(sorted_desc):
        end_ts = sorted_desc[i + 1][1] if i + 1 < len(sorted_desc) else None
        timeline[frame_idx] = (ts, end_ts)
    return timeline


def build_segment_timeline_map(
    segments: list[dict[str, Any]],
) -> dict[int, tuple[float | None, float | None]]:
    """从 ASR segments 构建 ``{seg_idx: (start, end)}``。

    ``seg_idx`` 用 ``enumerate`` 原始 segments 顺序（跳过空文本的 seg 仍占原序号，保持与拼接锚点
    ``#seg_idx`` 一致）；ASR segment 自带 ``start``/``end``，直接取用。
    """
    timeline: dict[int, tuple[float | None, float | None]] = {}
    for seg_idx, seg in enumerate(segments):
        if not seg.get("text", "").strip():
            continue
        timeline[seg_idx] = (seg.get("start", 0), seg.get("end"))
    return timeline


def merge_audio_into_frame_lines(
    lines: list[str],
    segments: list[dict[str, Any]],
    timeline_map: dict[int, tuple[float | None, float | None]],
) -> tuple[list[str], dict[str, int]]:
    """把 ASR 旁白 segments 按 ``start`` 归入覆盖它的帧区间，注回描述行。

    行格式：``[HH:MM:SS#idx] 画面:... 旁白:...``（帧描述与旁白同锚点，
    切分后 ``align_chunk_times`` 零改动）。
    - segment 按 ``start`` 归属帧区间 ``[start, end)``；跨帧长 segment
      按 start 归属、不拆分（拆分会割裂语义完整的句子）；
    - 帧行无锚点（异常输入）原样保留；segment 落在首帧之前或所有帧区间
      空洞之外（末帧 end=None 视为覆盖到无穷远）时跳过并计入
      ``dropped``（调用方据此告警，旁白有无丢失可观测）。
    - 已带「旁白:」的行不重复注入（幂等，防 resume 二次拼接）；
      一行含多个锚点（rewrite LLM 偶发合并行）时汇总全部锚点的
      segment 注入首个锚点之后，不丢旁白。

    帧区间须按 start 升序且 end 单调不降（``build_frame_timeline_map``
    产物天然如此），据此对有序 ASR segments 做 cursor 前进线性扫 O(n+m)；
    segment 乱序时 cursor 回退重扫（正确性优先，退化为 O(n·m)）。

    Args:
        lines: 帧描述行列表（``[HH:MM:SS#idx] desc`` 格式）。
        segments: ASR segments（``{"start": float, "text": str}``）。
        timeline_map: ``{frame_idx: (start_sec, end_sec)}``，值可含 None。

    Returns:
        (新行列表, metrics)；metrics 键为 audio_segments_total（非空
        segment 总数）/ audio_segments_merged（注入到帧行的数量）/
        audio_segments_dropped（未归入的），可直接进 task metrics。
    """
    # 排序索引：frame_idx 升序的 (start, end, frame_idx)；end=None → inf（末帧开放区间）
    spans: list[tuple[float, float, int]] = []
    for idx, (start, end) in timeline_map.items():
        if start is None:
            continue
        spans.append((float(start), float(end) if end is not None else float("inf"), idx))
    spans.sort(key=lambda s: (s[0], s[2]))

    assigned: dict[int, list[str]] = {}
    total = 0
    cursor = 0
    last_start = -1.0
    for seg in segments:
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        total += 1
        start = seg.get("start")
        if start is None:
            continue
        start_f = float(start)
        if start_f < last_start:
            cursor = 0
        last_start = start_f
        # cursor 前进：跳过 end <= start 的区间（帧区间连续时一次扫过不回退）
        while cursor < len(spans) and spans[cursor][1] <= start_f:
            cursor += 1
        if cursor < len(spans) and spans[cursor][0] <= start_f:
            assigned.setdefault(spans[cursor][2], []).append((start_f, text))

    def _metrics(merged: int) -> dict[str, int]:
        return {
            "audio_segments_total": total,
            "audio_segments_merged": merged,
            "audio_segments_dropped": total - merged,
        }

    if not assigned:
        return list(lines), _metrics(0)

    # 帧内 segment 按时间排序（乱序 ASR 输入时保证旁白拼接时间有序）
    ordered = {idx: [t for _, t in sorted(pairs)] for idx, pairs in assigned.items()}
    merged_count = 0
    new_lines: list[str] = []
    for line in lines:
        if "旁白:" in line:
            # 幂等重跑：已注入的行跳过，其 segment 不计入本轮 merged
            new_lines.append(line)
            continue
        idxs = [int(m) for m in _ANCHOR_RE.findall(line)]
        if not idxs:
            new_lines.append(line)
            continue
        segs = [s for i in idxs for s in ordered.get(i, [])]
        if not segs:
            new_lines.append(line)
            continue
        merged_count += len(segs)
        m = _ANCHOR_RE.search(line)
        anchor_prefix = line[: m.end()]
        rest = line[m.end():].lstrip()
        new_lines.append(f"{anchor_prefix} 画面:{rest} 旁白:{' '.join(segs)}")
    # dropped 按「本轮未注入」计（幂等重跑时已注入 segment 也算 dropped，
    # 守恒式 total == merged + dropped 恒成立；首次运行的 dropped 即真丢失）
    return new_lines, _metrics(merged_count)


def align_chunk_times(
    chunk_items: list[tuple[str, dict[str, Any]]],
    timeline_map: dict[int, tuple[float | None, float | None]],
    is_video: bool,
    *,
    frame_groups: dict[int, list[int]] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """切分后块到帧/segment 的时间对齐 + 剥离锚点。

    - 正则提取每个 chunk 文本里的 ``#idx`` 锚点 → 查 ``timeline_map`` 取 ``(start, end)``；
      chunk 时间区间 = ``[min(starts), max(ends)]``，视频填 ``frame_indices``。
    - 剥离 ``[HH:MM:SS#idx]`` 锚点前缀，返回纯描述文本（进 embedding，无时间戳噪声）。
    - 无锚点的块（单段超 chunk_size 被切成尾部块等罕见情形）start/end 填 None，前端标「时间未知」。
    - chunk 含 timeline_map 里没有的 idx（帧丢失等）被静默忽略，不报错。
    - ``frame_groups``（grouped 策略用）：``{anchor_idx: [组内所有 frame_idx]}``。若提供且
      锚点 idx 在 frame_groups 中，``frame_indices`` 展开为组内所有帧 idx（供下游映射多帧图路径）；
      否则 ``frame_indices = [idx]``（single/rewrite 行为不变）。
    """
    aligned: list[tuple[str, dict[str, Any]]] = []
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
                fis: list[int] = []
                for i in idxs:
                    if i not in timeline_map:
                        continue
                    if frame_groups and i in frame_groups:
                        fis.extend(frame_groups[i])
                    else:
                        fis.append(i)
                new_meta["frame_indices"] = fis
        else:
            new_meta.setdefault("start_time", None)
            new_meta.setdefault("end_time", None)
        clean_text = _ANCHOR_PREFIX_RE.sub("", text).strip()
        aligned.append((clean_text, new_meta))
    return aligned