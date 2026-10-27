"""DeepDoc PPT 解析器。"""
from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

from novamind.engines.document.exceptions import (
    EncryptedDocumentError,
    MismatchedPayloadError,
)
from novamind.engines.document.integrations.deepdoc.compat import guard_office_zip

# Adapted from RAGFlow deepdoc/parser/ppt_parser.py

# OLE 复合文档魔数（旧版 .ppt 与 OOXML 加密容器共用此头）
_OLE_HEADER_MAGIC = b"\xd0\xcf\x11\xe0"


class RAGFlowPptParser:
    """RAGFlow PPT 解析器：形状遍历抽取文本与表格。"""
    def __init__(self):
        """初始化形状排序缓存。"""
        self._shape_cache = {}

    @staticmethod
    def _import_presentation():
        """懒加载 python-pptx。"""
        from pptx import Presentation

        return Presentation

    def _sort_shapes(self, shapes):
        """按阅读序排序形状：top 按 10pt 桶分带，再按 left 从左到右。
        
        同页形状集合按对象 id 缓存，避免组内递归重复排序。
        """
        # 红队 P2：id(shapes) 做键——代理对象 GC 后 id 复用会命中陈旧排序。
        # 绑定形状数量 + 首个形状 id 的组合键（同页形状组稳定）。
        cache_key = (len(shapes), id(shapes[0]) if shapes else 0)
        if cache_key not in self._shape_cache:
            self._shape_cache[cache_key] = sorted(
                shapes,
                key=lambda shape: (
                    (shape.top if shape.top is not None else 0) // 10,
                    shape.left if shape.left is not None else 0,
                ),
            )
        return self._shape_cache[cache_key]

    @staticmethod
    def _get_bulleted_text(paragraph):
        """拼接段落文本，项目符号段落按层级缩进并加"·"前缀。"""
        is_bulleted = (
            bool(paragraph._p.xpath("./a:pPr/a:buChar"))
            or bool(paragraph._p.xpath("./a:pPr/a:buAutoNum"))
            or bool(paragraph._p.xpath("./a:pPr/a:buBlip"))
        )
        return f"{'  ' * paragraph.level}.{paragraph.text}" if is_bulleted else paragraph.text

    def _extract(self, shape):
        """抽取单个形状文本：文本框直取，图表/表格转数据行，组合形状递归。

        处理异常时记日志并返回空串，不让单个坏形状中断整页解析。
        """
        try:
            if hasattr(shape, "has_text_frame") and shape.has_text_frame:
                text_frame = shape.text_frame
                texts = []
                for paragraph in text_frame.paragraphs:
                    if paragraph.text.strip():
                        texts.append(self._get_bulleted_text(paragraph))
                return "\n".join(texts)

            # 原生图表（GraphicFrame.chart）：系列数据存独立 chart part，
            # python-pptx 不当文本暴露，默认整图静默丢失——按 docx 同款
            # 「系列名: 类别=值」格式重组缓存数据
            if getattr(shape, "has_chart", False):
                chart_text = self._chart_to_text(shape.chart)
                if chart_text:
                    return chart_text

            try:
                shape_type = shape.shape_type
            except NotImplementedError:
                return shape.text.strip() if hasattr(shape, "text") else ""

            if shape_type == 19:
                table = shape.table
                rows = []
                for row_idx in range(1, len(table.rows)):
                    rows.append(
                        "; ".join(
                            f"{table.cell(0, col_idx).text}: {table.cell(row_idx, col_idx).text}"
                            for col_idx in range(len(table.columns))
                            if table.cell(row_idx, col_idx)
                        )
                    )
                return "\n".join(rows)

            if shape_type == 6:
                texts = []
                for child_shape in self._sort_shapes(shape.shapes):
                    text = self._extract(child_shape)
                    if text:
                        texts.append(text)
                return "\n".join(texts)

            return ""
        except Exception as exc:
            logging.error("Error processing PPT shape: %s", exc)
            return ""

    @staticmethod
    def _chart_to_text(chart) -> str:
        """图表对象重组为「[图表《标题》] 系列: 类别=值; ...」文本。

        类别与值按下标对齐（python-pptx 已按缓存点对齐序列）；无类别的系列
        只输出值。图表无数据系列时返回空串。
        """
        try:
            title = ""
            if chart.has_title:
                title = chart.chart_title.text_frame.text.strip()
            series_lines: list[str] = []
            for plot in chart.plots:
                categories = [str(c) for c in (plot.categories or [])]
                for series in plot.series:
                    name = str(series.name or "").strip() if series.name else ""
                    values = [v for v in (series.values or []) if v is not None]
                    if not values:
                        continue
                    points = [
                        f"{categories[idx]}={value}" if idx < len(categories) else str(value)
                        for idx, value in enumerate(values)
                    ]
                    series_lines.append(
                        f"{name}: " + "; ".join(points) if name else "; ".join(points)
                    )
            if not series_lines:
                return ""
            prefix = f"[图表《{title}》] " if title else "[图表] "
            return prefix + " ｜ ".join(series_lines)
        except Exception as exc:
            logging.warning("PPT chart extraction failed: %s", exc)
            return ""

    def __call__(self, fnm, from_page=0, to_page=None, callback=None):
        """解析 PPT 为每页合并文本列表。

        Args:
            fnm: 文件路径或字节流。
            from_page: 起始页（slide 下标，0 起）。
            to_page: 结束页（不含），None 表示到末页。
            callback: 兼容参数（进度回调），未使用。

        Returns:
            每页文本（页内形状按阅读序拼接，演讲者备注以「[备注]」前缀
            附在页尾）的列表；实例属性 total_page 记录总页数。

        Raises:
            MismatchedPayloadError: 内容不是 OOXML 包（伪扩展名/损坏）。
            EncryptedDocumentError: OLE 头载荷（加密容器或旧版 .ppt）。
        """
        payload = Path(fnm).read_bytes() if isinstance(fnm, str) else fnm
        if not payload.startswith(b"PK\x03\x04"):
            if payload.startswith(_OLE_HEADER_MAGIC):
                raise EncryptedDocumentError(
                    "ppt 文档已加密（打开密码或敏感度标签），或为旧版二进制 .ppt 格式，"
                    "请解密或另存为 .pptx 后上传",
                    format_name="pptx",
                )
            raise MismatchedPayloadError(
                "pptx 内容不是 OOXML 包（可能是旧版 .ppt 改名或文件损坏）",
                format_name="pptx",
            )
        guard_office_zip(payload, "pptx")

        Presentation = self._import_presentation()
        ppt = Presentation(BytesIO(payload))
        texts_by_slide = []
        self.total_page = len(ppt.slides)
        upper = self.total_page if to_page is None else to_page
        for slide_index, slide in enumerate(ppt.slides):
            if slide_index < from_page:
                continue
            if slide_index >= upper:
                break
            texts = []
            for shape in self._sort_shapes(slide.shapes):
                text = self._extract(shape)
                if text:
                    texts.append(text)
            # 演讲者备注：内容在独立 notes part，形状遍历覆盖不到；空备注
            # 页（占位符未填写）has_notes_slide 为 False 自然跳过
            if getattr(slide, "has_notes_slide", False):
                notes_text = slide.notes_slide.notes_text_frame.text.strip()
                if notes_text:
                    texts.append(f"[备注] {notes_text}")
            texts_by_slide.append("\n".join(texts))
        return texts_by_slide
