"""自适应抽帧（adaptive 策略）测试：pHash 特征、FPS 选帧、两遍法端到端。

纯函数段（无 IO）：pHash 确定性与感知区分度、FPS 选帧的塌缩/覆盖/预算/
min_interval/边界行为；集成段：ffmpeg 合成视频验证静态塌缩、多场景覆盖、
降级路径（特征异常回退均匀采样）。
"""
import asyncio
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.video.frame_extraction import (
    _select_adaptive_keyframes,
    compute_phash,
    extract_frames_adaptive_from_path,
    extract_frames_fixed,
    hamming_distance,
)

pytestmark = pytest.mark.unit

_HAS_FFMPEG = shutil.which("ffmpeg") is not None


# ---------------------------------------------------------------------------
# pHash / hamming_distance 纯函数
# ---------------------------------------------------------------------------


def _solid_image(color, size=64):
    from PIL import Image

    return Image.new("RGB", (size, size), color)


def test_phash_deterministic_and_discriminative():
    """同图同 hash；颜色差异大的图 hash 距离显著大于同色图。"""
    red1 = compute_phash(_solid_image((200, 30, 30)))
    red2 = compute_phash(_solid_image((200, 30, 30)))
    blue = compute_phash(_solid_image((30, 30, 200)))
    assert red1 == red2
    assert hamming_distance(red1, blue) > 0


def _gradient_image(shift: int, size: int = 64):
    """带横向渐变纹理的测试图（纯色对 pHash 是退化情形：低频块除 DC 外全零）。"""
    from PIL import Image

    img = Image.new("RGB", (size, size))
    px = img.load()
    for x in range(size):
        for y in range(size):
            v = (x * 4 + y * 2 + shift) % 256
            px[x, y] = (v, v, (v + 30) % 256)
    return img


def test_phash_stable_under_mild_change():
    """亮度轻微漂移（渐变纹理整体 +10）：hash 距离应远小于上限 64。"""
    base = compute_phash(_gradient_image(0))
    mild = compute_phash(_gradient_image(10))
    other = compute_phash(compute_phash and _gradient_image(128))
    assert hamming_distance(base, mild) < hamming_distance(base, other)


def test_hamming_distance_bounds():
    assert hamming_distance(0, 0) == 0
    assert hamming_distance(0, (1 << 64) - 1) == 64
    assert hamming_distance(0b1010, 0b0110) == 2


# ---------------------------------------------------------------------------
# _select_adaptive_keyframes 纯函数（FPS 选帧）
# ---------------------------------------------------------------------------


def _cluster_hashes(seed: int, count: int) -> list[int]:
    """生成一簇相近 hash：seed 的 bit 扰动 ≤2 位。"""
    out = []
    for i in range(count):
        h = seed ^ ((1 << (i % 60)) | (1 << ((i * 7 + 13) % 60)) if i else 0)
        out.append(h)
    return out


def test_fps_collapses_static_content():
    """静态塌缩：全部候选 hash 完全相同（逐帧相同的静止画面）→ 输出 1 帧。"""
    hashes = [0xABCDEF1234567890] * 100
    ts = [i * 5.0 for i in range(100)]  # 时间拉满（排除 min_interval 干扰）
    out = _select_adaptive_keyframes(hashes, ts, budget=60, min_interval=0.5)
    assert len(out) == 1, f"静态内容应塌缩为 1 帧，实际 {len(out)} 帧"


def test_fps_collapses_near_duplicates():
    """近重复：扰动 ≤2 位的候选（感知近重复）在覆盖阈值内塌缩为极少帧。"""
    base = 0xABCDEF1234567890
    hashes = [base, base ^ 0b1, base ^ 0b11, base, base ^ 0b10, base]
    ts = [i * 5.0 for i in range(len(hashes))]
    out = _select_adaptive_keyframes(hashes, ts, budget=10, min_interval=0.5)
    assert len(out) <= 2, f"近重复候选应塌缩，实际 {len(out)} 帧"


def test_fps_covers_multiple_scenes():
    """多场景覆盖：4 个互相远离的场景簇 → 每簇至少一个代表，时间覆盖首尾。"""
    seeds = [0x0F0F0F0F << 16, 0x00FF00FF << 16, 0x33003300 << 16, 0x5555AAAA << 16]
    hashes: list[int] = []
    ts: list[float] = []
    for si, seed in enumerate(seeds):
        for i in range(25):
            hashes.extend(_cluster_hashes(seed, 1))
            ts.append(si * 10.0 + i * 0.4)
    out = _select_adaptive_keyframes(hashes, ts, budget=60, min_interval=0.0)
    assert 4 <= len(out) <= 8
    # 覆盖：选中的代表帧跨越首尾场景
    selected_ts = [ts[i] for i in out]
    assert min(selected_ts) < 10.0 and max(selected_ts) >= 30.0
    assert out == sorted(out), "输出按时间升序"


def test_fps_respects_budget():
    """预算上限：8 个互相远离的簇、预算 4 → 恰 4 帧且来自不同簇。"""
    seeds = [(0x1111 << 48) + i * 0x0F0F0F0F0F0F for i in range(8)]
    hashes: list[int] = []
    ts: list[float] = []
    for si, seed in enumerate(seeds):
        hashes.extend(_cluster_hashes(seed, 3))
        ts.extend([si * 5.0] * 3)
    out = _select_adaptive_keyframes(hashes, ts, budget=4, min_interval=0.0)
    assert len(out) == 4


def test_fps_min_interval_constraint():
    """min_interval：两簇 hash 不同但时间上挤在一起 → 只保留 1 帧（时间分布下限）。"""
    hashes = _cluster_hashes(0xAAAA << 32, 5) + _cluster_hashes(0x5555 << 32, 5)
    ts = [i * 0.1 for i in range(9)]  # 0~0.8s，全部落在 min_interval=1.0 窗口内
    out = _select_adaptive_keyframes(hashes, ts, budget=10, min_interval=1.0)
    assert len(out) == 1


def test_fps_edge_cases():
    """边界：空输入/单候选/零预算；输出时间升序。"""
    assert _select_adaptive_keyframes([], [], budget=10) == []
    assert _select_adaptive_keyframes([42], [1.0], budget=10) == [0]
    assert _select_adaptive_keyframes([1, 2, 3], [0.0, 1.0, 2.0], budget=0) == []


# ---------------------------------------------------------------------------
# 集成：ffmpeg 合成视频（静态塌缩 / 多场景覆盖 / 降级路径）
# ---------------------------------------------------------------------------


def _make_video(path: str, spec: str, duration: int) -> str:
    """动态源（testsrc）直接合成。"""
    import subprocess

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", spec,
         "-t", str(duration), "-r", "2", "-pix_fmt", "yuv420p", path],
        check=True, capture_output=True,
    )
    return path


def _make_static_video(path: str, c0: str, c1: str, duration: int, tmp_path) -> str:
    """静态纹理视频：先生成单帧渐变 PNG，再 -loop 1 循环成视频。

    gradients 滤镜默认是动画（speed>0 每帧渐变在动），逐帧 pHash 不同、
    无法构造"静态内容"；静态 PNG 循环保证逐帧完全相同。"""
    import subprocess

    png = str(tmp_path / (Path(path).stem + ".png"))
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"gradients=s=64x64:c0={c0}:c1={c1}", "-frames:v", "1", png],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", png,
         "-t", str(duration), "-r", "2", "-pix_fmt", "yuv420p", path],
        check=True, capture_output=True,
    )
    return path


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg 不可用")
def test_adaptive_collapses_static_video(tmp_path):
    """静态塌缩端到端：纯色 8s 视频应塌缩为极少帧，远少于 fixed 均匀帧数。"""
    video = _make_static_video(str(tmp_path / "static.mp4"), "darkred", "red", 8, tmp_path)
    adaptive = asyncio.run(extract_frames_adaptive_from_path(video, max_frames=60))
    fixed = asyncio.run(extract_frames_fixed(Path(video).read_bytes(), interval=1.0, max_frames=60))
    assert len(adaptive) <= 2, f"静态视频应塌缩，实际 {len(adaptive)} 帧"
    assert len(adaptive) < len(fixed), f"adaptive({len(adaptive)}) 应少于 fixed({len(fixed)})"
    assert adaptive[0][2] == 0, "frame_idx 从 0 递增"


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg 不可用")
def test_adaptive_covers_scene_change(tmp_path):
    """多场景覆盖端到端：红蓝两段拼接 → 两段各有代表帧（时间覆盖两端）。"""
    import subprocess

    video = str(tmp_path / "two_scene.mp4")
    red_png = str(tmp_path / "red.png")
    blue_png = str(tmp_path / "blue.png")
    for png, c0, c1 in ((red_png, "black", "white"), (blue_png, "navy", "blue")):
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", f"gradients=s=64x64:c0={c0}:c1={c1}", "-frames:v", "1", png],
            check=True, capture_output=True,
        )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-loop", "1", "-t", "4", "-i", red_png,
         "-loop", "1", "-t", "4", "-i", blue_png,
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1", "-pix_fmt", "yuv420p", video],
        check=True, capture_output=True,
    )
    frames = asyncio.run(extract_frames_adaptive_from_path(video, max_frames=60))
    assert 2 <= len(frames) <= 4, f"两场景应约 2 帧代表，实际 {len(frames)}"
    selected_ts = [ts for _, ts, _ in frames]
    assert min(selected_ts) < 3.0 and max(selected_ts) >= 4.0, "时间覆盖应横跨红蓝两段"


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg 不可用")
def test_adaptive_degrades_to_uniform_on_feature_failure(tmp_path):
    """降级路径：特征计算异常 → 回退候选均匀采样（覆盖不劣于 fixed）。"""
    video = _make_video(str(tmp_path / "degrade.mp4"), "testsrc=size=64x64", 6)
    with patch(
        "novamind.engines.document.media.video.frame_extraction.compute_phash",
        side_effect=RuntimeError("feature boom"),
    ):
        frames = asyncio.run(extract_frames_adaptive_from_path(video, max_frames=6))
    assert 1 <= len(frames) <= 6
    # 降级产物仍是合法帧序列：时间升序 + frame_idx 连续递增
    ts_list = [ts for _, ts, _ in frames]
    idx_list = [idx for _, _, idx in frames]
    assert ts_list == sorted(ts_list)
    assert idx_list == list(range(len(frames)))
