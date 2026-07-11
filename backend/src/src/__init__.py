"""Compatibility package for source-root style imports in installed wheels."""

from __future__ import annotations

from pathlib import Path


_CURRENT_DIR = Path(__file__).resolve().parent
_SOURCE_ROOT = _CURRENT_DIR.parent

# Allow `src.features`, `src.shared`, etc. to resolve against the real source
# tree when this compatibility package is imported first.
_source_root_str = str(_SOURCE_ROOT)
if _source_root_str not in __path__:
    __path__.append(_source_root_str)
