"""兼容包：扩展 __path__ 使 novamind.core/features/shared/setting 解析到 backend/src/<area>/（novamind.shared 为命名空间包）。"""
from __future__ import annotations

from pathlib import Path

_CURRENT_DIR = Path(__file__).resolve().parent
_SOURCE_ROOT = _CURRENT_DIR.parent

_source_root_str = str(_SOURCE_ROOT)
if _source_root_str not in __path__:
    __path__.append(_source_root_str)
