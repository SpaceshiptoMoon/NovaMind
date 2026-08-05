from __future__ import annotations

# Adapted from RAGFlow deepdoc/parser/markdown_parser.py

import re

try:
    from markdown import markdown as render_markdown
except Exception:  # pragma: no cover - optional dependency fallback
    render_markdown = None


class RAGFlowMarkdownParser:
    def __init__(self, chunk_token_num: int = 128):
        self.chunk_token_num = int(chunk_token_num)

    def extract_tables_and_remainder(self, markdown_text: str, separate_tables: bool = True):
        tables = []
        working_text = markdown_text

        def replace_tables(pattern, render=True):
            nonlocal working_text
            new_text = ""
            last_end = 0
            for match in pattern.finditer(working_text):
                raw_table = match.group()
                tables.append(raw_table)
                if separate_tables:
                    new_text += working_text[last_end:match.start()] + "\n\n"
                else:
                    html_table = (
                        render_markdown(raw_table, extensions=["markdown.extensions.tables"])
                        if render and render_markdown is not None
                        else raw_table
                    )
                    new_text += working_text[last_end:match.start()] + html_table + "\n\n"
                last_end = match.end()
            new_text += working_text[last_end:]
            working_text = new_text

        if "|" in markdown_text:
            border_table_pattern = re.compile(
                r"""
                (?:\n|^)
                (?:\|.*?\|.*?\|.*?\n)
                (?:\|(?:\s*[:-]+[-| :]*\s*)\|.*?\n)
                (?:\|.*?\|.*?\|.*?\n)+
            """,
                re.VERBOSE,
            )
            replace_tables(border_table_pattern)

        return working_text, tables


class MarkdownElementExtractor:
    def __init__(self, markdown_content: str):
        self.lines = markdown_content.split("\n")

    def extract_elements(self):
        sections = []
        current = []
        for line in self.lines:
            if re.match(r"^#{1,6}\s+.*$", line):
                if current:
                    sections.append("\n".join(current).strip())
                    current = []
                current.append(line)
                continue
            if not line.strip():
                if current:
                    sections.append("\n".join(current).strip())
                    current = []
                continue
            current.append(line)
        if current:
            sections.append("\n".join(current).strip())
        return [section for section in sections if section]
