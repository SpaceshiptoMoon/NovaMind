"""DeepDoc Excel 解析器。"""
from __future__ import annotations

import datetime
import logging
import re
from io import BytesIO
from pathlib import Path

import pandas as pd

# Adapted from RAGFlow deepdoc/parser/excel_parser.py

ILLEGAL_CHARACTERS_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")

logger = logging.getLogger(__name__)


class RAGFlowExcelParser:
    """RAGFlow Excel 解析器：工作表逐行转 Markdown 行文本。"""
    @staticmethod
    def _import_openpyxl():
        """懒加载 openpyxl。"""
        from openpyxl import Workbook, load_workbook

        return Workbook, load_workbook

    @staticmethod
    def _load_excel_to_workbook(file_like_object):
        """从路径/字节流加载为工作簿；非 Excel 载荷走 CSV 兜底。
        
        先按文件头魔数判断（zip 的 PK 头 / OLE 旧格式头），非 Excel 载荷用 pandas
        读 CSV；openpyxl 加载失败再降级 pandas（calamine 引擎兜底），统一包成工作簿。
        """
        _, load_workbook = RAGFlowExcelParser._import_openpyxl()
        # 路径形态先读入内存（真机实测：runtime_parser 传 Path 的 str 形态时
        # 无条件 seek(0) 崩溃——str 被当路径却从未打开），再统一包成字节流
        if isinstance(file_like_object, (str, Path)):
            file_like_object = Path(file_like_object).read_bytes()
        if isinstance(file_like_object, bytes):
            file_like_object = BytesIO(file_like_object)
        file_like_object.seek(0)
        file_head = file_like_object.read(4)
        file_like_object.seek(0)

        if not (file_head.startswith(b"PK\x03\x04") or file_head.startswith(b"\xd0\xcf\x11\xe0")):
            logging.info("DeepDoc excel parser received non-Excel payload; attempting CSV fallback")
            df = pd.read_csv(file_like_object, on_bad_lines="skip")
            return RAGFlowExcelParser._dataframe_to_workbook(df)

        try:
            wb = load_workbook(file_like_object, data_only=True)
        except Exception as exc:
            logging.info("openpyxl load failed, trying pandas fallback: %s", exc)
            file_like_object.seek(0)
            try:
                dfs = pd.read_excel(file_like_object, sheet_name=None)
            except Exception:
                file_like_object.seek(0)
                dfs = pd.read_excel(file_like_object, engine="calamine")
            return RAGFlowExcelParser._dataframe_to_workbook(dfs)
        RAGFlowExcelParser._expand_merged_cells(wb)
        RAGFlowExcelParser._backfill_formula_values(wb, file_like_object)
        return wb

    @staticmethod
    def _expand_merged_cells(wb):
        """合并单元格值展开：左上角值填充整个合并区域。

        openpyxl 里合并区域只有左上格有值、其余为 None——行遍历与 HTML 输出
        中合并维度会变成空串（如「华东区」合并 3 行，第 2/3 行区域列为空），
        行级语义断裂。展开后每行都携带区域值（代价是值在多行重复，属检索
        友好的冗余而非错误）。
        """
        for ws in wb.worksheets:
            merged_ranges = list(ws.merged_cells.ranges)
            if not merged_ranges:
                continue
            for rng in merged_ranges:
                top_left = ws.cell(row=rng.min_row, column=rng.min_col).value
                ws.unmerge_cells(str(rng))
                if top_left is None:
                    continue
                for row in range(rng.min_row, rng.max_row + 1):
                    for col in range(rng.min_col, rng.max_col + 1):
                        ws.cell(row=row, column=col).value = top_left

    @staticmethod
    def _backfill_formula_values(wb, file_like_object, size_limit_mb: int = 20):
        """公式无缓存值回填：data_only 视角为 None 且公式视图有值的格填公式字面量。

        程序生成的 xlsx（openpyxl/pandas 写出）只有公式没有缓存值，
        data_only=True 视角这些格为 None——检索产物丢值（常见于部分格是
        公式的常规报表，不限于整表公式）。以 data_only=False 二次加载，
        把公式字符串（如 =SUM(A1:A2)）当字面内容填回：诚实暴露公式而非
        静默丢值。文件超限不二次加载（内存防护）。
        """
        try:
            file_like_object.seek(0)
            head = file_like_object.read(4)
            file_like_object.seek(0)
        except Exception:
            return
        if not head.startswith(b"PK\x03\x04"):
            return  # CSV 兜底产物没有公式概念
        try:
            file_size = file_like_object.getbuffer().nbytes
        except AttributeError:
            return
        if file_size > size_limit_mb * 1024 * 1024:
            logging.info(
                "Excel formula backfill skipped: workbook too large (%d bytes)", file_size
            )
            return
        _, load_workbook = RAGFlowExcelParser._import_openpyxl()
        try:
            formula_wb = load_workbook(file_like_object, data_only=False)
        except Exception as exc:
            logging.info("Formula-view reload failed: %s", exc)
            return
        backfilled = 0
        for sheet_offset, ws in enumerate(wb.worksheets):
            formula_ws = formula_wb.worksheets[sheet_offset]
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is not None:
                        continue
                    formula_cell = formula_ws.cell(row=cell.row, column=cell.column)
                    if formula_cell.value is not None and str(formula_cell.value).strip():
                        cell.value = formula_cell.value
                        backfilled += 1
        if backfilled:
            logging.info("Excel formula backfill: %d cells", backfilled)

    @staticmethod
    def format_cell_value(value):
        """单元格值转展示文本：去浮点整尾、日期去零点时间、控制字符剔除。

        str(value) 的默认形态带检索噪音：1.0 显示「1.0」、日期显示
        「2024-01-01 00:00:00」——对 BM25 与阅读都是噪音。
        """
        if value is None:
            return ""
        if isinstance(value, bool):
            return "是" if value else "否"
        if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        if isinstance(value, datetime.datetime) and (
            value.hour == 0 and value.minute == 0 and value.second == 0
        ):
            return value.date().isoformat()
        if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
            return str(value)
        if isinstance(value, str):
            return ILLEGAL_CHARACTERS_RE.sub(" ", value).strip()
        return str(value)

    @staticmethod
    def _clean_dataframe(df: pd.DataFrame):
        """清理数据帧：剔除控制字符。"""
        def clean_string(value):
            """剔除单元格文本中的控制字符。"""
            if isinstance(value, str):
                return ILLEGAL_CHARACTERS_RE.sub(" ", value)
            return value

        return df.apply(lambda col: col.map(clean_string))

    @staticmethod
    def _fill_worksheet_from_dataframe(ws, df: pd.DataFrame):
        """把数据帧首行当表头、逐单元格写入工作表（pandas 兜底路径复用）。"""
        for col_num, column_name in enumerate(df.columns, 1):
            ws.cell(row=1, column=col_num, value=column_name)
        for row_num, row in enumerate(df.values, 2):
            for col_num, value in enumerate(row, 1):
                ws.cell(row=row_num, column=col_num, value=value)

    @staticmethod
    def _dataframe_to_workbook(df):
        """数据帧（或多表字典）包成工作簿，供统一的行遍历路径消费。"""
        Workbook, _ = RAGFlowExcelParser._import_openpyxl()
        if isinstance(df, dict) and len(df) > 1:
            return RAGFlowExcelParser._dataframes_to_workbook(df)

        df = RAGFlowExcelParser._clean_dataframe(df)
        wb = Workbook()
        ws = wb.active
        ws.title = "Data"
        RAGFlowExcelParser._fill_worksheet_from_dataframe(ws, df)
        return wb

    @staticmethod
    def _dataframes_to_workbook(dfs: dict):
        """多数据帧合并为一个多表工作簿。"""
        Workbook, _ = RAGFlowExcelParser._import_openpyxl()
        wb = Workbook()
        default_sheet = wb.active
        wb.remove(default_sheet)

        for sheet_name, df in dfs.items():
            df = RAGFlowExcelParser._clean_dataframe(df)
            ws = wb.create_sheet(title=sheet_name)
            RAGFlowExcelParser._fill_worksheet_from_dataframe(ws, df)
        return wb

    @staticmethod
    def _get_actual_row_count(ws):
        """探测工作表实际数据行数。
        
        openpyxl 的 max_row 常含样式残留的虚增行；超大表先抽样确认有数据，
        再二分定位最后的数据行，尾段线性扫描收边。
        """
        max_row = ws.max_row
        if not max_row:
            return 0
        if max_row <= 10000:
            return max_row

        max_col = min(ws.max_column or 1, 50)

        def row_has_data(row_idx):
            """该行前 50 列是否存在非空单元格（虚增行探测）。"""
            for col_idx in range(1, max_col + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                if cell.value is not None and str(cell.value).strip():
                    return True
            return False

        if not any(row_has_data(i) for i in range(1, min(101, max_row + 1))):
            return 0

        left, right = 1, max_row
        last_data_row = 1
        while left <= right:
            mid = (left + right) // 2
            found = False
            for row_idx in range(mid, min(mid + 10, max_row + 1)):
                if row_has_data(row_idx):
                    found = True
                    last_data_row = max(last_data_row, row_idx)
                    break
            if found:
                left = mid + 1
            else:
                right = mid - 1

        for row_idx in range(last_data_row, min(last_data_row + 500, max_row + 1)):
            if row_has_data(row_idx):
                last_data_row = row_idx
        return last_data_row

    @staticmethod
    def _get_rows_limited(ws):
        """读取工作表实际数据范围内的行对象列表。"""
        actual_rows = RAGFlowExcelParser._get_actual_row_count(ws)
        if actual_rows == 0:
            return []
        return list(ws.iter_rows(min_row=1, max_row=actual_rows))

    _NUMERIC_LIKE_RE = re.compile(r"^-?[$￥€]?\d[\d,，]*\.?\d*%?$")

    @classmethod
    def _detect_header_rows(cls, rows) -> int:
        """探测表头行数（支持多级复合表头，最多向下看 3 行）。

        表头行的特征：非空格占比高且数值型格占比低（≤30%）；遇到数值主导行
        即停。首行就数值主导（占比 >70%）判为无表头表，返回 0——此时首行
        按数据行输出，表头用列字母占位，不再错把数据行当表头丢弃语义。
        """
        checked = 0
        header_rows = 0
        for row in list(rows)[:3]:
            values = [RAGFlowExcelParser.format_cell_value(c.value) for c in row]
            non_empty = [v for v in values if v]
            if len(non_empty) < 2:
                break
            numeric = [v for v in non_empty if cls._NUMERIC_LIKE_RE.match(v)]
            numeric_ratio = len(numeric) / len(non_empty)
            if checked == 0 and numeric_ratio > 0.7:
                return 0  # 无表头表
            if numeric_ratio > 0.3:
                break
            header_rows += 1
            checked += 1
        return header_rows or 1

    @classmethod
    def _build_composite_headers(cls, rows, header_rows: int) -> list[str]:
        """把前 header_rows 行拼成每列单一复合表头（「Q1 > 收入」形态）。

        合并单元格展开会让组头值在同行横向重复（Q1 填满其下所有列）——
        纵向拼接时跳过与前一段相同的值，得到「组头 > 子头」。全列无值时
        用列字母占位。
        """
        # 物化为 list：openpyxl 的 _Row 代理可迭代但无 len()
        header_block = [list(row) for row in rows[:header_rows]]
        if header_rows <= 0 or not header_block:
            first = list(rows[0]) if rows else []
            return [cls._column_letter(i) for i in range(len(first))]
        width = max(len(row) for row in header_block)
        headers: list[str] = []
        for col in range(width):
            pieces: list[str] = []
            for row in header_block:
                value = cls.format_cell_value(row[col].value) if col < len(row) else ""
                if value and value not in pieces:
                    pieces.append(value)
            headers.append(" > ".join(pieces) if pieces else cls._column_letter(col))
        return headers

    @staticmethod
    def _column_letter(index: int) -> str:
        """0-based 列序号转 Excel 列字母（0→A，25→Z，26→AA）。"""
        letters = ""
        index += 1
        while index:
            index, rem = divmod(index - 1, 26)
            letters = chr(ord("A") + rem) + letters
        return letters

    def html(self, fnm, chunk_rows=256):
        """工作表转 HTML 表格文本，按 chunk_rows 行分块（多级表头折成复合表头）。

        Args:
            fnm: 文件路径或字节流。
            chunk_rows: 每块包含的数据行数。

        Returns:
            HTML 表格字符串列表，每块带工作表名 caption。
        """
        blocks, _images = self.parse_blocks(fnm, chunk_rows=chunk_rows)
        return blocks

    def parse_blocks(self, fnm, chunk_rows=256):
        """工作表转 HTML 块 + 提取嵌入图片（runtime 主入口，一次加载）。

        Args:
            fnm: 文件路径或字节流。
            chunk_rows: 每块包含的数据行数。

        Returns:
            (blocks, images) 二元组：blocks 为 HTML 表格字符串列表（每块带
            工作表名 caption，多级表头折成单行复合表头）；images 为嵌入图片
            字典列表（sheet/row/col/blob，png 化重编码，不可解码图跳过）。
        """
        from html import escape

        file_like_object = BytesIO(fnm) if not isinstance(fnm, str) else fnm
        wb = RAGFlowExcelParser._load_excel_to_workbook(file_like_object)
        tb_chunks: list[str] = []
        images: list[dict] = []

        def fmt_text(value):
            """单元格值转展示文本（数值/日期规范化，见 format_cell_value）。"""
            return RAGFlowExcelParser.format_cell_value(value)

        def cell_html(value):
            """单元格转 HTML：换行转 <br/>，None 转空格。"""
            if value is None:
                return "<td></td>"
            return f"<td>{escape(fmt_text(value)).replace(chr(10), '<br/>')}</td>"

        for sheet_index, sheetname in enumerate(wb.sheetnames):
            ws = wb[sheetname]
            try:
                rows = RAGFlowExcelParser._get_rows_limited(ws)
            except Exception:
                logger.warning("Skip sheet '%s' due to rows access error", sheetname, exc_info=True)
                continue

            sheet_images = RAGFlowExcelParser._extract_sheet_images(ws, sheetname)
            # artifact_id 在此定版（占位符与 figure_regions 必须同一 id）
            for order, image_info in enumerate(sheet_images):
                location = (
                    f"r{image_info['row'] + 1}c{image_info['col'] + 1}"
                    if image_info["row"] is not None and image_info["col"] is not None
                    else f"pos{order}"
                )
                image_info["artifact_id"] = (
                    f"xls_s{sheet_index}_{location}_{order}"
                )
            if not rows:
                images.extend(sheet_images)
                continue

            header_rows = RAGFlowExcelParser._detect_header_rows(rows)
            headers = RAGFlowExcelParser._build_composite_headers(rows, header_rows)
            header_row = "<tr>" + "".join(f"<th>{escape(h)}</th>" for h in headers) + "</tr>"
            n_data_rows = len(rows) - header_rows
            sheet_chunks: list[str] = []
            for chunk_i in range((n_data_rows + chunk_rows - 1) // chunk_rows):
                table_html = f"<table><caption>{sheetname}</caption>{header_row}"
                start = header_rows + chunk_i * chunk_rows
                for row in list(rows[start : min(start + chunk_rows, len(rows))]):
                    table_html += "<tr>" + "".join(cell_html(c.value) for c in row) + "</tr>"
                table_html += "</table>\n"
                sheet_chunks.append(table_html)
            # 嵌入图片：占位符挂在本表首块（精确到格位的行内插入对分块漂移
            # 太脆弱；挂首块保证图片随表入库，宿主上传后替换为短路径）
            if sheet_images and sheet_chunks:
                for image_info in sheet_images:
                    placeholder = f"__FIGURE_URL__{image_info['artifact_id']}__"
                    sheet_chunks[0] = placeholder + "\n" + sheet_chunks[0]
            images.extend(sheet_images)
            tb_chunks.extend(sheet_chunks)
        return tb_chunks, images

    @staticmethod
    def _extract_sheet_images(ws, sheetname: str) -> list[dict]:
        """提取工作表嵌入图片：png 化重编码（统一 figure 管线格式）。

        EMF/WMF 等 Windows 元文件 Pillow 不可解码，跳过并告警（诚实暴露
        而非产出坏图）。
        """
        from io import BytesIO

        from PIL import Image as PILImage

        out: list[dict] = []
        for order, img in enumerate(getattr(ws, "_images", []) or []):
            try:
                data = img._data()
            except Exception:
                logger.warning(
                    "Skip unreadable embedded image in sheet '%s' (order %d)",
                    sheetname, order, exc_info=True,
                )
                continue
            if not data:
                continue
            row = col = None
            anchor = getattr(img, "anchor", None)
            marker = getattr(anchor, "_from", None)
            if marker is not None:
                row = int(getattr(marker, "row", 0))
                col = int(getattr(marker, "col", 0))
            try:
                pil = PILImage.open(BytesIO(data))
                pil.load()
                if pil.mode not in ("RGB", "RGBA", "L"):
                    pil = pil.convert("RGBA")
                buf = BytesIO()
                pil.save(buf, format="PNG")
                png_bytes = buf.getvalue()
            except Exception:
                logger.warning(
                    "Skip undecodable embedded image in sheet '%s' (order %d, "
                    "likely EMF/WMF)", sheetname, order, exc_info=True,
                )
                continue
            out.append({
                "sheet": sheetname,
                "row": row,
                "col": col,
                "blob": png_bytes,
                # artifact_id 由 runtime_parser 组装（需 sheet 序号，此处不含）
            })
        return out

    def __call__(self, fnm):
        """解析 Excel 为「复合表头：值；……」行文本列表（sheet 名作后缀）。

        与 html 出口同源的多级表头处理：前 N 表头行纵向折成复合表头，
        数据行从表头块之后开始；无表头表用列字母做前缀。
        """
        file_like_object = BytesIO(fnm) if not isinstance(fnm, str) else fnm
        wb = RAGFlowExcelParser._load_excel_to_workbook(file_like_object)

        rows_out = []
        for sheetname in wb.sheetnames:
            ws = wb[sheetname]
            try:
                rows = RAGFlowExcelParser._get_rows_limited(ws)
            except Exception:
                logger.warning("Skip sheet '%s' due to rows access error", sheetname, exc_info=True)
                continue
            if not rows:
                continue
            header_rows = RAGFlowExcelParser._detect_header_rows(rows)
            headers = RAGFlowExcelParser._build_composite_headers(rows, header_rows)
            for row in list(rows[header_rows:]):
                fields = []
                for idx, cell in enumerate(row):
                    value_text = RAGFlowExcelParser.format_cell_value(cell.value)
                    if not value_text:
                        continue
                    title = headers[idx] if idx < len(headers) else ""
                    prefix = f"{title}：" if title else ""
                    fields.append(prefix + value_text)
                if not fields:
                    continue
                line = "; ".join(fields)
                if "sheet" not in sheetname.lower():
                    line += f" —— {sheetname}"
                rows_out.append(line)
        return rows_out
