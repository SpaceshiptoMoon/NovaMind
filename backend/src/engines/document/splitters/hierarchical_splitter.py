"""层级切分器：混合文档（正文+表格+代码）结构感知切分，特殊对象不二次切分。

一级按 Markdown 标题（# / ##）切章节保证语义完整；二级在章节内识别表格与
代码块为「特殊对象」独立成块；正文按 recursive 细分（普通文本语义）。
所有块携带 content_type（text/table/code）与所属章节锚点（section_slot），
检索期双向扩展（特殊对象回带章节正文、正文锚点拉取关联特殊对象）依赖该锚点。

设计取舍（与 parent_child 的关键差异）：正文块与特殊对象**都参与召回与
向量化**——正文是检索主对象而非回带容器，因此不走 chunk_role=parent 的
「排除召回+跳过 embedding」路径；章节锚点块（section 锚）用 content_type=text
普通正文身份参与召回，扩展只做「追加」不改写命中 content。
"""
import re

from novamind.engines.document.splitters.base_splitter import BaseSplitter
from novamind.engines.document.splitters.recursive_splitter import RecursiveCharacterSplitter

# Markdown 标题行：1-2 级（H1/H2 作章节边界；H3+ 视为章节内正文行，
# 深层标题在正文中仍有语义信号，不必升为边界）。
_HEADING_RE = re.compile(r"^(#{1,2})\s+(.+)")
# fenced 代码块围栏：``` 或 ~~~ 开头（允许缩进 ≤3 空格，行内信息量后缀忽略）
_FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
# HTML 表格块：成对 <table>...</table>（deepdoc 渲染形态；单行跨行均匹配）
_HTML_TABLE_RE = re.compile(r"<table[\s>].*?</table>", re.DOTALL | re.IGNORECASE)


def _is_table_separator(line: str) -> bool:
    """判断表格分隔行（| --- | :---: | 形态；管道可省略但破折号列必须有）。"""
    core = line.strip().strip("|").strip()
    if not core:
        return False
    cells = core.split("|")
    return all(re.fullmatch(r"\s*:?-{3,}:?\s*", c) for c in cells)


def _looks_like_table_block(lines: list[str], start: int) -> int | None:
    """从 lines[start] 起识别 markdown 管道表块，返回结束行号（不含）或 None。

    形态要求：首行含管道，次行是分隔行（若存在次行）；此后连续管道行都算表体。
    单行带管道的普通文本（如 "a | b"）无分隔行确认不算表。
    """
    if "|" not in lines[start]:
        return None
    end = start + 1
    if end < len(lines) and _is_table_separator(lines[end]):
        end += 1
        while end < len(lines) and "|" in lines[end] and lines[end].strip():
            end += 1
        return end
    # 无分隔行：仅当连续 ≥3 行都带管道才认表（防误伤普通含管道文本）
    body = start
    while body < len(lines) and "|" in lines[body] and lines[body].strip():
        body += 1
    if body - start >= 3:
        return body
    return None


class HierarchicalSplitter(BaseSplitter):
    """层级切分器：章节边界 → 特殊对象抽取 → 正文 recursive 细分。

    章节锚点语义：**章节首个产出块即锚点**（标题行前置到首块文本），不产
    独立锚点块——锚点与首个正文/特殊对象块天然合一，零内容重复；
    build_es_chunks 两遍式按 section_slot 取章节首个 text 块解析绝对指针。
    """

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 100,
                 min_chunk_size: int = 200):
        """初始化层级切分器。

        Args:
            chunk_size: 正文块最大字符数（特殊对象不受此限，整块保留）。
            chunk_overlap: 正文块间重叠字符数，特殊对象无重叠。
            min_chunk_size: 正文碎块合并阈值（仅章节内生效）。

        Raises:
            ValueError: chunk_size < 50 或 chunk_overlap >= chunk_size 时
                （正文细分的配置矛盾）。
        """
        super().__init__()
        if chunk_size < 50:
            raise ValueError(f"chunk_size ({chunk_size}) 不得小于 50")
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) 必须小于 chunk_size ({chunk_size})"
            )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    async def split(self, documents: list[dict[str, str]]) -> list[dict[str, str]]:
        """层级切分文档列表：章节 → 特殊对象 → 正文，输出按阅读序排列。

        Args:
            documents: 原始文档列表，每项含 text/source，可选 page/doc_id/type。

        Returns:
            切分后的文档块列表。每块 meta 携带：
            - ``content_type``: "text" | "table" | "code"
            - ``section_slot``: 所属章节 0 基序数
            - ``expansion_type``: "hierarchical"（恒定，检索期扩展开关）
        """
        split_docs = []
        for doc in documents:
            text = doc["text"]
            source = doc["source"]
            original_page = doc.get("page", 1)
            original_doc_id = doc.get("doc_id", "")
            doc_type = doc.get("type", "unknown")
            sections = self._segment_sections(text)
            for slot, blocks_in_section in enumerate(sections):
                # 标题行前置到章节首个产出块（保内容不丢失；锚点语义随首块走）
                heading = ""
                body_blocks = blocks_in_section
                if blocks_in_section and blocks_in_section[0][0] == "heading":
                    heading = blocks_in_section[0][1].strip()
                    body_blocks = blocks_in_section[1:]
                first_emitted = True
                for block_kind, block_text in body_blocks:
                    if block_kind == "text":
                        if not block_text.strip():
                            continue
                        sub = RecursiveCharacterSplitter(
                            chunk_size=self.chunk_size,
                            chunk_overlap=self.chunk_overlap,
                            min_chunk_size=0,  # 合并只在章节内做（merge_within_section）
                        )
                        sub_texts = await sub._split_text(block_text)
                        merged = merge_within_section(
                            [t for t in sub_texts if t.strip()], self.min_chunk_size
                        )
                        for j, t in enumerate(merged):
                            payload = t
                            if first_emitted:
                                payload = f"{heading}\n\n{t}" if heading else t
                                first_emitted = False
                            split_docs.append({
                                "text": payload,
                                "source": source,
                                "page": original_page,
                                "doc_id": f"{original_doc_id}_h_chunk_s{slot}t{j}",
                                "type": doc_type,
                                "meta": {
                                    "content_type": "text",
                                    "section_slot": slot,
                                    "expansion_type": "hierarchical",
                                },
                            })
                    else:
                        # 特殊对象（table/code）：独立成块绝不二次切分——表格行
                        # 切开丢结构、代码切开不可运行，宁超 chunk_size 不破坏
                        payload = block_text
                        if first_emitted:
                            payload = f"{heading}\n\n{block_text}" if heading else block_text
                            first_emitted = False
                        split_docs.append({
                            "text": payload,
                            "source": source,
                            "page": original_page,
                            "doc_id": f"{original_doc_id}_h_chunk_s{slot}{block_kind[0]}",
                            "type": doc_type,
                            "meta": {
                                "content_type": block_kind,
                                "section_slot": slot,
                                "expansion_type": "hierarchical",
                            },
                        })
        return split_docs

    def _segment_sections(self, text: str) -> list[list[tuple[str, str]]]:
        """一级切分：按 H1/H2 边界分章节，章内二级识别出特殊对象块。

        连续文本行聚合成单一 text 块（逐行成块会让 recursive 失去跨行聚拢
        机会，且 H3 标题行会脱离其正文）。

        Returns:
            ``[[(kind, text), ...], ...]``——外层每项是一个章节（保序），
            内层是 (kind, text) 块序列；kind ∈ heading/text/table/code。
            无标题文本产出单章节（heading 缺省，语义不退化）。
        """
        lines = text.split("\n")
        sections: list[list[tuple[str, str]]] = []
        current: list[tuple[str, str]] = []
        pending_text: list[str] = []

        def _flush_text() -> None:
            if pending_text:
                current.append(("text", "\n".join(pending_text)))
                pending_text.clear()

        i = 0
        while i < len(lines):
            line = lines[i]
            m = _HEADING_RE.match(line)
            if m and current:
                # 新章节边界：已积累内容成章（标题行留给新章节做锚点）
                _flush_text()
                sections.append(current)
                current = []
            if m:
                current.append(("heading", line))
                i += 1
                continue
            # fenced 代码块：从围栏行到配对围栏行（未闭合则吃到文末，不丢内容）
            fence = _FENCE_RE.match(line)
            if fence:
                _flush_text()
                j = i + 1
                while j < len(lines) and not _FENCE_RE.match(lines[j]):
                    j += 1
                end = j + 1 if j < len(lines) else len(lines)
                current.append(("code", "\n".join(lines[i:end])))
                i = end
                continue
            # HTML 表格块（deepdoc 渲染形态）：整体吞入
            rest = "\n".join(lines[i:])
            html_m = _HTML_TABLE_RE.match(rest)
            if html_m:
                _flush_text()
                current.append(("table", html_m.group(0)))
                i += html_m.group(0).count("\n") + (0 if html_m.group(0).endswith("\n") else 1)
                continue
            # markdown 管道表块：按行窗口识别
            tbl_end = _looks_like_table_block(lines, i)
            if tbl_end is not None:
                _flush_text()
                current.append(("table", "\n".join(lines[i:tbl_end])))
                i = tbl_end
                continue
            pending_text.append(line)
            i += 1
        _flush_text()
        if current:
            sections.append(current)
        if not sections:
            return [[]] if not text.strip() else [[("text", text)]]
        return sections


def merge_within_section(texts: list[str], min_size: int) -> list[str]:
    """章节内正文碎块贪心合并（≤min_size 的块并入前一块），不跨章节。

    与 merge_small_chunks（按 page 全局合并）不同：章节是锚点语义边界，
    跨章节合并会让一块带两个 section_slot，扩展指针歧义。
    """
    if min_size <= 0:
        return texts
    merged: list[str] = []
    for t in texts:
        if merged and len(merged[-1]) < min_size:
            merged[-1] = merged[-1] + "\n" + t
        else:
            merged.append(t)
    return merged
