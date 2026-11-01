"""视频帧提取引擎：固定间隔抽帧 + 场景切换抽帧（灰度直方图卡方距离检测切换点）。
extract_frames_fixed 是旧函数 extract_video_frames 的策略化别名，原函数保留不破坏存量 import。
每个 *_from_path 变体是大文件管道入口：直接吃文件路径，省一次 bytes→临时文件落盘。
"""
from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path

from novamind.engines.document.media.video.video_normalizer import (
    normalize_video_for_frame_extraction,
)
from novamind.engines.document.media.video.video_utils import (
    VideoMetadataError,
    extract_video_frames,
    read_frame_at,
    read_video_metadata,
)

logger = logging.getLogger(__name__)

# 候选采样上限：场景抽帧先按采样步长读候选帧算直方图，避免长视频一次性载入过多帧。
_MAX_CANDIDATE_FRAMES = 200


async def extract_frames_fixed(
    file_content: bytes,
    interval: float = 5.0,
    max_frames: int = 60,
) -> list[tuple[bytes, float, int]]:
    """固定间隔抽帧（= 现有 ``extract_video_frames`` 行为，策略化别名）。

    返回 ``[(jpeg_bytes, timestamp, frame_idx), ...]``，frame_idx 从 0 递增。
    """
    return await extract_video_frames(file_content, interval, max_frames)


async def extract_frames_scene(
    file_content: bytes,
    max_frames: int = 60,
    *,
    scene_threshold: float = 0.003,
    min_interval: float = 2.0,
    sample_step: float | None = None,
) -> list[tuple[bytes, float, int]]:
    """场景切换抽帧（bytes 版）：写临时文件后委托路径版实现。"""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".video", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        return await extract_frames_scene_from_path(
            tmp_path, max_frames,
            scene_threshold=scene_threshold,
            min_interval=min_interval,
            sample_step=sample_step,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def extract_frames_scene_from_path(
    filepath: str,
    max_frames: int = 60,
    *,
    scene_threshold: float = 0.003,
    min_interval: float = 2.0,
    sample_step: float | None = None,
) -> list[tuple[bytes, float, int]]:
    """场景切换抽帧：按相邻帧灰度直方图卡方距离检测镜头切换点。

    流程：
    1. 按采样步长 ``sample_step``（默认 ``max(1.0, duration/_MAX_CANDIDATE_FRAMES)``）
       逐帧解码为候选帧并算灰度直方图；
    2. 相邻候选帧直方图卡方距离 ``>= scene_threshold`` 判为切换点；
    3. 切换点经 ``min_interval`` 间隔保护（过近的切换点丢弃后者）；
    4. 切换点数超过 ``max_frames`` 时均匀抽样到 ``max_frames``；
    5. 选中帧编码为 JPEG，frame_idx 从 0 递增返回。

    极端情形兜底：若切换点为 0（全程无明显切换，如静态幻灯片），退化为候选帧均匀采样，
    保证至少产出 1 帧。

    路径版（大文件管道入口）：直读失败时归一化兜底（产物临时文件自清理）；
    调用方传入的 ``filepath`` 不会被删除（生命周期归调用方）。

    返回 ``[(jpeg_bytes, timestamp, frame_idx), ...]``，与 ``extract_frames_fixed`` 同结构。
    """
    normalized_path: str | None = None
    try:
        try:
            return await asyncio.to_thread(
                _extract_scene_from_path,
                filepath,
                max_frames,
                scene_threshold,
                min_interval,
                sample_step,
            )
        except Exception as direct_error:
            logger.warning(
                "场景抽帧直读失败，进入转换层兜底",
                extra={
                    "source_path": filepath,
                    "error_type": type(direct_error).__name__,
                    "error": str(direct_error),
                },
            )
            normalized_path = await asyncio.to_thread(
                normalize_video_for_frame_extraction, filepath
            )
            return await asyncio.to_thread(
                _extract_scene_from_path,
                normalized_path,
                max_frames,
                scene_threshold,
                min_interval,
                sample_step,
            )
    finally:
        if normalized_path:
            Path(normalized_path).unlink(missing_ok=True)


def _extract_scene_from_path(
    filepath: str,
    max_frames: int,
    scene_threshold: float,
    min_interval: float,
    sample_step: float | None,
) -> list[tuple[bytes, float, int]]:
    """场景抽帧的同步实现（在 to_thread 中执行）。"""
    metadata = read_video_metadata(filepath)
    duration = metadata.get("duration", 0) or 0
    fps = metadata.get("fps", 30) or 30
    n_images = metadata.get("n_images", 0) or 0

    if duration <= 0:
        if n_images > 0 and fps > 0:
            duration = n_images / fps
        else:
            raise VideoMetadataError(
                f"无法读取视频时长或总帧数: duration={duration}, fps={fps}, n_images={n_images}"
            )

    # 采样步长：默认按候选上限均分，但不少于 1s（过密浪费解码）。
    if sample_step is None:
        sample_step = max(1.0, duration / _MAX_CANDIDATE_FRAMES)

    candidate_ts: list[float] = []
    t = 0.0
    while t < duration and len(candidate_ts) < _MAX_CANDIDATE_FRAMES:
        candidate_ts.append(t)
        t += sample_step

    # 逐候选帧解码 + 算灰度直方图。
    import numpy as np

    histograms: list[np.ndarray] = []
    valid_ts: list[float] = []
    for ts in candidate_ts:
        pil = read_frame_at(filepath, ts, fps)
        if pil is None:
            continue
        histograms.append(compute_gray_histogram(pil))
        valid_ts.append(ts)

    if not valid_ts:
        raise RuntimeError("场景抽帧未能解码任何候选帧")

    # 相邻候选帧卡方距离。
    distances: list[float] = []
    for i in range(1, len(histograms)):
        distances.append(histogram_chi_square(histograms[i - 1], histograms[i]))

    # 选切换点索引（基于候选帧 idx）。
    selected_candidate_idx = _select_scene_keyframes(
        distances=distances,
        num_candidates=len(valid_ts),
        threshold=scene_threshold,
        min_interval=min_interval,
        sample_step=sample_step,
        max_frames=max_frames,
        valid_ts=valid_ts,
    )

    # 兜底：无有效切换点 → 候选帧均匀采样（红队 P0-2：_select_scene_keyframes
    # 首帧必选使 selected 恒非空，`not selected` 判断是死代码——静态幻灯片类
    # 视频只会产出首帧。改判「≤1 个选中」即无切换点形态）
    if len(selected_candidate_idx) <= 1:
        selected_candidate_idx = _uniform_sample_indices(len(valid_ts), max_frames)

    # 导出选中帧为 JPEG。
    frames: list[tuple[bytes, float, int]] = []
    for frame_idx, cand_idx in enumerate(selected_candidate_idx):
        ts = valid_ts[cand_idx]
        pil = read_frame_at(filepath, ts, fps)
        if pil is None:
            continue
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=85)
        frames.append((buf.getvalue(), ts, frame_idx))

    if not frames:
        raise RuntimeError("场景抽帧选中帧均解码失败")

    return frames


# ========== 纯函数：直方图 + 切换点选择（无 IO，供单测） ==========


def compute_gray_histogram(pil_image) -> np.ndarray:  # noqa: F821
    """算 PIL 图像的归一化灰度直方图（256 bin，和为 1）。

    Args:
        pil_image: PIL 图像。

    Returns:
        长度 256 的归一化直方图数组（空图返回零数组）。
    """
    import numpy as np

    gray = pil_image.convert("L")
    hist = gray.histogram()  # 长度 256
    arr = np.asarray(hist, dtype=np.float64)
    total = arr.sum()
    if total <= 0:
        return arr
    return arr / total


def histogram_chi_square(h1: np.ndarray, h2: np.ndarray) -> float:  # noqa: F821
    """两归一化直方图的平均卡方距离（红队 P0-1 量级标定修正）。

    卡方距离 ``sum((h1-h2)^2 / (h1+h2))``，分母为 0 的 bin 跳过；除以活跃
    bin 数得平均量级。**注意量级**：归一化直方图的卡方上界为 2，除以活跃
    bin 数（真实视频 100~256）后实际量级被压缩约两个数量级——硬切点实测
    ≈0.0065，同场景相邻帧接近 0。消费方默认阈值按此实测标定：
    ``scene_threshold=0.003``、dedup 相似度 cutoff=0.995（合成硬切视频
    对照实验验证）。此前注释声称「约 [0, 1]」导致默认阈值 0.3/0.95 在
    真实视频上永不触发（scene 检测失效、dedup 全部误判相似丢帧）。
    """
    import numpy as np

    denom = h1 + h2
    mask = denom > 0
    if not mask.any():
        return 0.0
    diff = h1[mask] - h2[mask]
    chi = float(np.sum((diff * diff) / denom[mask]))
    return chi / mask.sum()


def _select_scene_keyframes(
    distances: list[float],
    num_candidates: int,
    threshold: float,
    min_interval: float,
    sample_step: float,
    max_frames: int,
    valid_ts: list[float] | None = None,
) -> list[int]:
    """从相邻候选帧距离序列选场景切换关键帧，返回候选帧索引列表。

    - ``distances`` 长度 = ``num_candidates - 1``，``distances[i]`` 是候选帧 i 与 i+1 的距离；
    - 距离 ``>= threshold`` 判为切换点，切换点取「后一帧」候选 idx（即 ``i+1``）；
    - ``min_interval`` 保护：与上一个选中切换点时间间隔不足时丢弃后者；
    - 选中数 ``> max_frames`` 时均匀抽样到 ``max_frames``；
    - 首帧（idx 0）始终纳入（保证视频起点有描述），不受 threshold 约束。
    """
    if num_candidates <= 0:
        return []

    selected: list[int] = [0]  # 首帧必选
    last_ts = 0.0
    for i, dist in enumerate(distances):
        if dist < threshold:
            continue
        cand_idx = i + 1
        # 红队 P3：候选帧解码失败时名义时刻与 valid_ts 实际时刻错位——门控
        # 优先用实际时刻（导出侧同源），无实测量表时退回名义值
        cand_ts = valid_ts[cand_idx] if valid_ts and cand_idx < len(valid_ts) else cand_idx * sample_step
        if cand_ts - last_ts < min_interval:
            continue
        selected.append(cand_idx)
        last_ts = cand_ts

    if len(selected) > max_frames:
        selected = _uniform_sample_indices(len(selected), max_frames, base=selected)
    return selected


def _uniform_sample_indices(
    total: int,
    max_frames: int,
    *,
    base: list[int] | None = None,
) -> list[int]:
    """从 ``total`` 个候选中均匀抽 ``max_frames`` 个，返回其在 ``base``（或 range(total)）中的索引。

    ``base`` 为 None 时候选即 ``range(total)``；非 None 时从 ``base`` 列表里按均匀步长抽样。
    """
    if total <= 0:
        return []
    if max_frames <= 0:
        # 防御（红队 P3）：schema 默认 60 难触发，但显式 0/负值时除零崩溃
        return []
    if total <= max_frames:
        return list(base) if base is not None else list(range(total))
    step = total / max_frames
    picked = [int(i * step) for i in range(max_frames)]
    if base is not None:
        return [base[p] for p in picked]
    return picked

# ========== 自适应抽帧（adaptive）：粗采特征 → FPS 预算选代表帧 → 按时间戳精抽 ==========

# FPS 选帧的默认时间间隔下限（秒）：选中的代表帧彼此至少相距这么远，保证时间
# 分布下限——完全静止的视频里所有候选互为近邻（汉明距离趋零），没有该约束时
# 代表帧会在时间上堆叠。语义同 scene 策略的 min_interval，但这里约束的是
# 「已选集」双向近邻而非相邻切换点。
_ADAPTIVE_MIN_INTERVAL = 1.0

# 覆盖距离阈值：未选候选与已选集的最近汉明距离 ≤ 该值即视为「已覆盖」，
# FPS 提前终止。量级标定（合成静态视频实测，6 轮对照）：同一画面的 seek 解码
# + 编码噪声使 pHash 距离在 0~4 波动（JPEG/YUV 转换与 seek 恢复点差异），
# 而真实场景切换的距离远超 10（pHash 惯例 ≤10 判同图）。取 6 = 覆盖实测噪声
# 上界 4 加裕量，同时与真实变化保持安全距离；继续选噪声距离内的帧只会浪费
# VLM 预算。若未来引入 CLIP 语义特征，该阈值需随特征空间重新标定。
_ADAPTIVE_COVERAGE_DISTANCE = 6


def compute_phash(pil_image) -> int:  # noqa: F821
    """计算 PIL 图像的感知哈希（pHash，64bit 整数）。

    32x32 灰度 → 2D DCT-II → 左上 8x8 低频块（丢 DC 分量）→ 逐位按中位数阈值化。
    纯 numpy 实现（DCT 矩阵一次乘法），零外部模型依赖。

    视觉上相近的图 hash 汉明距离小（0≈相同），内容差异越大距离越大——对亮度
    线性漂移、轻微压缩噪声稳定，适合做"感知唯一性"度量。

    Args:
        pil_image: PIL 图像（任意尺寸，内部统一缩放到 32x32）。

    Returns:
        64bit 整数哈希。
    """
    import numpy as np

    gray = pil_image.convert("L").resize((32, 32))
    arr = np.asarray(gray, dtype=np.float64)
    # DCT-II 变换矩阵（正交归一）：D[k, n] = s_k * cos(pi*(2n+1)*k / (2N))
    n = 32
    k_idx = np.arange(n).reshape(-1, 1)
    nn = np.arange(n).reshape(1, -1)
    d = np.cos(np.pi * (2 * nn + 1) * k_idx / (2 * n)) * np.sqrt(2.0 / n)
    d[0, :] = np.sqrt(1.0 / n)
    dct = d @ arr @ d.T
    low = dct[:8, :8].flatten()[1:]  # 左上 8x8 低频块，丢 DC 分量
    median = np.median(low)
    bits = (low > median).astype(np.int64)
    return int(sum(int(bit) << i for i, bit in enumerate(bits)))


def hamming_distance(h1: int, h2: int) -> int:
    """两个 64bit 哈希的汉明距离（不同 bit 数，0~64）。"""
    return bin(h1 ^ h2).count("1")


def _select_adaptive_keyframes(
    hashes: list[int],
    valid_ts: list[float],
    budget: int,
    min_interval: float = _ADAPTIVE_MIN_INTERVAL,
) -> list[int]:
    """从候选帧哈希做最远点采样（FPS）选代表帧，返回候选索引列表（时间升序）。

    算法（覆盖保证下的冗余消除，"最少帧代表整个视频"的直接实现）：

    1. 起始帧 = 与其它所有候选总汉明距离最大的帧（最不寻常的画面）；
    2. 贪心循环：每轮选「距已选集最近距离最大」的未选候选（最远点），
       同时维护时间约束——与任一已选帧时间距离 < ``min_interval`` 的候选被
       屏蔽，保证代表帧的时间分布下限；
    3. 当最大最近距离 ≤ ``_ADAPTIVE_COVERAGE_DISTANCE``（所有未屏蔽候选都已被
       已选集覆盖，如整段静止画面）提前终止——冗余塌缩是本策略的预期行为；
    4. 预算 ``budget`` 或候选穷尽即停。

    Args:
        hashes: 候选帧 pHash 列表。
        valid_ts: 与 hashes 对齐的时间戳（秒）。
        budget: 代表帧数上限（现有 max_frames 配置，>0）。
        min_interval: 已选帧间最小时间距离（秒）。

    Returns:
        候选帧索引列表，按时间戳升序。
    """
    n = len(hashes)
    if n == 0 or budget <= 0:
        return []
    if n == 1:
        return [0]

    # 距离矩阵（n ≤ 候选上限 200，O(n²) popcount 量级毫秒级）
    dm = [[hamming_distance(hashes[i], hashes[j]) for j in range(n)] for i in range(n)]

    # 起始帧：与其它帧总距离最大 = 全局最不寻常的画面
    first = max(range(n), key=lambda i: sum(dm[i]))
    selected = [first]
    # md[i] = 候选 i 到已选集的最近距离（FPS 增量维护）
    md = dm[first][:]
    last_selected_ts = valid_ts[first] if first < len(valid_ts) else 0.0

    while len(selected) < budget:
        pick = -1
        pick_dist = -1
        for i in range(n):
            if i in selected:
                continue
            ts_i = valid_ts[i] if i < len(valid_ts) else 0.0
            # 时间屏蔽：与最近已选帧的距离不足 min_interval 的候选不参选
            if abs(ts_i - last_selected_ts) < min_interval:
                continue
            if md[i] > pick_dist:
                pick = i
                pick_dist = md[i]
        if pick < 0 or pick_dist <= _ADAPTIVE_COVERAGE_DISTANCE:
            # 无可参选候选（时间屏蔽穷尽）或全覆盖（剩余候选与已选集距离都在
            # 覆盖阈值内，感知近重复）：提前终止——冗余塌缩是本策略的预期行为
            break
        selected.append(pick)
        last_selected_ts = valid_ts[pick] if pick < len(valid_ts) else 0.0
        md = [min(cur, dm[pick][i]) for i, cur in enumerate(md)]

    return sorted(selected)


def _extract_adaptive_from_path(
    filepath: str,
    max_frames: int,
    min_interval: float,
    candidate_step: float | None,
) -> list[tuple[bytes, float, int]]:
    """自适应抽帧的同步实现（在 to_thread 中执行）：两遍法。

    第一遍逐候选解码算 pHash（小成本特征）；FPS 全局选代表帧；第二遍只对
    选中帧重新解码导出全尺寸 JPEG。特征计算异常时降级为候选均匀采样（覆盖
    不劣于 fixed），保证失败方向安全。
    """
    metadata = read_video_metadata(filepath)
    duration = metadata.get("duration", 0) or 0
    fps = metadata.get("fps", 30) or 30
    n_images = metadata.get("n_images", 0) or 0

    if duration <= 0:
        if n_images > 0 and fps > 0:
            duration = n_images / fps
        else:
            raise VideoMetadataError(
                f"无法读取视频时长或总帧数: duration={duration}, fps={fps}, n_images={n_images}"
            )

    if candidate_step is None:
        candidate_step = max(1.0, duration / _MAX_CANDIDATE_FRAMES)

    candidate_ts: list[float] = []
    t = 0.0
    while t < duration and len(candidate_ts) < _MAX_CANDIDATE_FRAMES:
        candidate_ts.append(t)
        t += candidate_step

    # 第一遍：逐候选解码 + pHash（解码失败项跳过，时间戳以实际可解码项为准）。
    # 特征/选帧异常 → 无法判定代表性 → 全量降级候选均匀采样（能力缺失优于
    # 错误结果，最差不劣于 fixed），不让单帧的图像库异常炸掉整个解析任务。
    hashes: list[int] = []
    valid_ts: list[float] = []
    selected_ts: list[float]
    try:
        for ts in candidate_ts:
            pil = read_frame_at(filepath, ts, fps)
            if pil is None:
                continue
            hashes.append(compute_phash(pil))
            valid_ts.append(ts)
        if not valid_ts:
            raise RuntimeError("自适应抽帧未能解码任何候选帧")
        selected_idx = _select_adaptive_keyframes(
            hashes, valid_ts, budget=max_frames, min_interval=min_interval
        )
        selected_ts = [valid_ts[i] for i in selected_idx]
    except Exception as exc:  # noqa: BLE001
        # 特征/选帧异常 → 候选时间戳均匀采样兜底（能力缺失优于错误结果，
        # 最差不劣于 fixed）。按时间戳而非候选索引工作，与特征失败前的
        # 部分解码状态解耦。
        logger.warning("自适应选帧异常，降级候选均匀采样", extra={"error": str(exc)})
        pick_idx = _uniform_sample_indices(len(candidate_ts), max_frames)
        selected_ts = [candidate_ts[i] for i in pick_idx]

    # 第二遍：只对选中时间戳解码导出全尺寸 JPEG
    frames: list[tuple[bytes, float, int]] = []
    for frame_idx, ts in enumerate(selected_ts):
        pil = read_frame_at(filepath, ts, fps)
        if pil is None:
            continue
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=85)
        frames.append((buf.getvalue(), ts, frame_idx))

    if not frames:
        raise RuntimeError("自适应抽帧选中帧均解码失败")

    return frames


async def extract_frames_adaptive(
    file_content: bytes,
    max_frames: int = 60,
    *,
    min_interval: float = _ADAPTIVE_MIN_INTERVAL,
    candidate_step: float | None = None,
) -> list[tuple[bytes, float, int]]:
    """自适应抽帧（bytes 版）：写临时文件后委托路径版实现。

    以「最少帧代表整个视频」为目标：全局最远点采样（FPS）消除冗余候选，
    时间间隔约束保证覆盖分布，预算复用 max_frames 配置，零阈值调参。
    特征/选帧异常时降级候选均匀采样，最差不劣于 fixed。

    Returns:
        ``[(jpeg_bytes, timestamp, frame_idx), ...]``，与其它抽帧策略同结构。
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".video", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        return await extract_frames_adaptive_from_path(
            tmp_path,
            max_frames,
            min_interval=min_interval,
            candidate_step=candidate_step,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def extract_frames_adaptive_from_path(
    filepath: str,
    max_frames: int = 60,
    *,
    min_interval: float = _ADAPTIVE_MIN_INTERVAL,
    candidate_step: float | None = None,
) -> list[tuple[bytes, float, int]]:
    """自适应抽帧（路径版，大文件管道入口）：直读失败走归一化兜底，同 scene。"""
    normalized_path: str | None = None
    try:
        try:
            return await asyncio.to_thread(
                _extract_adaptive_from_path,
                filepath,
                max_frames,
                min_interval,
                candidate_step,
            )
        except Exception as direct_error:
            logger.warning(
                "自适应抽帧直读失败，进入转换层兜底",
                extra={
                    "source_path": filepath,
                    "error_type": type(direct_error).__name__,
                    "error": str(direct_error),
                },
            )
            normalized_path = await asyncio.to_thread(
                normalize_video_for_frame_extraction, filepath
            )
            return await asyncio.to_thread(
                _extract_adaptive_from_path,
                normalized_path,
                max_frames,
                min_interval,
                candidate_step,
            )
    finally:
        if normalized_path:
            Path(normalized_path).unlink(missing_ok=True)
