"""Excel 版面语义层：值网格构建、多岛分割、前置区与表头识别。

把 openpyxl 工作表转成与库解耦的值网格（SheetGrid），按空白投影连通域切分
多岛（一个 sheet 多张表的场景），逐岛识别前置标题区与表头 band。算法来源：
投影连通域与缝合后处理对齐 knowledgestack/excel-parser 的 segmenter，anchor
contrast/styled 信号与体类型签名刹车对齐其 header_detector；合并展开与复合
表头合成为 NovaMind 自有层。纯函数、不依赖 openpyxl 类型，便于夹具直测。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_NUMERIC_LIKE_RE = re.compile(r"^-?[$￥€]?\d[\d,，]*\.?\d*%?$")
_DATE_RE = re.compile(r"^\d{4}-\d{1,2}(-\d{1,2})?$")
# 单格换行/文本批注上限（防超长批注淹没单元格文本）
_NOTE_MAX_CHARS = 300
# 表头 band 上限（ SpreadsheetLLM/表格惯例：多级表头很少超过 3 行，留余量）
MAX_HEADER_BAND = 6
# 表头锚点向下扫描窗口
_HEADER_SCAN_ROWS = 6


def _is_numeric_like(text: str) -> bool:
    """文本是否数值形态（含千分位/货币符号/百分号）。"""
    return bool(_NUMERIC_LIKE_RE.match(text))


def _type_sig(text: str) -> str:
    """单元格文本类型签名：n 数值 / d 日期 / s 文本 / '' 空（体签名刹车用）。"""
    if not text:
        return ""
    if _is_numeric_like(text):
        return "n"
    if _DATE_RE.match(text):
        return "d"
    return "s"


def _column_letter(index: int) -> str:
    """0-based 列序号转 Excel 列字母（0→A，25→Z，26→AA）。"""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


@dataclass
class SheetGrid:
    """工作表值网格（0-based 行列；值为展示文本，含批注与合并展开后的结果）。"""

    sheet_name: str
    values: dict[tuple[int, int], str]
    comments: dict[tuple[int, int], str]
    merged_ranges: list[tuple[int, int, int, int]]  # (min_row, min_col, max_row, max_col) 1-based 闭区间
    # 行分组大纲（作者用「组合」功能折叠的层级，≥1 即分组行）
    outline_levels: dict[int, int] = field(default_factory=dict)

    @property
    def n_rows(self) -> int:
        return (max((r for r, _c in self.values), default=-1)) + 1

    @property
    def n_cols(self) -> int:
        return (max((c for _r, c in self.values), default=-1)) + 1

    def text_at(self, row: int, col: int) -> str:
        return self.values.get((row, col), "")


@dataclass
class Island:
    """一个连通数据岛（0-based 闭区间行列范围）。"""

    top: int
    bottom: int
    left: int
    right: int
    preamble: list[str] = field(default_factory=list)  # 前置标题/KV 文本行
    header_top: int | None = None  # 表头 band 首行；None = 无表头（数据直接开始）
    header_rows: int = 0
    headers: list[str] = field(default_factory=list)  # 复合表头（列字母兜底）
    data_top: int = 0  # 数据首行
    has_header: bool = False

    @property
    def width(self) -> int:
        return self.right - self.left + 1

    def col_overlap(self, other: Island) -> float:
        """列区间重叠率（相对较窄一方），缝合判定用。"""
        inter_left = max(self.left, other.left)
        inter_right = min(self.right, other.right)
        inter = max(0, inter_right - inter_left + 1)
        narrower = min(self.width, other.width)
        return inter / narrower if narrower else 0.0

    def absorb(self, other: Island) -> None:
        """缝合下方延续岛：行区间并、列区间并，数据行范围扩展。"""
        self.bottom = max(self.bottom, other.bottom)
        self.left = min(self.left, other.left)
        self.right = max(self.right, other.right)
        self.preamble.extend(other.preamble)


def build_grid(ws, format_value) -> SheetGrid:
    """从 openpyxl 工作表构建值网格。

    优先走 ``ws._cells`` 字典（稀疏表避免为海量空格物化单元格，openpyxl 3.x
    稳定私有形态），缺失时回落 iter_rows。批注随格收集；合并区优先读展开
    前快照（``ws._novamind_merged_pre``，宿主展开时回写），否则读现存合并
    区（未展开路径）。行分组大纲（outlineLevel）随行收集。
    """
    values: dict[tuple[int, int], str] = {}
    comments: dict[tuple[int, int], str] = {}
    cells = getattr(ws, "_cells", None)
    if cells is not None:
        items = ((coord, cell) for coord, cell in cells.items())
    else:
        def _iter():
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is not None:
                        yield (cell.row, cell.column), cell
        items = _iter()
    for (row, col), cell in items:
        text = format_value(getattr(cell, "value", None))
        if text:
            values[(row - 1, col - 1)] = text
        comment = getattr(cell, "comment", None)
        if comment is not None:
            note = " ".join(str(comment.text or "").split())
            if note:
                note = note[:_NOTE_MAX_CHARS]
                author = str(getattr(comment, "author", "") or "批注")
                comments[(row - 1, col - 1)] = f"[note({author}): {note}]"
    merged = getattr(ws, "_novamind_merged_pre", None)
    if merged is None:
        # read_only 流式工作簿没有 merged_cells 属性（合并区不保留），按无
        # 合并处理——降级语义：合并区仅锚点格有值
        merged = [
            (rng.min_row, rng.min_col, rng.max_row, rng.max_col)
            for rng in (getattr(getattr(ws, "merged_cells", None), "ranges", None) or [])
        ]
    outline_levels = {
        int(row_index) - 1: int(dim.outline_level or 0)
        for row_index, dim in getattr(ws, "row_dimensions", {}).items()
        if getattr(dim, "outline_level", 0)
    }
    return SheetGrid(
        sheet_name=str(getattr(ws, "title", "") or ""),
        values=values,
        comments=comments,
        merged_ranges=merged,
        outline_levels=outline_levels,
    )


def _row_texts(grid: SheetGrid, row: int, left: int, right: int) -> list[str]:
    return [grid.text_at(row, c) for c in range(left, right + 1)]


def _numeric_ratio(texts: list[str]) -> float:
    non_empty = [t for t in texts if t]
    if not non_empty:
        return 0.0
    return sum(1 for t in non_empty if _is_numeric_like(t)) / len(non_empty)


def _contrast_cols(grid: SheetGrid, row: int, left: int, right: int, data_top: int) -> int:
    """contrast 列数：本行是文本标签、下方该列主体（≥60%）是数据。

    表头反向保护用（有 contrast 列的行永不判前置区）；数值占比阈值放宽到
    0.6——公式字面量、偶发文本格不应灭掉整列的数据性。
    """
    body_rows = list(range(data_top, min(data_top + 8, grid.n_rows)))
    contrast = 0
    for col in range(left, right + 1):
        label = grid.text_at(row, col)
        if not label or _is_numeric_like(label):
            continue
        body_values = [grid.text_at(r, col) for r in body_rows]
        body_non_empty = [v for v in body_values if v]
        if not body_non_empty:
            continue
        data_ratio = sum(
            1 for v in body_non_empty if _type_sig(v) in ("n", "d")
        ) / len(body_non_empty)
        if data_ratio >= 0.6:
            contrast += 1
    return contrast


def _is_preamble_row(grid: SheetGrid, row: int, left: int, right: int) -> str | None:
    """前置区行判定，返回形态标记；不是前置区返回 None。

    三信号（对齐 excel-parser `_is_title_or_preamble`）：banner 横合并行 /
    "Label: value" KV 行 / 稀疏样式行。反向保护：≥2 个 contrast 列的行是
    表头，永不判为前置区。
    """
    texts = _row_texts(grid, row, left, right)
    non_empty = [t for t in texts if t]
    if not non_empty:
        return None
    if _contrast_cols(grid, row, left, right, row + 1) >= 2:
        return None
    width = right - left + 1
    # banner：单格横向合并且跨度 >50% 表宽
    for min_row, min_col, max_row, max_col in grid.merged_ranges:
        if min_row - 1 == row and min_col - 1 <= left <= right <= max_col - 1:
            if (max_col - min_col + 1) > width * 0.5:
                return "banner"
    # KV 行：覆盖率 <50% 且单格以冒号结尾，或「标签格+值格」两格形态
    coverage = len(non_empty) / width
    if coverage < 0.5:
        if len(non_empty) == 1 and re.search(r"[：:]$", non_empty[0]):
            return "kv"
        if len(non_empty) == 2 and re.search(r"[：:]$", non_empty[0]):
            return "kv"
    # 稀疏行：单格文本
    if len(non_empty) == 1:
        return "sparse"
    return None


def detect_header(grid: SheetGrid, island: Island) -> None:
    """就地识别岛的前置区、表头 band 与数据首行。

    「headings 在哪结束、data 从哪开始」的直接解法：**数据首行 = 岛顶向下
    首个含数值形态单元格的行**（数值占比 ≥0.3，防年份标签行误判）；其上
    的非前置区行即表头 band（纵向折成复合表头）。首行即数值主导判无表头
    表（列字母占位）。纯文本表无数值行可依——回退单行表头（本身即含混
    场景，保守处理）。
    """
    top = island.top
    scanned = 0
    row = top
    band_rows: list[int] = []
    while row <= island.bottom and scanned < _HEADER_SCAN_ROWS:
        texts = _row_texts(grid, row, island.left, island.right)
        non_empty = [t for t in texts if t]
        if not non_empty:
            row += 1
            continue
        numeric_ratio = _numeric_ratio(texts)
        has_numeric = any(_is_numeric_like(t) for t in non_empty)
        if numeric_ratio > 0.7 and not band_rows:
            # 无表头表（band 未收集过）：数据直接开始（列字母占位）
            island.data_top = row
            island.headers = [
                _column_letter(c - island.left) for c in range(island.left, island.right + 1)
            ]
            island.has_header = False
            return
        if numeric_ratio >= 0.3 and has_numeric:
            # 数据首行确定：其上非前置行 = 表头 band
            island.data_top = row
            island.header_top = band_rows[0] if band_rows else None
            island.header_rows = len(band_rows)
            if band_rows:
                island.has_header = True
                island.headers = _compose_headers(grid, island, band_rows)
            else:
                island.has_header = False
                island.headers = [
                    _column_letter(c - island.left)
                    for c in range(island.left, island.right + 1)
                ]
            return
        kind = _is_preamble_row(grid, row, island.left, island.right)
        if kind:
            island.preamble.append(" ".join(non_empty))
            row += 1
            scanned += 1
            continue
        band_rows.append(row)
        if len(band_rows) >= MAX_HEADER_BAND:
            # band 顶格仍未见数据行：全文本表——按首行表头保守回退
            island.data_top = band_rows[0]
            island.header_rows = 1
            island.has_header = True
            island.headers = _compose_headers(grid, island, band_rows[:1])
            return
        row += 1
        scanned += 1
    # 扫描耗尽（纯文本岛）：按首行表头保守回退
    island.data_top = top
    island.header_rows = 1
    island.has_header = True
    island.headers = _compose_headers(grid, island, [top])


def _compose_headers(grid: SheetGrid, island: Island, band_rows: list[int]) -> list[str]:
    """band 行纵向折成每列单一复合表头（「Q1 > 收入」）；空列用列字母兜底。

    合并展开会让组头值横向重复——纵向拼接时去重保序，得到「组头 > 子头」。
    """
    headers: list[str] = []
    for col in range(island.left, island.right + 1):
        pieces: list[str] = []
        for r in band_rows:
            value = grid.text_at(r, col)
            if value and value not in pieces:
                pieces.append(value)
        headers.append(
            " > ".join(pieces) if pieces else _column_letter(col - island.left)
        )
    return headers


def _group_runs(sorted_positions: list[int], max_gap: int) -> list[list[int]]:
    """把有序位置按空白档分组：空白档数 < max_gap 才同组（gap=1 即任何 1 空
    行/列都切开——激进切分由 stitch 后处理兜底，对齐 excel-parser 哲学）。"""
    groups: list[list[int]] = []
    for pos in sorted_positions:
        if groups and pos - groups[-1][-1] - 1 < max_gap:
            groups[-1].append(pos)
        else:
            groups.append([pos])
    return groups


def segment_islands(grid: SheetGrid, gap_rows: int = 1, gap_cols: int = 1) -> list[Island]:
    """两阶段投影连通域分岛：行投影分组 → 组内列投影分组。

    阈值自适应（对齐 excel-parser）：整表填充率 >0.9 时行 gap 放宽到 2
    （防极密表过切）；列方向永不放宽——列分隔是可靠边界。
    """
    if not grid.values:
        return []
    occupied_rows = sorted({r for r, _c in grid.values})
    occupied_cols = sorted({c for _r, c in grid.values})
    used_rows = occupied_rows[-1] - occupied_rows[0] + 1
    used_cols = occupied_cols[-1] - occupied_cols[0] + 1
    density = len(grid.values) / max(1, used_rows * used_cols)
    effective_row_gap = 2 if (density > 0.9 and gap_rows <= 1) else gap_rows

    row_groups = _group_runs(occupied_rows, effective_row_gap)
    islands: list[Island] = []
    for group in row_groups:
        rows_set = set(group)
        group_cols = sorted({c for (r, c) in grid.values if r in rows_set})
        col_groups = _group_runs(group_cols, gap_cols)
        for col_group in col_groups:
            islands.append(Island(
                top=group[0], bottom=group[-1],
                left=col_group[0], right=col_group[-1],
            ))
    islands.sort(key=lambda i: (i.top, i.left))
    return islands


_SUBTOTAL_RE = re.compile(r"^(合计|总计|小计|累计|总和|total|subtotal)", re.IGNORECASE)
# 单位词不含空白与括号（「件」「万元」；括号是前置句的包裹符）
_UNIT_RE = re.compile(r"单位[：:]\s*([^\s（）()]{1,12})")


def is_subtotal_row(texts: list[str]) -> bool:
    """小计/总计行判定：首个非空格命中聚合词（Total/合计/小计/累计等）。

    只做打标不做剔除——用户可能就是问总计，剔除属丢数据；打标后检索层
    可降权、LLM 层可区分聚合值与明细值。
    """
    for t in texts:
        if t:
            return bool(_SUBTOTAL_RE.match(t.strip()))
    return False


def detect_transpose(grid: SheetGrid, island: Island, data_top: int) -> bool:
    """转置表判定：首行数值主导（>0.7）而首列是文本维度（行头在左）。

    满足时数据区按「首列作行表头」渲染，不再套列字母列头。
    """
    first_row = _numeric_ratio(_row_texts(grid, island.top, island.left, island.right))
    if first_row <= 0.7:
        return False
    body_rows = list(range(data_top, min(data_top + 8, island.bottom + 1)))
    first_col = [grid.text_at(r, island.left) for r in body_rows]
    non_empty = [t for t in first_col if t]
    if len(non_empty) < 2:
        return False
    text_density = sum(1 for t in non_empty if not _is_numeric_like(t)) / len(non_empty)
    return text_density >= 0.6


def section_rows(grid: SheetGrid, island: Island, data_top: int) -> dict[int, str]:
    """表内小节行：outline 分组行（Tier 1）+ 左缘横向合并行（Tier 2）。

    Excel 自带的作者意图信号，比文本启发式可靠。返回 {行号: 小节文本}，
    渲染层把小节行从数据表中拆出为独立标注行。
    """
    sections: dict[int, str] = {}
    for row in range(data_top, island.bottom + 1):
        texts = _row_texts(grid, row, island.left, island.right)
        non_empty = [t for t in texts if t]
        if not non_empty:
            continue
        label = None
        # Tier 1：行分组大纲（作者主动折叠/分组的行）
        if grid.outline_levels.get(row, 0) >= 1 and len(non_empty) <= 2:
            label = non_empty[0]
        # Tier 2：左缘横向合并行（小节标签横跨表宽的一部分，行内唯一值）
        if label is None:
            for min_row, min_col, max_row, max_col in grid.merged_ranges:
                if min_row - 1 == row and min_col - 1 <= island.left and max_col - 1 > min_col - 1:
                    if len(non_empty) <= 2:
                        label = non_empty[0]
                    break
        if label:
            sections[row] = label
    return sections


def extract_unit(preamble_lines: list[str]) -> str | None:
    """从前置文本行提取「单位：万元」形态的数值单位。"""
    for line in preamble_lines:
        m = _UNIT_RE.search(line)
        if m:
            return m.group(1)
    return None


def stitch_islands(grid: SheetGrid, islands: list[Island]) -> list[Island]:
    """缝合后处理：把被小节行/空行切断的延续岛缝回上方有表头的岛。

    条件全部满足才吸收（对齐 excel-parser `_stitch_vertical_tables`）：
    紧邻（空行 ≤1）、列重叠率 ≥0.5、自身无表头（有自己的表头 = 真正的
    新表，链终止）。前置文本行随吸收并入上方岛。
    """
    for island in islands:
        detect_header(grid, island)
    stitched: list[Island] = []
    for island in islands:
        prev = stitched[-1] if stitched else None
        if (
            prev is not None
            and prev.has_header
            and not island.has_header
            and island.top - prev.bottom <= 2
            and prev.col_overlap(island) >= 0.5
        ):
            prev.absorb(island)
            continue
        stitched.append(island)
    return stitched
