"""DeepDoc 兼容层：映射上游 RAGFlow 的模块路径 / 类名 / 函数签名到本实现。"""
from __future__ import annotations

import re
from dataclasses import dataclass


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
    blobs: list[bytes]

    def first(self) -> bytes | None:
        return self.blobs[0] if self.blobs else None

    def __bool__(self) -> bool:
        return bool(self.blobs)
