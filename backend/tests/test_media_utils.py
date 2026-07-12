import asyncio
from pathlib import Path
import sys

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytest.importorskip("av")

from novamind.shared.knowledge.media_processing.video import extract_video_frames


def _assert_video_frames(path: Path) -> None:
    frames = asyncio.run(extract_video_frames(path.read_bytes(), interval=5, max_frames=60))
    assert frames, f"{path.name} 应至少提取出一帧"
    frame_bytes, timestamp, frame_index = frames[0]
    assert frame_bytes
    assert timestamp == 0
    assert frame_index == 0


def test_extract_video_frames_mp4_sample():
    video_path = Path(__file__).resolve().parents[2] / "test_data" / "output" / "video" / "01_novamind_demo.mp4"
    _assert_video_frames(video_path)


def test_extract_video_frames_mov_sample():
    video_path = Path(__file__).resolve().parents[2] / "test_data" / "output" / "video" / "02_novamind_demo.mov"
    _assert_video_frames(video_path)


def test_extract_video_frames_mkv_sample():
    video_path = Path(__file__).resolve().parents[2] / "test_data" / "output" / "video" / "04_novamind_demo.mkv"
    _assert_video_frames(video_path)


def test_extract_video_frames_webm_sample():
    video_path = Path(__file__).resolve().parents[2] / "test_data" / "output" / "video" / "05_novamind_demo.webm"
    _assert_video_frames(video_path)
