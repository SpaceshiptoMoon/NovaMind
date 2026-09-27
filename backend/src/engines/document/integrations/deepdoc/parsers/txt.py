"""DeepDoc 纯文本文件解析器。"""
from __future__ import annotations

# Adapted from RAGFlow deepdoc/parser/txt_parser.py
import re

from novamind.engines.document.integrations.deepdoc.compat import num_tokens_from_string
from novamind.engines.document.integrations.deepdoc.parsers.upstream.utils import get_text


class RAGFlowTxtParser:
    """纯文本解析器：分隔符切段、token 预算聚块。"""
    def __call__(
        self,
        file_name: str,
        binary: bytes | None = None,
        chunk_token_num: int = 128,
        delimiter: str = "\n!?;。；！？",
    ):
        """解码文本并按分块目标长度切分为（分块，页码空串）列表。

        Args:
            file_name: 文件路径（binary 为 None 时使用）。
            binary: 文本字节流；与 file_name 二选一。
            chunk_token_num: 单块 token 上限。
            delimiter: 分段分隔符，支持反引号包裹的多字符分隔符。
        """
        text = get_text(file_name, binary)
        return self.parser_txt(text, chunk_token_num, delimiter)

    @classmethod
    def parser_txt(cls, text: str, chunk_token_num: int = 128, delimiter: str = "\n!?;。；！？"):
        """按分隔符切分文本并聚合到 token 上限内的块。

        超上限的块独立成块；未超限的追加进当前块（换行拼接）。
        """
        if not isinstance(text, str):
            raise TypeError("txt type should be str!")

        chunks = [""]
        token_counts = [0]
        delimiter = delimiter.encode("utf-8").decode("unicode_escape").encode("latin1").decode("utf-8")

        def add_chunk(section: str) -> None:
            """追加一段文本：超限新起一块，否则并入当前块并累计 token 数。"""
            token_num = num_tokens_from_string(section)
            if token_counts[-1] > chunk_token_num:
                chunks.append(section)
                token_counts.append(token_num)
            else:
                if chunks[-1]:
                    chunks[-1] += "\n" + section
                else:
                    chunks[-1] += section
                token_counts[-1] += token_num

        delimiters = []
        start = 0
        for match in re.finditer(r"`([^`]+)`", delimiter, re.I):
            left, right = match.span()
            delimiters.append(match.group(1))
            delimiters.extend(list(delimiter[start:left]))
            start = right
        if start < len(delimiter):
            delimiters.extend(list(delimiter[start:]))
        delimiters = [re.escape(item) for item in delimiters if item]
        delimiters = "|".join(item for item in delimiters if item)

        if not delimiters:
            return [[text, ""]] if text else []

        sections = re.split(r"(%s)" % delimiters, text)
        for section in sections:
            if re.match(f"^{delimiters}$", section):
                continue
            add_chunk(section)

        return [[chunk, ""] for chunk in chunks if chunk]
