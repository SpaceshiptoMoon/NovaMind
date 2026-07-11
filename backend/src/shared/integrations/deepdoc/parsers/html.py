from __future__ import annotations

# Adapted from RAGFlow deepdoc/parser/html_parser.py

import html
import logging
import re
import uuid

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from src.shared.integrations.deepdoc.compat import find_codec, rag_tokenizer


BLOCK_TAGS = [
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "div",
    "article",
    "section",
    "aside",
    "ul",
    "ol",
    "li",
    "table",
    "pre",
    "code",
    "blockquote",
    "figure",
    "figcaption",
]
TITLE_TAGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}


class RAGFlowHtmlParser:
    def __call__(self, file_name: str, binary: bytes | None = None, chunk_token_num: int = 512):
        if binary:
            encoding = find_codec(binary)
            text = binary.decode(encoding, errors="ignore")
        else:
            with open(file_name, "rb") as handle:
                raw = handle.read()
            encoding = find_codec(raw)
            text = raw.decode(encoding, errors="ignore")
        return self.parser_txt(text, chunk_token_num)

    @classmethod
    def parser_txt(cls, text: str, chunk_token_num: int):
        if not isinstance(text, str):
            raise TypeError("txt type should be string!")

        temp_sections = []
        soup = BeautifulSoup(text, "html.parser")
        for removable in soup.find_all(["style", "script"]):
            removable.decompose()
        for tag in soup.find_all(True):
            if "style" in tag.attrs:
                del tag.attrs["style"]
        for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
            comment.extract()

        root = soup.body or soup
        if soup.body is None:
            logging.debug("html_parser: parsing HTML fragment without <body>; falling back to soup root")
        cls.read_text_recursively(root, temp_sections, chunk_token_num=chunk_token_num)
        block_text_list, table_list = cls.merge_block_text(temp_sections)
        sections = cls.chunk_block(block_text_list, chunk_token_num=chunk_token_num)
        sections.extend(table.get("content", "") for table in table_list if table.get("content"))
        return sections

    @classmethod
    def read_text_recursively(cls, element, parser_result, chunk_token_num: int = 512, parent_name: str | None = None, block_id: str | None = None):
        if isinstance(element, NavigableString):
            content = element.strip()
            if content:
                info = {"content": content, "tag_name": parent_name or "inner_text", "metadata": {"block_id": block_id}}
                return [info]
            return []

        if isinstance(element, Tag):
            if element.name.lower() == "table":
                table_id = str(uuid.uuid1())
                return [{"content": html.unescape(str(element)), "tag_name": "table", "metadata": {"table_id": table_id, "index": 0}}]
            if element.name.lower() in BLOCK_TAGS:
                block_id = str(uuid.uuid1())
            for child in element.children:
                parser_result.extend(cls.read_text_recursively(child, parser_result, chunk_token_num, element.name, block_id))

        return []

    @classmethod
    def merge_block_text(cls, parser_result):
        block_content = []
        current_content = ""
        table_info_list = []
        last_block_id = None
        for item in parser_result:
            content = item.get("content", "")
            tag_name = item.get("tag_name")
            title_flag = tag_name in TITLE_TAGS
            block_id = item.get("metadata", {}).get("block_id")
            if block_id:
                if title_flag:
                    content = f"{TITLE_TAGS[tag_name]} {content}"
                if last_block_id != block_id:
                    if last_block_id is not None and current_content:
                        block_content.append(current_content)
                    current_content = content
                    last_block_id = block_id
                else:
                    current_content += (" " if current_content else "") + content
            elif tag_name == "table":
                table_info_list.append(item)
            else:
                current_content += (" " if current_content else "") + content
        if current_content:
            block_content.append(current_content)
        return block_content, table_info_list

    _SPACELESS = "぀-ヿ㐀-䶿一-鿿豈-﫿가-힯"
    _ATOM_RE = re.compile(r"[{s}]|[^\s{s}]+|\s+".format(s=_SPACELESS))

    @classmethod
    def _token_count(cls, text: str):
        if not text:
            return 0
        tokenized = rag_tokenizer.tokenize(text)
        return len(tokenized.split(" ")) if tokenized else 0

    @classmethod
    def _split_oversized_block(cls, block: str, chunk_token_num: int):
        pieces = []
        current = ""
        current_tokens = 0
        token_cache = {}

        def atom_token_count(atom: str):
            if atom.isspace():
                return 0
            if atom not in token_cache:
                token_cache[atom] = cls._token_count(atom)
            return token_cache[atom]

        for atom in cls._ATOM_RE.findall(block):
            atom_tokens = atom_token_count(atom)
            if current and current_tokens + atom_tokens > chunk_token_num:
                pieces.append(current)
                current = ""
                current_tokens = 0
            current += atom
            current_tokens += atom_tokens
        if current:
            pieces.append(current)
        return pieces

    @classmethod
    def chunk_block(cls, block_text_list, chunk_token_num: int = 512):
        chunks = []
        current_block = ""
        current_token_count = 0
        for block in block_text_list:
            block_token_count = cls._token_count(block)
            if block_token_count > chunk_token_num:
                if current_block:
                    chunks.append(current_block)
                    current_block = ""
                    current_token_count = 0
                chunks.extend(cls._split_oversized_block(block, chunk_token_num))
            elif current_token_count + block_token_count <= chunk_token_num:
                current_block += ("\n" if current_block else "") + block
                current_token_count += block_token_count
            else:
                chunks.append(current_block)
                current_block = block
                current_token_count = block_token_count
        if current_block:
            chunks.append(current_block)
        return chunks
