"""DeepDoc 兼容层：映射上游 RAGFlow 的模块路径 / 类名 / 函数签名到本实现。"""
from __future__ import annotations

import re
from dataclasses import dataclass


class SimpleTokenizer:
    """Compatibility shim for the subset of RAGFlow tokenizer APIs we need."""

    _token_pattern = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")

    def tokenize(self, text: str) -> str:
        """按中英文词边界粗分词，空格连接（上游 ragflow NltkTokenizer 的轻量替身）。

        Args:
            text: 待分词文本。

        Returns:
            空格连接的词串。
        """
        return " ".join(self._token_pattern.findall(text or ""))

    def tag(self, token: str) -> str:
        """词性粗标（n 名词/nr 人名/en 英文/m 数词/x 其他），供上游命名体识别路径兼容。

        Args:
            token: 单个词。

        Returns:
            词性标记字符串。
        """
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
        """全角字符转半角（含全角空格 U+3000），对齐上游 rag_tokenizer.strQ2B。

        Args:
            text: 待转换文本。

        Returns:
            半角文本。
        """
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
        """繁转简的占位实现（无 OpenCC 依赖时原样返回）。

        Args:
            text: 待转换文本。

        Returns:
            原样返回输入。
        """
        # Lightweight fallback when OpenCC-style conversion is unavailable.
        return text or ""

    @staticmethod
    def is_chinese(text: str) -> bool:
        """字符串是否含任一 CJK 汉字。

        Args:
            text: 待检测文本。

        Returns:
            含 CJK 汉字为 True。
        """
        return any("\u4e00" <= ch <= "\u9fff" for ch in text or "")


rag_tokenizer = SimpleTokenizer()


def num_tokens_from_string(text: str) -> int:
    """估算文本 token 数（分词后按空格计数），上游同名函数的兼容实现。

    Args:
        text: 待估算文本。

    Returns:
        token 数估计值。
    """
    tokenized = rag_tokenizer.tokenize(text or "")
    return len(tokenized.split()) if tokenized else 0


def find_codec(binary: bytes) -> str:
    """按 utf-8→gb18030→latin-1 顺序探测字节流编码名，全部失败回退 utf-8。

    Args:
        binary: 待探测字节流。

    Returns:
        探测到的编码名。
    """
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "latin-1"):
        try:
            binary.decode(encoding)
            return encoding
        except Exception:
            continue
    return "utf-8"


@dataclass(slots=True)
class LazyImage:
    """页图像字节序列的惰性容器（vendored 层按需取用，不做提前解码）。"""

    blobs: list[bytes]

    def first(self) -> bytes | None:
        """取首页图像字节；无页时 None。"""
        return self.blobs[0] if self.blobs else None

    def __bool__(self) -> bool:
        """是否持有任何页图像。"""
        return bool(self.blobs)
