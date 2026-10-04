"""ffmpeg 错误信息提取回归。

extract_ffmpeg_error 剥掉 ffmpeg stderr 固定 banner（版本/编译配置/库版本行，
约 1.5KB 与失败原因无关的噪音），保留真正错误行——此前 UI 错误提示被 banner
撑满，用户要滚动才能看到 ``moov atom not found`` 这类关键原因。
"""

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.video.video_normalizer import extract_ffmpeg_error

pytestmark = pytest.mark.unit

_BANNER_STDERR = """ffmpeg version 7.1-essentials_build-www.gyan.dev Copyright (c) 2000-2024 the FFmpeg developers
  built with gcc 14.2.0 (Rev1, Built by MSYS2 project)
  configuration: --enable-gpl --enable-version3 --enable-static
  libavutil      59. 39.100 / 59. 39.100
  libavcodec     61. 19.100 / 61. 19.100
  libavformat    61.  7.100 / 61.  7.100
  libswscale      8.  3.100 /  8.  3.100
[mov,mp4,m4a,3gp,3g2,mj2 @ 000001d4e29010c0] moov atom not found
[in#0 @ 000001d4e2900cc0] Error opening input: Invalid data found when processing input
Error opening input file C:\\Users\\xl\\AppData\\Local\\Temp\\tmp7j7o_r5h.mp4.
Error opening input files: Invalid data found when processing input"""


def test_banner_stripped_key_error_kept():
    """正向：banner 段（version/built with/configuration/lib*）全剥除，错误行保留。"""
    detail = extract_ffmpeg_error(_BANNER_STDERR)
    assert "moov atom not found" in detail
    assert "Error opening input" in detail
    # banner 关键词不残留
    assert "ffmpeg version" not in detail
    assert "configuration:" not in detail
    assert "libavcodec" not in detail


def test_empty_stderr_falls_back_to_stdout():
    """反向：stderr 为空时兜底 stdout；两者皆空返回占位。"""
    assert extract_ffmpeg_error("", "stdout has some info") == "stdout has some info"
    assert extract_ffmpeg_error("", "") == "ffmpeg returned a non-zero exit code"
    assert extract_ffmpeg_error(None, None) == "ffmpeg returned a non-zero exit code"


def test_no_banner_stderr_passthrough():
    """反向：无 banner 的 stderr 原样保留（不误剥真实内容）。"""
    detail = extract_ffmpeg_error("Output file is empty")
    assert detail == "Output file is empty"


def test_long_detail_truncated_from_head():
    """超长错误保留末尾（错误集中在尾部），并带省略标记。"""
    noisy = "banner line\n" + "x" * 2000 + "\nreal error: bad descriptor"
    detail = extract_ffmpeg_error(noisy, max_chars=100)
    assert detail.startswith("...")
    assert detail.endswith("real error: bad descriptor")
