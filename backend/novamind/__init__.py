"""Local development bridge for the novamind import root."""

from __future__ import annotations

from pathlib import Path


_CURRENT_DIR = Path(__file__).resolve().parent
_SOURCE_ROOT = _CURRENT_DIR.parent / "src"

_source_root_str = str(_SOURCE_ROOT)
if _source_root_str not in __path__:
    __path__.append(_source_root_str)
