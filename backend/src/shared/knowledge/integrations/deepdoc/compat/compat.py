from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional


class SimpleTokenizer:
    """Compatibility shim for the subset of RAGFlow tokenizer APIs we need."""

    _token_pattern = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")

    def tokenize(self, text: str) -> str:
        return " ".join(self._token_pattern.findall(text or ""))

    def tag(self, token: str) -> str:
        token = token or ""
        if self.is_chinese(token):
            return "n"
        if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*", token):
            return "nr"
        if re.fullmatch(r"[A-Za-z]+", token):
            return "en"
        if re.fullmatch(r"[0-9]+", token):
            return "m"
        return "x"

    def strQ2B(self, text: str) -> str:
        chars: list[str] = []
        for ch in text or "":
            code = ord(ch)
            if code == 0x3000:
                chars.append(" ")
                continue
            if 0xFF01 <= code <= 0xFF5E:
                chars.append(chr(code - 0xFEE0))
                continue
            chars.append(ch)
        return "".join(chars)

    def tradi2simp(self, text: str) -> str:
        # Lightweight fallback when OpenCC-style conversion is unavailable.
        return text or ""

    @staticmethod
    def is_chinese(text: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in text or "")


rag_tokenizer = SimpleTokenizer()


def num_tokens_from_string(text: str) -> int:
    tokenized = rag_tokenizer.tokenize(text or "")
    return len(tokenized.split()) if tokenized else 0


def find_codec(binary: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "latin-1"):
        try:
            binary.decode(encoding)
            return encoding
        except Exception:
            continue
    return "utf-8"


@dataclass(slots=True)
class LazyImage:
    blobs: List[bytes]

    def first(self) -> Optional[bytes]:
        return self.blobs[0] if self.blobs else None

    def __bool__(self) -> bool:
        return bool(self.blobs)



class SimpleSurnameHelper:
    """Small surname checker used by the vendored resume helpers."""

    _common_surnames = {
        "\u8d75", "\u94b1", "\u5b59", "\u674e", "\u5468", "\u5434", "\u90d1", "\u738b",
        "\u51af", "\u9648", "\u848b", "\u6c88", "\u97e9", "\u6768", "\u6731", "\u79e6",
        "\u8bb8", "\u4f55", "\u5415", "\u65bd", "\u5f20", "\u5b54", "\u66f9", "\u534e",
        "\u91d1", "\u9b4f", "\u9676", "\u59dc", "\u8c22", "\u90b9", "\u82cf", "\u6f58",
        "\u8303", "\u5f6d", "\u9c81", "\u9a6c", "\u65b9", "\u4efb", "\u8881", "\u5510",
        "\u859b", "\u96f7", "\u8d3a", "\u7f57", "\u90dd", "\u5b89", "\u5e38", "\u4e8e",
        "\u5085", "\u987e", "\u5b5f", "\u9ec4", "\u8427", "\u5c39", "\u59da", "\u6c6a",
        "\u5b8b", "\u6881", "\u675c", "\u90ed", "\u6797", "\u949f", "\u5f90", "\u9ad8",
        "\u590f", "\u8521", "\u7530", "\u80e1", "\u5362", "\u6234", "\u9093", "\u5d14",
        "\u9646", "\u6bb5", "\u4faf", "\u5218", "\u53f6", "\u767d", "\u9ece", "\u8c2d",
        "\u66fe", "\u5ed6", "\u95eb", "\u6b27\u9633", "\u53f8\u9a6c", "\u4e0a\u5b98",
        "\u590f\u4faf", "\u8bf8\u845b", "\u4e1c\u65b9", "\u7687\u752b", "\u5c09\u8fdf",
        "\u516c\u7f8a", "\u6de1\u53f0", "\u6fee\u9633",
    }

    def isit(self, text: str) -> bool:
        return (text or "").strip() in self._common_surnames


surname = SimpleSurnameHelper()
