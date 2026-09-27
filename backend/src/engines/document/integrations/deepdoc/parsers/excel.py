"""DeepDoc Excel 解析器。"""
from __future__ import annotations

import logging
import re
from io import BytesIO

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
            return load_workbook(file_like_object, data_only=True)
        except Exception as exc:
            logging.info("openpyxl load failed, trying pandas fallback: %s", exc)
            file_like_object.seek(0)
            try:
                dfs = pd.read_excel(file_like_object, sheet_name=None)
            except Exception:
                file_like_object.seek(0)
                dfs = pd.read_excel(file_like_object, engine="calamine")
            return RAGFlowExcelParser._dataframe_to_workbook(dfs)

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

    def html(self, fnm, chunk_rows=256):
        """工作表转 HTML 表格文本，按 chunk_rows 行分块。
        
        Args:
            fnm: 文件路径或字节流。
            chunk_rows: 每块包含的数据行数。
        
        Returns:
            HTML 表格字符串列表，每块带工作表名 caption。
        """
        from html import escape

        file_like_object = BytesIO(fnm) if not isinstance(fnm, str) else fnm
        wb = RAGFlowExcelParser._load_excel_to_workbook(file_like_object)
        tb_chunks = []

        def fmt(value):
            """单元格值转文本（None 转空串）。"""
            if value is None:
                return ""
            return str(value).strip()

        for sheetname in wb.sheetnames:
            ws = wb[sheetname]
            try:
                rows = RAGFlowExcelParser._get_rows_limited(ws)
            except Exception:
                logger.warning("Skip sheet '%s' due to rows access error", sheetname, exc_info=True)
                continue
            if not rows:
                continue

            header_row = "<tr>" + "".join(f"<th>{escape(fmt(cell.value))}</th>" for cell in list(rows[0])) + "</tr>"
            n_data_rows = len(rows) - 1
            for chunk_i in range((n_data_rows + chunk_rows - 1) // chunk_rows):
                table_html = f"<table><caption>{sheetname}</caption>{header_row}"
                for row in list(rows[1 + chunk_i * chunk_rows : min(1 + (chunk_i + 1) * chunk_rows, len(rows))]):
                    table_html += "<tr>"
                    for cell in row:
                        table_html += f"<td>{escape(fmt(cell.value))}</td>" if cell.value is not None else "<td></td>"
                    table_html += "</tr>"
                table_html += "</table>\n"
                tb_chunks.append(table_html)
        return tb_chunks

    def __call__(self, fnm):
        """解析 Excel 为「表头：值；……」行文本列表（sheet 名作后缀）。"""
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
            header = list(rows[0])
            for row in list(rows[1:]):
                fields = []
                for idx, cell in enumerate(row):
                    if cell.value is None or str(cell.value).strip() == "":
                        continue
                    title = str(header[idx].value) if idx < len(header) else ""
                    prefix = f"{title}：" if title else ""
                    fields.append(prefix + str(cell.value))
                if not fields:
                    continue
                line = "; ".join(fields)
                if "sheet" not in sheetname.lower():
                    line += f" —— {sheetname}"
                rows_out.append(line)
        return rows_out
