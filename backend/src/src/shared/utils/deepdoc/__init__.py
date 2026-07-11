from __future__ import annotations

from shared.utils import deepdoc as _deepdoc


__path__ = list(_deepdoc.__path__)
__all__ = getattr(_deepdoc, "__all__", [])


def __getattr__(name):
    return getattr(_deepdoc, name)
