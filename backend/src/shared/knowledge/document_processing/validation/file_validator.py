"""
文件类型验证器

使用 python-magic 验证文件的真实 MIME 类型，防止文件伪装攻击。
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from novamind.core.middleware.structured_logging import get_logger


logger = get_logger(__name__)


@dataclass
class FileInfo:
    """文件信息"""

    filename: str
    size: int
    extension: str
    detected_mime: Optional[str] = None
    detected_extension: Optional[str] = None
    is_valid: bool = False
    validation_message: str = ""


class FileValidator:
    """
    文件验证器

    通过以下方式验证文件类型:
    1. 文件头（魔数）检测
    2. MIME 类型验证
    3. 扩展名与实际类型匹配
    """

    MAGIC_SIGNATURES = {
        b"%PDF": "application/pdf",
        b"PK\x03\x04": "application/zip",
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1": "application/msword",
        b"\x89PNG\r\n\x1a\n": "image/png",
        b"\xff\xd8\xff": "image/jpeg",
        b"GIF87a": "image/gif",
        b"GIF89a": "image/gif",
        b"Rar!\x1a\x07": "application/x-rar-compressed",
        b"7z\xbc\xaf\x27\x1c": "application/x-7z-compressed",
        b"MZ": "application/x-dosexec",
        b"#!/bin/sh": "text/x-shellscript",
        b"#!/bin/bash": "text/x-shellscript",
        b"#!/usr/bin/env": "text/x-shellscript",
        b"ID3": "audio/mpeg",
        b"\xff\xfb": "audio/mpeg",
        b"\xff\xf3": "audio/mpeg",
        b"\xff\xe3": "audio/mpeg",
        b"fLaC": "audio/flac",
        b"OggS": "audio/ogg",
        b"\x1aE\xdf\xa3": "video/webm",
    }

    EXTENSION_TO_MIME = {
        "pdf": ["application/pdf"],
        "doc": ["application/msword"],
        "docx": [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/zip",
        ],
        "xls": ["application/vnd.ms-excel"],
        "xlsx": [
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/zip",
        ],
        "ppt": ["application/vnd.ms-powerpoint"],
        "pptx": [
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/zip",
        ],
        "txt": ["text/plain"],
        "md": ["text/markdown", "text/plain"],
        "html": ["text/html"],
        "htm": ["text/html"],
        "csv": ["text/csv", "text/plain"],
        "json": ["application/json", "text/plain"],
        "xml": ["application/xml", "text/xml", "text/plain"],
        "png": ["image/png"],
        "jpg": ["image/jpeg"],
        "jpeg": ["image/jpeg"],
        "gif": ["image/gif"],
        "mp4": ["video/mp4"],
        "mov": ["video/quicktime"],
        "avi": ["video/x-msvideo"],
        "mkv": ["video/x-matroska"],
        "webm": ["video/webm"],
        "mp3": ["audio/mpeg", "audio/mp3"],
        "wav": ["audio/wav", "audio/x-wav"],
        "flac": ["audio/flac"],
        "aac": ["audio/aac"],
        "ogg": ["audio/ogg"],
        "m4a": ["audio/mp4", "audio/x-m4a"],
    }

    OFFICE_CONTENT_TYPES = {
        "word": "[Content_Types].xml contains wordprocessingml",
        "excel": "[Content_Types].xml contains spreadsheetml",
        "powerpoint": "[Content_Types].xml contains presentationml",
    }

    DANGEROUS_EXTENSIONS = {
        "exe",
        "bat",
        "cmd",
        "com",
        "pif",
        "scr",
        "vbs",
        "js",
        "jar",
        "msi",
        "ps1",
        "sh",
        "bash",
        "zsh",
        "fish",
        "py",
        "pl",
        "rb",
        "php",
        "asp",
        "aspx",
        "jsp",
        "cgi",
        "dll",
        "so",
        "dylib",
    }

    def __init__(self, max_file_size: int = 100 * 1024 * 1024):
        self.max_file_size = max_file_size
        self._magic = None

    def _get_magic(self):
        if self._magic is None:
            try:
                import magic

                self._magic = magic.Magic(mime=True)
            except ImportError:
                logger.warning(
                    "python-magic is not installed; falling back to header-only detection. "
                    "Install python-magic-bin on Windows or python-magic on Linux/Mac."
                )
        return self._magic

    def detect_mime_by_magic(self, content: bytes) -> Optional[str]:
        magic = self._get_magic()
        if magic:
            try:
                return magic.from_buffer(content[:2048])
            except Exception as exc:
                logger.warning("MIME detection failed", error=str(exc))
        return None

    def detect_mime_by_header(self, content: bytes) -> Optional[str]:
        for signature, mime_type in self.MAGIC_SIGNATURES.items():
            if content.startswith(signature):
                if mime_type == "audio/x-wav" and content.startswith(b"RIFF") and len(content) >= 12:
                    riff_type = content[8:12]
                    if riff_type == b"WAVE":
                        return "audio/x-wav"
                    if riff_type == b"AVI ":
                        return "video/x-msvideo"
                    return None
                return mime_type
        return None

    def get_extension_from_filename(self, filename: str) -> str:
        if "." not in filename:
            return ""
        return filename.rsplit(".", 1)[-1].lower()

    def is_dangerous_extension(self, extension: str) -> bool:
        return extension.lower() in self.DANGEROUS_EXTENSIONS

    def is_office_document(self, content: bytes) -> Tuple[bool, Optional[str]]:
        import io
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                namelist = zf.namelist()
                if "[Content_Types].xml" in namelist:
                    try:
                        content_types = zf.read("[Content_Types].xml").decode("utf-8", errors="ignore")
                        if "wordprocessingml" in content_types:
                            return True, "docx"
                        if "spreadsheetml" in content_types:
                            return True, "xlsx"
                        if "presentationml" in content_types:
                            return True, "pptx"
                    except Exception:
                        pass
        except Exception:
            pass

        return False, None

    def validate(
        self,
        content: bytes,
        filename: str,
        allowed_extensions: Optional[list] = None,
    ) -> FileInfo:
        extension = self.get_extension_from_filename(filename)
        file_size = len(content)
        info = FileInfo(filename=filename, size=file_size, extension=extension)

        if file_size > self.max_file_size:
            info.validation_message = f"文件大小 ({file_size} 字节) 超过限制 ({self.max_file_size} 字节)"
            return info

        if file_size == 0:
            info.validation_message = "文件为空"
            return info

        if self.is_dangerous_extension(extension):
            info.validation_message = f"禁止上传的文件类型: {extension}"
            return info

        if allowed_extensions:
            allowed_lower = [e.lower().lstrip(".") for e in allowed_extensions]
            if extension not in allowed_lower:
                info.validation_message = (
                    f"不支持的文件类型: {extension}，支持的类型: {', '.join(allowed_lower)}"
                )
                return info

        detected_mime = self.detect_mime_by_magic(content)
        if not detected_mime:
            detected_mime = self.detect_mime_by_header(content)
        info.detected_mime = detected_mime

        if detected_mime == "application/zip" and extension in ("docx", "xlsx", "pptx"):
            is_office, doc_type = self.is_office_document(content)
            if is_office:
                info.detected_extension = doc_type
                info.is_valid = True
                info.validation_message = "文件验证通过"
                return info

        expected_mimes = self.EXTENSION_TO_MIME.get(extension, [])
        if expected_mimes and detected_mime:
            if detected_mime in expected_mimes:
                info.is_valid = True
                info.validation_message = "文件验证通过"
            else:
                info.validation_message = (
                    f"文件扩展名 ({extension}) 与实际内容 ({detected_mime}) 不匹配，可能存在文件伪装攻击"
                )
                logger.warning(
                    "文件类型不匹配",
                    filename=filename,
                    extension=extension,
                    detected_mime=detected_mime,
                    expected_mimes=expected_mimes,
                )
        elif not expected_mimes:
            if detected_mime:
                info.is_valid = True
                info.validation_message = f"文件验证通过 (MIME: {detected_mime})"
            else:
                info.validation_message = f"无法识别的文件类型: {extension}"
        else:
            info.is_valid = True
            info.validation_message = "文件验证通过（仅扩展名）"

        return info


_validator: Optional[FileValidator] = None


def get_file_validator(max_file_size: int = 100 * 1024 * 1024) -> FileValidator:
    """获取全局文件验证器实例"""

    global _validator
    if _validator is None:
        _validator = FileValidator(max_file_size=max_file_size)
    return _validator


def validate_file(
    content: bytes,
    filename: str,
    allowed_extensions: Optional[list] = None,
) -> FileInfo:
    """验证文件（便捷函数）"""

    validator = get_file_validator()
    return validator.validate(content, filename, allowed_extensions)
