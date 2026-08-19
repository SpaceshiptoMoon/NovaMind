"""文件名合法性校验回归测试。

覆盖 DocumentUploadService._get_file_type 的文件名字符白名单：
- 允许中文 + 全角标点（：（）等）与 CJK 标点，避免误拒常见中文命名
- 仍拦截路径遍历（../、/、\）
"""
import pytest

from novamind.features.knowledge_space.services.document_upload_service import (
    DocumentUploadService,
)
from novamind.features.knowledge_space.exceptions import (
    InvalidParameterError,
    DocumentInvalidTypeError,
)


def _get_file_type(filename: str) -> str:
    service = object.__new__(DocumentUploadService)
    return DocumentUploadService._get_file_type(service, filename)


@pytest.mark.parametrize(
    "filename",
    [
        "00-总纲.md",
        "01-第一代：机械式OCR（1914-1950s）.md",
        "02-第二代：模板匹配OCR（1960s-1970s）.md",
        "附录A-主流OCR引擎对比.md",
        "　全角空格开头.md",
    ],
)
def test_accepts_legal_filenames(filename):
    assert _get_file_type(filename) in DocumentUploadService.SUPPORTED_FILE_TYPES


@pytest.mark.parametrize(
    "filename",
    [
        "../etc/passwd.md",
        "a/b.md",
        "a\\b.md",
        "..hidden.md",
    ],
)
def test_rejects_path_traversal(filename):
    with pytest.raises(InvalidParameterError):
        _get_file_type(filename)


def test_rejects_unsupported_extension():
    with pytest.raises(DocumentInvalidTypeError):
        _get_file_type("恶意脚本.exe")


def test_rejects_empty_filename():
    with pytest.raises(InvalidParameterError):
        _get_file_type("   ")
