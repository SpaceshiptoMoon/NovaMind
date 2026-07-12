from __future__ import annotations

import ast
import json
from typing import Any


class _DemjsonCompat:
    """Small demjson3-compatible decoder for resume payloads."""

    @staticmethod
    def decode(value: str) -> Any:
        try:
            return json.loads(value)
        except Exception:
            return ast.literal_eval(value)


demjson3 = _DemjsonCompat()


try:
    from xpinyin import Pinyin as Pinyin
except ImportError:
    class Pinyin:
        """Fallback preserving stable output when xpinyin is not installed."""

        def get_pinyins(self, text: str, splitter: str = "-") -> list[str]:
            values = [char.lower() if char.isascii() else char for char in text or ""]
            if splitter == "":
                return values
            if splitter == " ":
                return [" ".join(values)] if values else []
            return values
