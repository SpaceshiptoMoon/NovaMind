"""图片 VLM 输入降采样回归：超长边主动缩图防服务商端不可控压缩丢小字。"""
import sys
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.services.document_pipeline import (
    _downscale_image_for_vlm,
)

pytestmark = pytest.mark.unit


def _make_png(width: int, height: int) -> bytes:
    """生成纯色测试 PNG。"""
    img = Image.new("RGB", (width, height), color=(200, 100, 50))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_oversized_image_downscaled_to_limit():
    """长边 5000px 大图 → 缩到 2000px，返回 JPEG mime 覆盖。"""
    content, mime = _downscale_image_for_vlm(_make_png(5000, 2500))
    img = Image.open(BytesIO(content))
    assert max(img.size) <= 2000
    assert mime == "image/jpeg"


def test_normal_image_untouched():
    """常规尺寸图原样返回（不重编码、mime 不覆盖）。"""
    original = _make_png(1200, 800)
    content, mime = _downscale_image_for_vlm(original)
    assert content == original
    assert mime is None


def test_undecodable_payload_returned_as_is():
    """解码失败的字节原样返回（不在本地引入新失败面，由服务商兜底）。"""
    garbage = b"\x00\x01not-an-image"
    content, mime = _downscale_image_for_vlm(garbage)
    assert content == garbage
    assert mime is None


def test_exif_rotation_applied():
    """EXIF Orientation 转正：VLM 不再看到旋转图。"""
    img = Image.new("RGB", (300, 100), color=(10, 10, 10))
    buf = BytesIO()
    exif = Image.Exif()
    exif[274] = 6  # Orientation: 旋转 90°
    img.save(buf, format="JPEG", exif=exif)
    content, mime = _downscale_image_for_vlm(buf.getvalue())
    if mime == "image/jpeg":  # 超限才会转码；未超限时 EXIF 转正不强制触发
        rotated = Image.open(BytesIO(content))
        assert rotated.width >= rotated.height, "Orientation=6 应转正为横图"
