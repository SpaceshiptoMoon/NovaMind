"""Compatibility package for source-root style imports in installed wheels."""

from __future__ import annotations

from pathlib import Path


_CURRENT_DIR = Path(__file__).resolve().parent
_REAL_SHARED_DIR = _CURRENT_DIR.parents[1] / "shared"

_real_shared_str = str(_REAL_SHARED_DIR)
if _real_shared_str not in __path__:
    __path__.append(_real_shared_str)
