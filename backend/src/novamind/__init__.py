"""Compatibility package for the new novamind import root.

``backend/src/novamind/__init__.py`` 把 ``__path__`` 扩展到 ``backend/src/``，
使 ``novamind.core.* / novamind.features.* / novamind.shared.*`` 解析到对应的
``backend/src/<area>/`` 目录。

``novamind.shared`` 是命名空间包（无 ``__init__.py``）。
"""
from __future__ import annotations

from pathlib import Path

_CURRENT_DIR = Path(__file__).resolve().parent
_SOURCE_ROOT = _CURRENT_DIR.parent

_source_root_str = str(_SOURCE_ROOT)
if _source_root_str not in __path__:
    __path__.append(_source_root_str)
