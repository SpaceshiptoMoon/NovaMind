"""DeepDoc DOCX 解析器。"""
from __future__ import annotations

# Adapted from RAGFlow deepdoc/parser/docx_parser.py
import logging
import re
from collections.abc import Sequence
from io import BytesIO
from typing import Any

from docx import Document
from docx.image.exceptions import (
    InvalidImageStreamError,
    UnexpectedEndOfFileError,
    UnrecognizedImageError,
)
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from novamind.engines.document.integrations.deepdoc.compat import (
    MAXIMUM_PAGE_NUMBER,
    LazyImage,
    rag_tokenizer,
)


class RAGFlowDocxParser:
    """RAGFlow DOCX 文档解析器（段落/图片/表格三路抽取）。"""
    def get_picture(self, document: Any, paragraph: Any) -> LazyImage | None:
        """抽取段落内嵌图片的二进制数据。
        
        Args:
            document: python-docx Document 对象，用于解析图片关系 ID。
            paragraph: 待抽取的段落对象。
        
        Returns:
            懒加载图片对象（惰性读取 blob，避免解析期占内存）；段落无图或图片损坏时返回 None。
        """
        imgs = paragraph._element.xpath(".//pic:pic")
        if not imgs:
            return None

        image_blobs: list[bytes] = []
        for img in imgs:
            embed = img.xpath(".//a:blip/@r:embed")
            if not embed:
                continue
            rel_id = embed[0]
            image_blob = None
            try:
                related_part = document.part.related_parts[rel_id]
            except Exception as exc:
                logging.warning("Skipping image due to unexpected related part error: %s", exc)
                continue

            try:
                image = related_part.image
                if image is not None:
                    image_blob = image.blob
            except (
                UnrecognizedImageError,
                UnexpectedEndOfFileError,
                InvalidImageStreamError,
                UnicodeDecodeError,
            ) as exc:
                logging.info("Damaged image encountered, attempting blob fallback: %s", exc)
            except Exception as exc:
                logging.warning("Unexpected error getting image, attempting blob fallback: %s", exc)

            if image_blob is None:
                image_blob = getattr(related_part, "blob", None)
            if image_blob:
                image_blobs.append(image_blob)

        if not image_blobs:
            return None
        return LazyImage(image_blobs)

    def _extract_table_content(self, table: Any) -> list[str]:
        """把表格对象转为二维文本行，交由 _compose_table_content 拼装。"""
        # 合并单元格去重：python-docx 对 spanned 网格位返回同一 cell，
        # 不去重会让合并表头/单元格文本重复 N 遍（红队 P1-2）
        rows = []
        for row in table.rows:
            seen_tc = set()
            row_texts = []
            for cell in row.cells:
                if id(cell._tc) in seen_tc:
                    continue
                seen_tc.add(id(cell._tc))
                row_texts.append(cell.text)
            rows.append(row_texts)
        return self._compose_table_content(rows)

    def _compose_table_content(self, rows: Sequence[Sequence[str]]) -> list[str]:
        """按表头-数据行关系把表格行拼装为「表头: 值」文本。
        
        先按单元格内容类型（日期/数值/文本等）投票定主类型，主类型为数值的表格
        把类型不一致的行识别为多级表头；每行数据与对应表头拼接，再按列数决定
        逐行输出（宽表）或合并为单块文本（窄表）。
        """
        def block_type(block: str) -> str:
            """单元格文本类型判定：Dt 日期 / Nu 数值 / Tx·Lx 文本 / Nr 人名等（表头识别用）。"""
            patterns = [
                (r"^(20|19)[0-9]{2}[年/-][0-9]{1,2}[月/-][0-9]{1,2}日*$", "Dt"),
                (r"^(20|19)[0-9]{2}年$", "Dt"),
                (r"^(20|19)[0-9]{2}[年/-][0-9]{1,2}月*$", "Dt"),
                (r"^[0-9]{1,2}[月/-][0-9]{1,2}日*$", "Dt"),
                (r"^第?[一二三四1-4]季度$", "Dt"),
                (r"^(20|19)[0-9]{2}年?[一二三四1-4]季度$", "Dt"),
                (r"^(20|19)[0-9]{2}[ABCDE]$", "DT"),
                (r"^[0-9.,+%/ -]+$", "Nu"),
                (r"^[0-9A-Z/\._~-]+$", "Ca"),
                (r"^[A-Z]*[a-z' -]+$", "En"),
                (r"^[0-9.,+-]+[0-9A-Za-z/$￥%<>（）()' -]+$", "NE"),
                (r"^.{1}$", "Sg"),
            ]
            for pattern, name in patterns:
                if re.search(pattern, block):
                    return name

            tokens = [t for t in rag_tokenizer.tokenize(block).split() if len(t) > 1]
            if len(tokens) > 3:
                return "Tx" if len(tokens) < 12 else "Lx"
            if len(tokens) == 1 and rag_tokenizer.tag(tokens[0]) == "nr":
                return "Nr"
            return "Ot"

        if len(rows) < 2:
            return []

        column_count = max(len(row) for row in rows)
        normalized_rows = [list(row) + [""] * (column_count - len(row)) for row in rows]
        data_rows = normalized_rows[1:]

        dominant_counts = {}
        for row in data_rows:
            for cell in row:
                name = block_type(str(cell))
                dominant_counts[name] = dominant_counts.get(name, 0) + 1
        dominant_type = max(dominant_counts.items(), key=lambda item: item[1])[0]

        header_rows = [0]
        if dominant_type == "Nu":
            for row_index in range(1, len(normalized_rows)):
                row_types = {}
                for cell in normalized_rows[row_index]:
                    name = block_type(str(cell))
                    row_types[name] = row_types.get(name, 0) + 1
                row_type = max(row_types.items(), key=lambda item: item[1])[0]
                if row_type != dominant_type:
                    header_rows.append(row_index)

        lines: list[str] = []
        for row_index in range(1, len(normalized_rows)):
            if row_index in header_rows:
                continue

            related_headers = [idx for idx in header_rows if idx < row_index]
            if len(related_headers) > 1:
                trimmed = [related_headers[-1]]
                for i in range(len(related_headers) - 2, -1, -1):
                    if trimmed[0] - related_headers[i] <= 1:
                        trimmed.insert(0, related_headers[i])
                    else:
                        break
                related_headers = trimmed

            headers: list[str] = []
            for column_index in range(column_count):
                pieces: list[str] = []
                for header_index in related_headers:
                    value = str(normalized_rows[header_index][column_index]).strip()
                    if value and value not in pieces:
                        pieces.append(value)
                header = ",".join(pieces)
                headers.append(f"{header}: " if header else "")

            cells: list[str] = []
            for column_index in range(column_count):
                value = str(normalized_rows[row_index][column_index]).strip()
                if value:
                    cells.append(headers[column_index] + value)
            lines.append(";".join(cells))

        if column_count > 3:
            return lines
        return ["\n".join(lines)] if lines else []

    def __call__(self, file_name_or_binary: str | bytes, from_page: int = 0, to_page: int = MAXIMUM_PAGE_NUMBER):
        """解析 DOCX 为段落 section 列表与表格文本列表（保持文档物理顺序）。

        按 body 元素序交错遍历段落与表格：表格位置在 sections 中以
        ``table_index`` 占位（消费方据此把表格文本插回原位），不再出现
        「表格内容全部堆到文档尾」的顺序错乱。列表段（numPr）带「• 」前缀，
        文本框内容以 TextBox 样式追加在文档尾（python-docx 无法锚定其
        渲染位置，尾部保留优于丢失）。

        Args:
            file_name_or_binary: 文件路径或 DOCX 字节流。
            from_page: 起始页码（按 lastRenderedPageBreak 计数）。
            to_page: 结束页码（不含），超出范围的段落文本留空。

        Returns:
            (sections, tables) 二元组；section 为含 text/style/image 的字典
            列表（表格位置项额外带 table_index），tables 为表格文本行列表的
            列表，顺序与 doc.tables 一致。
        """
        self.doc = (
            Document(file_name_or_binary)
            if isinstance(file_name_or_binary, str)
            else Document(BytesIO(file_name_or_binary))
        )
        self._footnotes = self._load_footnotes()
        parsed_page = 0
        sections: list[dict[str, Any]] = []
        table_index = 0
        sdt_tables: list[Any] = []

        def _emit_paragraph(paragraph: Paragraph) -> None:
            """按分页窗口产出单个段落的 section（含脚注/文本框原位锚定）。"""
            nonlocal parsed_page
            if parsed_page > to_page:
                return
            # 修订模式段落：python-docx 对 w:ins/w:del 静默——runs/text 均不含
            # 插入文本（实测修订段整段消失），需按「接受修订终稿」XML 级提取
            has_revisions = bool(
                paragraph._element.xpath(".//w:ins or .//w:del")
            )
            if has_revisions:
                text = self._accepted_text(paragraph._element).strip()
            else:
                # paragraph.text 含超链接显示文本（runs 累加会丢 hyperlink 内
                # 文字，python-docx 1.2 实测：hyperlink-only 段落 runs 为空而
                # text 完整）
                text = (paragraph.text or "").strip()
            breaks = paragraph._element.xpath(".//w:lastRenderedPageBreak")
            parsed_page += len(breaks)
            if from_page <= parsed_page < to_page and text:
                # 脚注引用内联：正文词句与注释同 context 进 chunk
                ref_ids = paragraph._element.xpath(".//w:footnoteReference/@w:id")
                for fid in ref_ids:
                    note = self._footnotes.get(str(fid))
                    if note:
                        text = f"{text} [脚注{fid}: {note}]"
                style_name = (
                    paragraph.style.name if hasattr(paragraph.style, "name") else ""
                )
                # 列表段：numPr 编号语义由 Word 渲染期生成、python-docx 拿不到
                # 真实序号，以「• 」前缀保住"这是列表成员"的语义
                p_pr = paragraph._p.pPr
                is_list_item = p_pr is not None and p_pr.numPr is not None
                if is_list_item and not text.startswith("•"):
                    text = f"• {text}"
                image = self.get_picture(self.doc, paragraph)
                sections.append({"text": text, "style": style_name, "image": image})
            # 段内文本框（流程图/标注框）原位锚定：紧跟所属段落，不再堆文档尾
            for box_text in self._paragraph_textbox_texts(paragraph._element):
                sections.append({"text": box_text, "style": "TextBox", "image": None})

        for child in self.doc.element.body.iterchildren():
            if child.tag == qn("w:tbl"):
                sections.append(
                    {"text": "", "style": "", "image": None, "table_index": table_index}
                )
                table_index += 1
                continue
            if child.tag == qn("w:sdt"):
                # 内容控件包裹的文档（模板生成的合同/表单）整块跳过=丢内容：
                # 穿透取其内段落（排除表格内段落，表格走占位协议）与表格。
                # iterchildren 返回裸 lxml 元素，xpath 必须显式 nsmap
                from docx.oxml.ns import nsmap

                for inner_p in child.xpath(
                    ".//w:p[not(ancestor::w:tbl)]", namespaces=nsmap
                ):
                    _emit_paragraph(Paragraph(inner_p, self.doc))
                for inner_tbl in child.xpath(".//w:tbl", namespaces=nsmap):
                    sections.append(
                        {"text": "", "style": "", "image": None,
                         "table_index": table_index}
                    )
                    table_index += 1
                    sdt_tables.append(Table(inner_tbl, self.doc))
                continue
            if child.tag != qn("w:p"):
                continue
            _emit_paragraph(Paragraph(child, self.doc))

        tables = [
            self._extract_table_content(table)
            for table in list(self.doc.tables) + sdt_tables
        ]
        return sections, tables

    def _accepted_text(self, p_element) -> str:
        """接受修订视角的段落文本：保留插入（w:ins）文字，丢弃删除（w:del）文字。

        知识库入库语义取「接受修订后的终稿」。w:del 内是被删除文字
        （w:delText，不含 w:t），w:t 直取天然排除；普通/超链接/插入内文字
        统一经 .//w:t 收集。纯文本拼接丢弃 tab/换行符（RAG 文本可接受）。
        """
        try:
            # p_element 是 python-docx 注册类（CT_P），其 .xpath 自带命名空间表
            # （不可传 namespaces 参数，会 TypeError）
            nodes = p_element.xpath(".//w:t[not(ancestor::w:del)]")
        except Exception:
            return ""
        return "".join(node.text or "" for node in nodes)

    def _load_footnotes(self) -> dict[str, str]:
        """读取脚注 part（python-docx 无公开 API，经关系直取 footnotes part）。

        Returns:
            {脚注 id: 注释文本}；无脚注 part 或解析失败返回空 dict。
        """
        from docx.oxml.ns import nsmap

        try:
            for rel in self.doc.part.rels.values():
                if rel.reltype.endswith("/footnotes"):
                    blob = rel.target_part.blob
                    break
            else:
                return {}
            from lxml import etree

            root = etree.fromstring(blob)
            out: dict[str, str] = {}
            for fn in root.xpath(".//w:footnote", namespaces=nsmap):
                if fn.get(qn("w:type")):
                    continue  # separator/continuationSeparator 非真实注释
                fid = fn.get(qn("w:id"))
                text = "".join(
                    t.text or "" for t in fn.xpath(".//w:t", namespaces=nsmap)
                ).strip()
                if fid is not None and text:
                    out[fid] = " ".join(text.split())
            return out
        except Exception:
            return {}

    def _paragraph_textbox_texts(self, p_element) -> list[str]:
        """提取段落内文本框（w:txbxContent）的可见文本（原位锚定）。

        w:txbxContent 非 python-docx 注册类，其返回元素的 .xpath 无内置
        nsmap，必须显式传 namespaces。
        """
        from docx.oxml.ns import nsmap

        texts: list[str] = []
        try:
            boxes = p_element.xpath(".//w:txbxContent")
        except Exception:
            return texts
        for box in boxes:
            try:
                pieces = [
                    node.text for node in box.xpath(".//w:t", namespaces=nsmap)
                    if node.text
                ]
            except Exception:
                continue
            text = "".join(pieces).strip()
            if text:
                texts.append(text)
        return texts
