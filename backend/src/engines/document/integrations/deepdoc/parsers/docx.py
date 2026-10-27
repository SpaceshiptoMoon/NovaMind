"""DeepDoc DOCX 解析器。"""
from __future__ import annotations

# Adapted from RAGFlow deepdoc/parser/docx_parser.py
import logging
import re
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import Any

from docx import Document
from docx.image.exceptions import (
    InvalidImageStreamError,
    UnexpectedEndOfFileError,
    UnrecognizedImageError,
)
from docx.oxml.ns import nsmap as _DOCX_NSMAP
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from novamind.engines.document.exceptions import (
    EncryptedDocumentError,
    MismatchedPayloadError,
)
from novamind.engines.document.integrations.deepdoc.compat import (
    MAXIMUM_PAGE_NUMBER,
    LazyImage,
    guard_office_zip,
    rag_tokenizer,
    safe_fromstring,
)

# OLE 复合文档魔数（旧版 .doc/.xls/.ppt 与 OOXML 加密容器共用此头）
_OLE_HEADER_MAGIC = b"\xd0\xcf\x11\xe0"

# python-docx 全局 nsmap 无 VML 前缀，而 w:pict/v:imagedata 旧式图在 Word 2003
# 工具链与公式对象 fallback 中仍常见；注册类元素的 .xpath 只认这张表，缺前缀
# 直接查不到元素，模块加载期注入一次
_DOCX_NSMAP.setdefault("v", "urn:schemas-microsoft-com:vml")


class RAGFlowDocxParser:
    """RAGFlow DOCX 文档解析器（段落/图片/表格三路抽取）。"""
    def get_picture(self, document: Any, paragraph: Any) -> LazyImage | None:
        """抽取段落内嵌图片的二进制数据。

        覆盖 DrawingML（wp:inline/wp:anchor 内的 pic:pic）与 VML 旧式图
        （w:pict/v:imagedata）两代表示；mc:AlternateContent 中同一图片以两种
        表示并存时按关系 ID 去重。

        Args:
            document: python-docx Document 对象，用于解析图片关系 ID。
            paragraph: 待抽取的段落对象。

        Returns:
            懒加载图片对象（惰性读取 blob，避免解析期占内存）；段落无图或图片损坏时返回 None。
        """
        rel_ids: list[str] = []
        for img in paragraph._element.xpath(".//pic:pic"):
            rel_ids.extend(img.xpath(".//a:blip/@r:embed"))
        if not rel_ids:
            # DrawingML 未命中的旧式位图：Word 2003 工具链产物、公式对象的
            # 位图 fallback 等
            rel_ids = paragraph._element.xpath(".//v:imagedata/@r:id")

        image_blobs: list[bytes] = []
        seen_rel_ids: set[str] = set()
        for rel_id in rel_ids:
            if rel_id in seen_rel_ids:
                continue
            seen_rel_ids.add(rel_id)
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
        lines = self._compose_table_content(rows)
        # 表格单元格内嵌的原生图表/SmartArt：cell.text 不含（走独立 part），
        # 追加在表格文本尾部避免整块丢失
        lines.extend(self._chart_texts(table._tbl))
        lines.extend(self._smartart_texts(table._tbl))
        return lines

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
        payload = (
            Path(file_name_or_binary).read_bytes()
            if isinstance(file_name_or_binary, str)
            else file_name_or_binary
        )
        # 载荷守卫：OOXML 是 zip 包。OLE 复合文档头对 docx 入口只有两种来源
        # ——加密容器（打开密码/IRM 敏感度标签）或被误改扩展名的旧版 .doc；
        # 非两者即伪格式/损坏包。后续 python-docx 对这些会抛误导性的
        # PackageNotFoundError/BadZipFile 裸栈。
        if not payload.startswith(b"PK\x03\x04"):
            if payload.startswith(_OLE_HEADER_MAGIC):
                raise EncryptedDocumentError(
                    "docx 文档已加密（打开密码或敏感度标签），请解密后上传",
                    format_name="docx",
                )
            raise MismatchedPayloadError(
                "docx 内容不是 OOXML 包（可能是旧版 .doc 改名或文件损坏）",
                format_name="docx",
            )
        guard_office_zip(payload, "docx")
        self.doc = Document(BytesIO(payload))
        self._footnotes = self._load_footnotes()
        # 图片 artifact_id 计数器（每文档重置；闭包内自增）
        self._figure_counter = 0
        header_footer_sections = self._load_header_footer_sections()
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
                figure_id = ""
                if image:
                    # 图片进 figure 契约：artifact_id 定版于此（与 pdf/xlsx 同
                    # 协议），markdown 图片链接占位符随段落文本入正文流——业务
                    # 层替换后恰为 ](figure_xxx.png)，读取端点 presign 正则按此
                    # 识别换签名。纯图片段也产出占位符（text 保证非空入 section）
                    figure_id = f"docx_fig_{self._figure_counter}"
                    self._figure_counter += 1
                    link = f"![图片](__FIGURE_URL__{figure_id}__)"
                    text = f"{text}\n{link}" if text else link
                sections.append(
                    {"text": text, "style": style_name, "image": image,
                     "figure_id": figure_id}
                )
            # 段内文本框（流程图/标注框）原位锚定：紧跟所属段落，不再堆文档尾
            for box_text in self._paragraph_textbox_texts(paragraph._element):
                sections.append({"text": box_text, "style": "TextBox", "image": None})
            # 段内原生图表/SmartArt：数据存于独立 part，python-docx 不暴露，
            # 默认整图丢失；此处重组为文本，与文本框同款原位锚定
            for chart_text in self._chart_texts(paragraph._element):
                sections.append({"text": chart_text, "style": "Chart", "image": None})
            for smartart_text in self._smartart_texts(paragraph._element):
                sections.append({"text": smartart_text, "style": "SmartArt", "image": None})

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
        # 页眉页脚是文档级元信息（密级/公司/版本），逐页重复只取一次，置于
        # 文档最前；纯页码段已被域判据剔除
        for offset, (style, text) in enumerate(header_footer_sections):
            sections.insert(offset, {"text": text, "style": style, "image": None})
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
            root = safe_fromstring(blob)
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

    # 页码/日期时间类 Word 域：值由渲染期确定且逐页变化，对检索是噪音。
    # FILENAME/TOC/REF 等承载语义的域不在列，其缓存文本保留
    _AUTO_FIELD_TOKENS = (
        "PAGE",
        "NUMPAGES",
        "SECTIONPAGES",
        "DATE",
        "TIME",
        "PRINTDATE",
        "SAVEDATE",
        "CREATEDATE",
    )

    def _visible_text_without_fields(self, p_element) -> str:
        """段落可见文本：剔除域的缓存渲染值。

        复杂域（fldChar begin..separate..end）区间内与简单域（fldSimple
        子树）内的 w:t 都是上次渲染缓存（如页码 "7"），对 RAG 无意义。
        """
        from docx.oxml.ns import nsmap

        parts: list[str] = []
        field_depth = 0
        skip_ids: set[int] = set()
        for node in p_element.iter():
            if id(node) in skip_ids:
                continue
            if node.tag == qn("w:fldSimple"):
                skip_ids.update(id(descendant) for descendant in node.iter())
                continue
            if node.tag == qn("w:fldChar"):
                kind = node.get(qn("w:fldCharType"))
                if kind == "begin":
                    field_depth += 1
                elif kind == "end":
                    field_depth = max(0, field_depth - 1)
            elif node.tag == qn("w:t") and field_depth == 0:
                parts.append(node.text or "")
        return "".join(parts)

    def _load_header_footer_sections(self) -> list[tuple[str, str]]:
        """提取页眉页脚常量文本为 (样式名, 文本) 列表（Header 在前）。

        页眉页脚逐页重复，作为文档级元信息（密级/公司/版本号）只取一次；
        含页码/日期类自动域的段落整段视为页码噪音跳过。多 part（default/
        even/first）文本去重后按段落合并。解析异常时静默跳过该 part，不影响
        正文提取。
        """
        from docx.oxml.ns import nsmap

        out: list[tuple[str, str]] = []
        for style, suffix in (("Header", "/header"), ("Footer", "/footer")):
            lines: list[str] = []
            seen: set[str] = set()
            for rel in self.doc.part.rels.values():
                if not rel.reltype.endswith(suffix):
                    continue
                try:
                    root = safe_fromstring(rel.target_part.blob)
                except Exception:
                    continue
                for p in root.xpath(".//w:p", namespaces=nsmap):
                    instr = " ".join(
                        node.text or ""
                        for node in p.xpath(".//w:instrText", namespaces=nsmap)
                    ).upper()
                    if any(token in instr for token in self._AUTO_FIELD_TOKENS):
                        continue
                    text = self._visible_text_without_fields(p).strip()
                    if text and text not in seen:
                        seen.add(text)
                        lines.append(text)
            if lines:
                out.append((style, "\n".join(lines)))
        return out

    def _chart_texts(self, p_element) -> list[str]:
        """提取段落内原生图表（c:chart）的缓存系列数据为文本。

        Word 图表不是图片：数值存于独立 chart part 的 strCache/numCache，
        python-docx 不暴露该 part，默认整图丢失。按「系列名: 类别=值; ...」
        重组，图表标题并入前缀。
        """
        out: list[str] = []
        try:
            rel_ids = p_element.xpath(".//c:chart/@r:id")
        except Exception:
            return out
        for rel_id in rel_ids:
            try:
                blob = self.doc.part.related_parts[rel_id].blob
            except Exception:
                continue
            text = self._chart_blob_to_text(blob)
            if text:
                out.append(text)
        return out

    @staticmethod
    def _chart_blob_to_text(blob: bytes) -> str:
        """chart part 字节流重组为文本（标题 + 各系列数据点）。

        类别与值按缓存点序号 zip 对齐；无类别的系列只输出值。
        """
        chart_ns = {
            "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
            "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        }
        try:
            root = safe_fromstring(blob)
        except Exception:
            return ""
        title = "".join(root.xpath(".//c:title//a:t/text()", namespaces=chart_ns)).strip()
        series_lines: list[str] = []
        for ser in root.xpath(".//c:ser", namespaces=chart_ns):
            name = "".join(ser.xpath("./c:tx//c:v/text()", namespaces=chart_ns)).strip()
            cats = ser.xpath("./c:cat//c:pt/c:v/text()", namespaces=chart_ns)
            vals = ser.xpath("./c:val//c:pt/c:v/text()", namespaces=chart_ns)
            if not vals:
                continue
            points = [
                f"{cats[idx]}={value}" if idx < len(cats) and str(cats[idx]).strip() else str(value)
                for idx, value in enumerate(vals)
            ]
            series_lines.append(f"{name}: " + "; ".join(points) if name else "; ".join(points))
        if not series_lines:
            return ""
        prefix = f"[图表《{title}》] " if title else "[图表] "
        return prefix + " ｜ ".join(series_lines)

    def _smartart_texts(self, p_element) -> list[str]:
        """提取段落内 SmartArt（dgm:relIds）的节点文本。

        SmartArt 渲染为图形但语义是流程/层级文本，存于 diagram data part
        （dgm:pt 的 dgm:t）。仅取 node 类型节点，按文档顺序以「 → 」连接。
        """
        diagram_ns = {
            "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
            "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        }
        out: list[str] = []
        try:
            rel_ids = p_element.xpath(".//dgm:relIds/@r:dm")
        except Exception:
            return out
        for rel_id in rel_ids:
            try:
                blob = self.doc.part.related_parts[rel_id].blob
            except Exception:
                continue
            try:
                root = safe_fromstring(blob)
            except Exception:
                continue
            texts = []
            for pt in root.xpath(
                ".//dgm:pt[not(@type) or @type='node']/dgm:t", namespaces=diagram_ns
            ):
                node_text = "".join(
                    pt.xpath(".//a:t/text()", namespaces=diagram_ns)
                ).strip()
                if node_text:
                    texts.append(node_text)
            if texts:
                out.append("[SmartArt] " + " → ".join(texts))
        return out
