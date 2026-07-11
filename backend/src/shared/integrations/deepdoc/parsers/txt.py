from __future__ import annotations

# Adapted from RAGFlow deepdoc/parser/txt_parser.py

import re

from src.shared.utils.deepdoc.compat import num_tokens_from_string
from src.shared.integrations.deepdoc.parsers.upstream.utils import get_text


class RAGFlowTxtParser:
    def __call__(
        self,
        file_name: str,
        binary: bytes | None = None,
        chunk_token_num: int = 128,
        delimiter: str = "\n!?;。；！？",
    ):
        text = get_text(file_name, binary)
        return self.parser_txt(text, chunk_token_num, delimiter)

    @classmethod
    def parser_txt(cls, text: str, chunk_token_num: int = 128, delimiter: str = "\n!?;。；！？"):
        if not isinstance(text, str):
            raise TypeError("txt type should be str!")

        chunks = [""]
        token_counts = [0]
        delimiter = delimiter.encode("utf-8").decode("unicode_escape").encode("latin1").decode("utf-8")

        def add_chunk(section: str) -> None:
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
