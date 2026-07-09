import asyncio
from pathlib import Path
import sys

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytest.importorskip("av")

from src.shared.utils.media_utils import extract_video_frames


def test_extract_video_frames_mp4_sample():
    video_path = Path(__file__).resolve().parents[2] / "test_data" / "output" / "video" / "01_novamind_demo.mp4"
    frames = asyncio.run(extract_video_frames(video_path.read_bytes(), interval=5, max_frames=60))

    assert frames, "mp4 样例视频应至少提取出一帧"
    frame_bytes, timestamp, frame_index = frames[0]
    assert frame_bytes
    assert timestamp == 0
    assert frame_index == 0


def test_extract_video_frames_mov_sample():
    video_path = Path(__file__).resolve().parents[2] / "test_data" / "output" / "video" / "02_novamind_demo.mov"
    frames = asyncio.run(extract_video_frames(video_path.read_bytes(), interval=5, max_frames=60))

    assert frames, "mov 样例视频应至少提取出一帧"
    frame_bytes, timestamp, frame_index = frames[0]
    assert frame_bytes
    assert timestamp == 0
    assert frame_index == 0
