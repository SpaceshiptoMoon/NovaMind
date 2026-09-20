import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytest.importorskip("av")

from novamind.engines.document.media.video import extract_video_frames

pytestmark = pytest.mark.unit


def _assert_video_frames(path: Path) -> None:
    # test_data/ 是 repo 外本地样例约定目录（CLAUDE.md），不进 git；缺失即跳过
    if not path.exists():
        pytest.skip(f"本地样例缺失: {path.name}（test_data/ 约定目录，见 CLAUDE.md）")
    frames = asyncio.run(extract_video_frames(path.read_bytes(), interval=5, max_frames=60))
    assert frames, f"{path.name} 应至少提取出一帧"
    frame_bytes, timestamp, frame_index = frames[0]
    assert frame_bytes
    assert timestamp == 0
    assert frame_index == 0


def test_extract_video_frames_mp4_sample():
    video_path = Path(__file__).resolve().parents[5] / "test_data" / "output" / "video" / "01_novamind_demo.mp4"
    _assert_video_frames(video_path)


def test_extract_video_frames_mov_sample():
    video_path = Path(__file__).resolve().parents[5] / "test_data" / "output" / "video" / "02_novamind_demo.mov"
    _assert_video_frames(video_path)


def test_extract_video_frames_mkv_sample():
    video_path = Path(__file__).resolve().parents[5] / "test_data" / "output" / "video" / "04_novamind_demo.mkv"
    _assert_video_frames(video_path)


def test_extract_video_frames_webm_sample():
    video_path = Path(__file__).resolve().parents[5] / "test_data" / "output" / "video" / "05_novamind_demo.webm"
    _assert_video_frames(video_path)
