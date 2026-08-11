"""跨 feature 文件验证（FileInfo / FileValidator），被 qa / knowledge_space 复用。"""
from novamind.shared.document.validation.file_validator import (
    FileInfo,
    FileValidator,
    get_file_validator,
    validate_file,
)

__all__ = [
    "FileInfo",
    "FileValidator",
    "get_file_validator",
    "validate_file",
]
