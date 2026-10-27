"""DeepDoc HTML 解析器。"""
from __future__ import annotations

# Adapted from RAGFlow deepdoc/parser/html_parser.py
import html
import logging
import re
import uuid

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from novamind.engines.document.integrations.deepdoc.compat import find_codec, rag_tokenizer

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
# 无表头表判定：数值形态格（含千分位/货币/百分号）
_HTML_NUMERIC_RE = re.compile(r"^-?[$￥€]?\d[\d,，]*\.?\d*%?$")


def _column_letter(index: int) -> str:
    """0-based 列序号转 Excel 列字母（无表头表占位用）。"""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


class RAGFlowHtmlParser:
    """RAGFlow HTML 解析器：DOM 遍历抽文本块并按 token 预算分块。"""
    def __call__(self, file_name: str, binary: bytes | None = None, chunk_token_num: int = 512):
        """解析 HTML 为分块文本列表。
        
        Args:
            file_name: 文件路径（binary 为 None 时使用）。
            binary: HTML 字节流；编码自动探测。
            chunk_token_num: 单块 token 上限。
        """
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
        """HTML 文本清洗并分块。
        
        剔除 style/script/注释后按块级元素递归收集文本，同块文本合并，
        表格 HTML 单独收集，最后按 token 预算分块并追加表格块。
        """
        if not isinstance(text, str):
            raise TypeError("txt type should be string!")

        temp_sections = []
        soup = BeautifulSoup(text, "html.parser")
        # style/script 剔除；template（不渲染的模板）/noscript（无 JS 回退，
        # 通常与正文重复）/select（交互控件选项非内容）/nav（导航样板）同为
        # 噪音源（网页存档类 HTML 会被导航与下拉选项淹没）；rt/rp 是 ruby
        # 注音（剔除后保留注音基底字，防注音重复进索引）
        for removable in soup.find_all(
            ["style", "script", "template", "noscript", "select", "nav", "rt", "rp"]
        ):
            removable.decompose()
        for tag in soup.find_all(True):
            if "style" in tag.attrs:
                del tag.attrs["style"]
        for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
            comment.extract()

        root = soup.body or soup
        if soup.body is None:
            logging.debug("html_parser: parsing HTML fragment without <body>; falling back to soup root")
        try:
            cls.read_text_recursively(root, temp_sections, chunk_token_num=chunk_token_num)
        except RecursionError as exc:
            # 深嵌套（恶意/异常文件，2000 层即可构造）递归爆栈：转显式可读错误
            raise ValueError("HTML 嵌套层级过深，超出解析器递归上限") from exc
        ordered_blocks, _table_list = cls.merge_block_text(temp_sections)
        # 文本块按 token 预算聚合切分；表格块整块原位输出（不进聚合器——
        # 表格 HTML 被邻块合并或按字符窗硬切都会破坏结构）
        sections = []
        for kind, content in ordered_blocks:
            if kind == "table":
                sections.append(content)
            else:
                sections.extend(cls.chunk_block([content], chunk_token_num=chunk_token_num))
        return sections

    @classmethod
    def read_text_recursively(cls, element, parser_result, chunk_token_num: int = 512, parent_name: str | None = None, block_id: str | None = None):
        """深度优先遍历 DOM：文本串记入当前块，table 整体输出，块级标签开新块。
        
        Args:
            element: 当前遍历的 BeautifulSoup 节点。
            parser_result: 结果缓冲（就地扩展）。
            chunk_token_num: 兼容参数，遍历阶段不使用。
            parent_name: 父标签名，裸文本用它标记归属。
            block_id: 当前块级元素 ID，同块文本靠它聚合。
        """
        if isinstance(element, NavigableString):
            # 不间断空格归一：\xa0 对分词/向量是噪音（视觉上与空格无异）
            content = element.replace("\xa0", " ").strip()
            if content:
                info = {"content": content, "tag_name": parent_name or "inner_text", "metadata": {"block_id": block_id}}
                return [info]
            return []

        if isinstance(element, Tag):
            name = element.name.lower()
            if name == "table":
                return cls._table_to_blocks(element)
            if name == "li":
                # 列表项语义保真：整项一行加「• 」前缀（嵌套列表会拍平进同行）
                text = element.get_text(" ", strip=True)
                if text:
                    return [{"content": f"• {text}", "tag_name": "li",
                             "metadata": {"block_id": str(uuid.uuid1())}}]
                return []
            if name == "img":
                # alt 是 HTML 图片的官方语义描述（对照 Excel 图片提取链路）
                alt = (element.get("alt") or "").strip()
                if alt:
                    return [{"content": alt, "tag_name": "img",
                             "metadata": {"block_id": str(uuid.uuid1())}}]
                return []
            if name in ("script", "style"):
                return []
            if name in BLOCK_TAGS:
                block_id = str(uuid.uuid1())
            for child in element.children:
                parser_result.extend(cls.read_text_recursively(child, parser_result, chunk_token_num, element.name, block_id))

        return []

    @classmethod
    def _table_to_blocks(cls, table_el, window_rows: int = 50):
        """表格 → 按行窗口的多个表格块（每窗重复表头），防超大表格单块超
        embedding 上限后 90% 行被静默截断（3000 行实测产出 5.4 万 token 单块）。

        嵌套表格回退整体序列化（递归结构难以按行切）。单元格取 bs4 解码后
        纯文本再转义（旧实现的 html.unescape 会把 &lt; 还原成裸 < 破坏表格
        结构）。无 th 且首行数值占比 >0.3 判无表头表，列字母占位。
        """
        if table_el.find("table") or not table_el.find("tr"):
            # 嵌套表格 / 无行表格：整体序列化
            return [{
                "content": str(table_el), "tag_name": "table",
                "metadata": {"table_id": str(uuid.uuid1()), "index": 0},
            }]

        def row_cells(tr):
            cells = tr.find_all(["th", "td"])
            if not cells:
                return [tr.get_text(" ", strip=True)]
            return [c.get_text(" ", strip=True) for c in cells]

        trs = table_el.find_all("tr")
        header_cells = row_cells(trs[0])
        body = trs[1:]
        has_th = bool(trs[0].find("th"))
        if not has_th:
            non_empty = [t for t in header_cells if t]
            numeric = sum(1 for t in non_empty if _HTML_NUMERIC_RE.match(t))
            if non_empty and numeric / len(non_empty) > 0.3:
                body = trs
                header_cells = [_column_letter(i) for i in range(len(header_cells))]
        header_html = (
            "<tr>"
            + "".join(f"<th>{html.escape(h)}</th>" for h in header_cells)
            + "</tr>"
        )
        if not body:
            # 仅表头行（无数据行）：表头即全部内容，原样保留不丢
            return [{
                "content": f"<table>{header_html}</table>\n",
                "tag_name": "table",
                "metadata": {"table_id": str(uuid.uuid1()), "index": 0},
            }]
        blocks = []
        for window_start in range(0, len(body), window_rows):
            window = body[window_start : window_start + window_rows]
            rows_html = "".join(
                "<tr>"
                + "".join(f"<td>{html.escape(c)}</td>" for c in row_cells(tr))
                + "</tr>"
                for tr in window
            )
            blocks.append({
                "content": f"<table>{header_html}{rows_html}</table>\n",
                "tag_name": "table",
                "metadata": {"table_id": str(uuid.uuid1()), "index": window_start},
            })
        return blocks

    @classmethod
    def merge_block_text(cls, parser_result):
        """按 block_id 聚合文本块；标题行加 Markdown 井号前缀；表格原位输出。

        Returns:
            (有序块列表, 表格信息列表) 二元组。有序块为 ("text", 文本) /
            ("table", 表格 HTML) 二元组——表格保持文档位置不堆尾（与 Word
            表格原位修复同因）。表格信息列表仅为兼容旧签名保留。
        """
        ordered: list[tuple[str, str]] = []
        table_info_list: list[dict] = []
        current_content = ""
        last_block_id = None

        def _flush():
            nonlocal current_content, last_block_id
            if current_content:
                ordered.append(("text", current_content))
            current_content = ""
            last_block_id = None

        for item in parser_result:
            content = item.get("content", "")
            tag_name = item.get("tag_name")
            title_flag = tag_name in TITLE_TAGS
            block_id = item.get("metadata", {}).get("block_id")
            if tag_name == "table":
                _flush()
                ordered.append(("table", content))
                table_info_list.append(item)
                continue
            if block_id:
                if title_flag:
                    content = f"{TITLE_TAGS[tag_name]} {content}"
                if last_block_id != block_id:
                    _flush()
                    current_content = content
                    last_block_id = block_id
                else:
                    current_content += (" " if current_content else "") + content
            else:
                current_content += (" " if current_content else "") + content
        _flush()
        return ordered, table_info_list

    _SPACELESS = "぀-ヿ㐀-䶿一-鿿豈-﫿가-힯"
    _ATOM_RE = re.compile(rf"[{_SPACELESS}]|[^\s{_SPACELESS}]+|\s+")

    @classmethod
    def _token_count(cls, text: str):
        """RAGFlow 分词后的 token 数（块大小计量）。"""
        if not text:
            return 0
        tokenized = rag_tokenizer.tokenize(text)
        return len(tokenized.split(" ")) if tokenized else 0

    @classmethod
    def _split_oversized_block(cls, block: str, chunk_token_num: int):
        """把超 token 预算的块按最小语言单元（CJK 单字/连续非空白串）切小。
        
        单个 atom 仍超预算（长 URL/base64 等）时按字符窗口硬切。
        """
        pieces = []
        current = ""
        current_tokens = 0
        token_cache = {}

        def atom_token_count(atom: str):
            """单个语言单元的 token 数（带缓存）。"""
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
            if atom_tokens > chunk_token_num and not atom.isspace():
                # 单个 atom 超过 token 预算（长 URL / base64 / 无空格超长串）：
                # 按 chunk_token_num 字符窗口切块，否则整段会作为一个超大 chunk。
                # 对齐上游 html_parser._split_oversized_block 的回退分支。
                for i in range(0, len(atom), chunk_token_num):
                    pieces.append(atom[i : i + chunk_token_num])
                continue
            current += atom
            current_tokens += atom_tokens
        if current:
            pieces.append(current)
        return pieces

    @classmethod
    def chunk_block(cls, block_text_list, chunk_token_num: int = 512):
        """把块文本聚合到 token 预算内；超预算的块先切小再输出。

        Args:
            block_text_list: 块文本列表（同块文本已按 block_id 聚合）。
            chunk_token_num: 单块 token 上限。

        Returns:
            聚合后的分块文本列表。
        """
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
