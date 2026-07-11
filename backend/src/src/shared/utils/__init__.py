"""Compatibility package for source-root style imports in installed wheels."""
from __future__ import annotations

from pathlib import Path


_CURRENT_DIR = Path(__file__).resolve().parent
_REAL_UTILS_DIR = _CURRENT_DIR.parents[2] / "shared" / "utils"

_real_utils_str = str(_REAL_UTILS_DIR)
if _real_utils_str not in __path__:
    __path__.append(_real_utils_str)
