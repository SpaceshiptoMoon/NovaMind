"""
文件类型验证器

使用 python-magic 验证文件的真实 MIME 类型，防止文件伪装攻击
"""

import hashlib
from typing import Optional, Tuple, Dict
from dataclasses import dataclass

from src.core.middleware.structured_logging import get_logger


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

    通过以下方式验证文件类型：
    1. 文件头（魔数）检测
    2. MIME 类型验证
    3. 扩展名与实际类型匹配
    """

    # 文件魔数签名（文件头）
    MAGIC_SIGNATURES = {
        # PDF
        b'%PDF': 'application/pdf',

        # DOCX (ZIP-based Office format)
        b'PK\x03\x04': 'application/zip',  # 需要进一步检查

        # DOC (old Word format)
        b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1': 'application/msword',

        # PNG
        b'\x89PNG\r\n\x1a\n': 'image/png',

        # JPEG
        b'\xff\xd8\xff': 'image/jpeg',

        # GIF
        b'GIF87a': 'image/gif',
        b'GIF89a': 'image/gif',

        # RAR
        b'Rar!\x1a\x07': 'application/x-rar-compressed',

        # 7z
        b'7z\xbc\xaf\x27\x1c': 'application/x-7z-compressed',

        # Executable (Windows)
        b'MZ': 'application/x-dosexec',

        # Shell script
        b'#!/bin/sh': 'text/x-shellscript',
        b'#!/bin/bash': 'text/x-shellscript',
        b'#!/usr/bin/env': 'text/x-shellscript',
    }

    # 扩展名到 MIME 类型的映射
    EXTENSION_TO_MIME = {
        'pdf': ['application/pdf'],
        'doc': ['application/msword'],
        'docx': [
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/zip',  # DOCX 本质是 ZIP
        ],
        'xls': ['application/vnd.ms-excel'],
        'xlsx': [
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/zip',
        ],
        'ppt': ['application/vnd.ms-powerpoint'],
        'pptx': [
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'application/zip',
        ],
        'txt': ['text/plain'],
        'md': ['text/markdown', 'text/plain'],
        'html': ['text/html'],
        'htm': ['text/html'],
        'csv': ['text/csv', 'text/plain'],
        'json': ['application/json', 'text/plain'],
        'xml': ['application/xml', 'text/xml', 'text/plain'],
        'png': ['image/png'],
        'jpg': ['image/jpeg'],
        'jpeg': ['image/jpeg'],
        'gif': ['image/gif'],
    }

    # Office 文件内容类型（在 ZIP 内部）
    OFFICE_CONTENT_TYPES = {
        'word': '[Content_Types].xml 中包含 wordprocessingml',
        'excel': '[Content_Types].xml 中包含 spreadsheetml',
        'powerpoint': '[Content_Types].xml 中包含 presentationml',
    }

    # 危险文件类型
    DANGEROUS_EXTENSIONS = {
        'exe', 'bat', 'cmd', 'com', 'pif', 'scr', 'vbs', 'js', 'jar',
        'msi', 'ps1', 'sh', 'bash', 'zsh', 'fish', 'py', 'pl', 'rb',
        'php', 'asp', 'aspx', 'jsp', 'cgi', 'dll', 'so', 'dylib',
    }

    def __init__(self, max_file_size: int = 100 * 1024 * 1024):
        """
        初始化文件验证器

        Args:
            max_file_size: 最大文件大小（字节），默认 100MB
        """
        self.max_file_size = max_file_size
        self._magic = None

    def _get_magic(self):
        """延迟加载 python-magic"""
        if self._magic is None:
            try:
                import magic
                self._magic = magic.Magic(mime=True)
            except ImportError:
                logger.warning(
                    "python-magic 未安装，将仅使用文件头检测。"
                    "建议安装: pip install python-magic-bin (Windows) 或 pip install python-magic (Linux/Mac)"
                )
        return self._magic

    def detect_mime_by_magic(self, content: bytes) -> Optional[str]:
        """
        使用 python-magic 检测 MIME 类型

        Args:
            content: 文件内容（前 2048 字节足够）

        Returns:
            MIME 类型字符串或 None
        """
        magic = self._get_magic()
        if magic:
            try:
                return magic.from_buffer(content[:2048])
            except Exception as e:
                logger.warning("MIME 检测失败", error=str(e))
        return None

    def detect_mime_by_header(self, content: bytes) -> Optional[str]:
        """
        通过文件头（魔数）检测 MIME 类型

        Args:
            content: 文件内容

        Returns:
            MIME 类型字符串或 None
        """
        for signature, mime_type in self.MAGIC_SIGNATURES.items():
            if content.startswith(signature):
                return mime_type
        return None

    def get_extension_from_filename(self, filename: str) -> str:
        """
        从文件名获取扩展名

        Args:
            filename: 文件名

        Returns:
            小写扩展名（不含点）
        """
        if '.' not in filename:
            return ''
        return filename.rsplit('.', 1)[-1].lower()

    def is_dangerous_extension(self, extension: str) -> bool:
        """
        检查是否是危险的文件扩展名

        Args:
            extension: 文件扩展名

        Returns:
            是否危险
        """
        return extension.lower() in self.DANGEROUS_EXTENSIONS

    def is_office_document(self, content: bytes) -> Tuple[bool, Optional[str]]:
        """
        检查 ZIP 文件是否是 Office 文档

        Args:
            content: 文件内容

        Returns:
            (是否是 Office 文档, 文档类型)
        """
        import zipfile
        import io

        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                namelist = zf.namelist()

                # 检查是否包含 Office 文件的标记
                if '[Content_Types].xml' in namelist:
                    try:
                        content_types = zf.read('[Content_Types].xml').decode('utf-8', errors='ignore')
                        if 'wordprocessingml' in content_types:
                            return True, 'docx'
                        elif 'spreadsheetml' in content_types:
                            return True, 'xlsx'
                        elif 'presentationml' in content_types:
                            return True, 'pptx'
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
        """
        验证文件

        Args:
            content: 文件内容
            filename: 文件名
            allowed_extensions: 允许的扩展名列表，None 表示使用默认列表

        Returns:
            FileInfo: 文件验证结果
        """
        extension = self.get_extension_from_filename(filename)
        file_size = len(content)

        # 创建文件信息对象
        info = FileInfo(
            filename=filename,
            size=file_size,
            extension=extension,
        )

        # 1. 检查文件大小
        if file_size > self.max_file_size:
            info.validation_message = f"文件大小 ({file_size} 字节) 超过限制 ({self.max_file_size} 字节)"
            return info

        if file_size == 0:
            info.validation_message = "文件为空"
            return info

        # 2. 检查危险扩展名
        if self.is_dangerous_extension(extension):
            info.validation_message = f"禁止上传的文件类型: {extension}"
            return info

        # 3. 检查扩展名是否在允许列表中
        if allowed_extensions:
            allowed_lower = [e.lower().lstrip('.') for e in allowed_extensions]
            if extension not in allowed_lower:
                info.validation_message = f"不支持的文件类型: {extension}，支持的类型: {', '.join(allowed_lower)}"
                return info

        # 4. 检测实际 MIME 类型
        detected_mime = self.detect_mime_by_magic(content)
        if not detected_mime:
            detected_mime = self.detect_mime_by_header(content)
        info.detected_mime = detected_mime

        # 5. 处理 ZIP 格式的 Office 文件
        if detected_mime == 'application/zip' and extension in ('docx', 'xlsx', 'pptx'):
            is_office, doc_type = self.is_office_document(content)
            if is_office:
                info.detected_extension = doc_type
                info.is_valid = True
                info.validation_message = "文件验证通过"
                return info

        # 6. 验证扩展名与 MIME 类型是否匹配
        expected_mimes = self.EXTENSION_TO_MIME.get(extension, [])
        if expected_mimes and detected_mime:
            if detected_mime in expected_mimes:
                info.is_valid = True
                info.validation_message = "文件验证通过"
            else:
                # MIME 类型不匹配
                info.validation_message = (
                    f"文件扩展名 ({extension}) 与实际内容 ({detected_mime}) 不匹配，"
                    "可能存在文件伪装攻击"
                )
                logger.warning(
                    "文件类型不匹配",
                    filename=filename,
                    extension=extension,
                    detected_mime=detected_mime,
                    expected_mimes=expected_mimes,
                )
        elif not expected_mimes:
            # 未知扩展名，但通过了魔数检测
            if detected_mime:
                info.is_valid = True
                info.validation_message = f"文件验证通过（MIME: {detected_mime}）"
            else:
                info.validation_message = f"无法识别的文件类型: {extension}"
        else:
            # 无法检测 MIME 类型，仅信任扩展名（较宽松）
            info.is_valid = True
            info.validation_message = "文件验证通过（仅扩展名）"

        return info

    def calculate_hash(self, content: bytes) -> str:
        """
        计算文件 SHA256 哈希值

        Args:
            content: 文件内容

        Returns:
            十六进制哈希字符串
        """
        return hashlib.sha256(content).hexdigest()


# 全局验证器实例
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
    """
    验证文件（便捷函数）

    Args:
        content: 文件内容
        filename: 文件名
        allowed_extensions: 允许的扩展名列表

    Returns:
        FileInfo: 文件验证结果
    """
    validator = get_file_validator()
    return validator.validate(content, filename, allowed_extensions)
