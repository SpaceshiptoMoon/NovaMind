"""DeepDoc PDF 解析器：含 OCR / 版面分析的完整 PDF 处理。"""
from __future__ import annotations

# Adapted around RAGFlow deepdoc/parser/pdf_parser.py class layout.

from dataclasses import asdict, dataclass
import gc
from io import BytesIO
from pathlib import Path
import logging
import re
from statistics import median
from typing import Any, Dict, List, Sequence, Union

import numpy as np
import pdfplumber
from PIL import Image

from novamind.engines.document.integrations.deepdoc.compat import MAXIMUM_PAGE_NUMBER
from novamind.engines.document.integrations.deepdoc.core.models import DeepDocParseResult, strip_position_tags
from novamind.engines.document.integrations.deepdoc.formula_recognition import (
    get_formula_model_status,
    load_formula_recognizer,
)
from novamind.engines.document.integrations.deepdoc.logging_compat import get_logger
from novamind.engines.document.integrations.deepdoc.page_filter import PageNoiseFilter
from novamind.engines.document.integrations.deepdoc.pdf_artifacts import PdfArtifactExtractor
from novamind.engines.document.integrations.deepdoc.pdf_layout import PdfLayoutExtractor
from novamind.engines.document.integrations.deepdoc.parsers.pdf_plain import RAGFlowPlainPdfParser
from novamind.engines.document.integrations.deepdoc.updown_concat import UpDownConcatMerger
from novamind.engines.document.integrations.deepdoc.vision.recognizer import Recognizer
from novamind.engines.document.integrations.deepdoc.vision_runtime import get_vision_health_status

# Structured logger (structlog BoundLogger) — accepts key=value context kwargs
# and renders JSON. Do NOT use stdlib ``logging.info(msg, key=val)`` here: stdlib
# Logger._log() rejects arbitrary kwargs and raises TypeError at the call site.
logger = get_logger(__name__)


@dataclass(slots=True)
class DeepDocPdfBox:
    page: int
    x0: float
    x1: float
    top: float
    bottom: float
    text: str
    col_id: int = 0
    position_tag: str = ""
    positions: list[list[float]] | None = None
    layout_type: str = ""
    layoutno: str = ""

    @property
    def height(self) -> float:
        return max(self.bottom - self.top, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeepDocPdfBox":
        positions = data.get("positions")
        return cls(
            page=int(data.get("page_number", data.get("page", 0))),
            x0=float(data["x0"]),
            x1=float(data["x1"]),
            top=float(data["top"]),
            bottom=float(data["bottom"]),
            text=str(data.get("text", "")),
            col_id=int(data.get("col_id", 0)),
            position_tag=str(data.get("position_tag", "")),
            positions=[list(pos) for pos in positions] if positions else None,
            layout_type=str(data.get("layout_type", "")),
            layoutno=str(data.get("layoutno", "")),
        )

    def as_tagged_text(self) -> str:
        return f"{self.position_tag or self.line_tag()}{self.text}"

    def line_tag(self) -> str:
        return f"@@{self.page}\t{self.x0:.1f}\t{self.x1:.1f}\t{self.top:.1f}\t{self.bottom:.1f}##"


class RAGFlowPdfParser:
    """Vendored PDF parser facade modeled after RAGFlowPdfParser."""

    # 公式识别（pix2text-mfr）：layout 的 equation 区域 → LaTeX。
    # 这些阈值在 2026-09-15 spike 中用真实论文（62 个公式区域）标定。
    FORMULA_LAYOUT_SCORE_THR = 0.3  # equation 区域置信度低于此值不识别
    FORMULA_INLINE_WIDTH_RATIO = 0.3  # 区域宽度 < 30% 页宽 → 行内公式 $..$，否则块级 $$..$$
    FORMULA_BOX_CONTAIN_RATIO = 0.7  # 文字框 ≥70% 面积落入公式区域 → 视为公式内碎片剔除
    FORMULA_REGION_DEDUPE_RATIO = 0.8  # 区域 ≥80% 面积嵌套进另一区域 → 去重（整块+逐行拆分并存）
    FORMULA_CROP_PADDING = 4.0  # 公式裁剪外扩（PDF 点，防止笔画贴边被切）

    def __init__(self):
        self._plain_parser = RAGFlowPlainPdfParser()
        self._layout_extractor = PdfLayoutExtractor()
        self._layout_recognizer = None
        self._ocr = None
        self._updown_concat = UpDownConcatMerger()
        self._page_filter = PageNoiseFilter()
        self._artifact_extractor = PdfArtifactExtractor()
        self.page_images: list[Image.Image] = []
        self.page_from = 0
        self.page_cum_height: list[float] = [0.0]
        self.page_layout: list[list[dict[str, Any]]] = []
        self.outlines: list[Any] = []
        self.pdf = None
        self.mean_height: list[float] = []
        self.mean_width: list[float] = []
        self.boxes: list[dict[str, Any]] = []
        self.lefted_chars: list[Any] = []
        self.garbages: dict[str, Any] = {}

    def _get_layout_recognizer(self):
        if self._layout_recognizer is None:
            # The hosted layout.onnx (InfiniFlow/deepdoc) is a YOLOv10 model whose
            # output is (batch, anchors, 6=[xywh,score,class]); LayoutRecognizer4YOLOv10
            # has the matching postprocess. Plain LayoutRecognizer's base postprocess
            # misreads that shape and IndexErrors. Mirrors RAGFlow's docker_stubs alias.
            from novamind.engines.document.integrations.deepdoc.vision.layout_recognizer import (
                LayoutRecognizer4YOLOv10 as LayoutRecognizer,
            )

            self._layout_recognizer = LayoutRecognizer()
        return self._layout_recognizer

    @staticmethod
    def _import_fitz():
        import fitz

        return fitz

    @staticmethod
    def total_page_number(fnm, binary=None):
        try:
            with pdfplumber.open(fnm) if binary is None else pdfplumber.open(BytesIO(binary)) as pdf:
                total_page = len(pdf.pages)
            return total_page
        except Exception:
            logging.exception("total_page_number")
            return 0

    @staticmethod
    def sort_x_by_page(boxes: Sequence[DeepDocPdfBox], threshold: float) -> List[DeepDocPdfBox]:
        ordered = sorted(boxes, key=lambda item: (item.page, item.x0, item.top))
        for index in range(len(ordered) - 1):
            for cursor in range(index, -1, -1):
                if (
                    abs(ordered[cursor + 1].x0 - ordered[cursor].x0) < threshold
                    and ordered[cursor + 1].top < ordered[cursor].top
                    and ordered[cursor + 1].page == ordered[cursor].page
                ):
                    ordered[cursor], ordered[cursor + 1] = ordered[cursor + 1], ordered[cursor]
        return ordered

    @staticmethod
    def sort_X_by_page(arr, threshold):
        return RAGFlowPdfParser.sort_x_by_page(arr, threshold)

    def _has_color(self, obj):
        if obj.get("ncs", "") == "DeviceGray":
            if obj.get("stroking_color") and obj.get("stroking_color")[0] == 1 and obj.get("non_stroking_color") and obj.get("non_stroking_color")[0] == 1:
                if re.match(r"[a-zT_\[\]\(\)-]+", obj.get("text", "")):
                    return False
        return True

    @staticmethod
    def _is_garbled_char(ch):
        if not ch:
            return False
        cp = ord(ch)
        if 0xE000 <= cp <= 0xF8FF:
            return True
        if 0xF0000 <= cp <= 0xFFFFF:
            return True
        if 0x100000 <= cp <= 0x10FFFF:
            return True
        if cp == 0xFFFD:
            return True
        if cp < 0x20 and ch not in ("\t", "\n", "\r"):
            return True
        if 0x80 <= cp <= 0x9F:
            return True
        return False

    @classmethod
    def _is_garbled_text(cls, text):
        if not text:
            return False
        garbled = sum(1 for ch in text if cls._is_garbled_char(ch))
        return garbled / max(len(text), 1) >= 0.3

    @staticmethod
    def _has_subset_font_prefix(fontname):
        return bool(fontname and re.match(r"^[A-Z]{6}\+", str(fontname)))

    @classmethod
    def _is_garbled_by_font_encoding(cls, page_chars, *, require_garbled_chars: bool = False) -> bool:
        """子集字体编码可疑检测。

        ``require_garbled_chars=False``（默认，兼容旧行为）：子集字体 + 纯 ASCII
        字符占比 >= 50% 即可疑，供 ``_fuse_page`` 逐框裁决时与字符级乱码特征
        联合使用（两个信号叠加，误报率低）。

        ``require_garbled_chars=True``：额外要求样本里存在字符级乱码特征
        （PUA/CID/替换符），用于「清空整页文字层」这类重决策——单独的子集字体
        信号对现代 LaTeX 产出的 PDF 几乎必然误报（其字体全部带 ``XXXXXX+``
        子集前缀，表格/参考文献页又以 ASCII 为主）。
        """
        if not page_chars:
            return False
        suspicious = 0
        sample_size = min(len(page_chars), 200)
        has_garbled_chars = False
        for char in page_chars[:sample_size]:
            text = str(char.get("text", "") or "")
            fontname = char.get("fontname", "")
            if cls._has_subset_font_prefix(fontname) and text and all(ord(ch) < 128 for ch in text):
                suspicious += 1
            if any(cls._is_garbled_char(ch) for ch in text):
                has_garbled_chars = True
        if require_garbled_chars and not has_garbled_chars:
            return False
        return suspicious / max(sample_size, 1) >= 0.5

    @staticmethod
    def proj_match(line: str):
        if len(line) <= 2:
            return None
        if re.match(r"[0-9 ().,%%+/-]+$", line):
            return False
        patterns = [
            (r"第[零一二三四五六七八九十百]+章", 1),
            (r"第[零一二三四五六七八九十百]+[条节]", 2),
            (r"[零一二三四五六七八九十百]+[、 　]", 3),
            (r"[\(（][零一二三四五六七八九十百]+[）\)]", 4),
            (r"[0-9]+(、|\.[　 ]|\.[^0-9])", 5),
            (r"[0-9]+\.[0-9]+(、|[. 　]|[^0-9])", 6),
            (r"[0-9]+\.[0-9]+\.[0-9]+(、|[ 　]|[^0-9])", 7),
            (r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(、|[ 　]|[^0-9])", 8),
            (r".{,48}[：:?？]$", 9),
            (r"[0-9]+）", 10),
            (r"[\(（][0-9]+[）\)]", 11),
            (r"[零一二三四五六七八九十百]+是", 12),
            (r"[⚫•➢✓]", 12),
        ]
        for pattern, level in patterns:
            if re.match(pattern, line):
                return level
        return None

    def __call__(
        self,
        filename: Union[str, bytes, Path],
        *,
        pdf_mode: str = "full",
        chunk_size: int = 1000,
        formula_recognition: bool | None = None,
    ) -> DeepDocParseResult:
        source_desc = str(filename) if isinstance(filename, (str, Path)) else "<bytes>"
        logger.info(
            "DeepDoc PDF 解析器开始",
            pdf_mode=pdf_mode,
            chunk_size=chunk_size,
            formula_recognition=formula_recognition,
            source=source_desc,
        )
        if pdf_mode == "plain":
            result = self._parse_plain(filename, chunk_size=chunk_size)
        elif pdf_mode == "full":
            result = self._parse_full(
                filename, chunk_size=chunk_size, formula_recognition=formula_recognition
            )
        elif pdf_mode in ("layout", "vision"):
            # 兼容别名：layout/vision 已并入 full（上游对齐的逐框融合流水线），
            # 保留一个发布周期，防止旧 runtime config / 测试漏迁移。
            logger.info("DeepDoc PDF 模式别名映射到 full", alias=pdf_mode)
            result = self._parse_full(
                filename, chunk_size=chunk_size, formula_recognition=formula_recognition
            )
        else:
            raise ValueError(f"Unsupported DeepDoc PDF mode: {pdf_mode}")
        logger.info(
            "DeepDoc PDF 解析器完成",
            pdf_mode=pdf_mode,
            char_count=len(result.full_text),
            chunk_count=len(result.chunks),
            metadata_keys=list(result.metadata.keys()) if result.metadata else [],
        )
        return result

    def __images__(self, fnm, zoomin=3, page_from=0, page_to=MAXIMUM_PAGE_NUMBER, callback=None):
        self.lefted_chars = []
        self.mean_height = []
        self.mean_width = []
        self.boxes = []
        self.garbages = {}
        self.page_cum_height = [0]
        self.page_layout = []
        self.page_from = page_from
        self.page_images = []
        with pdfplumber.open(fnm) if isinstance(fnm, str) else pdfplumber.open(BytesIO(fnm)) as pdf:
            self.pdf = pdf
            for page in pdf.pages[page_from:page_to]:
                rendered = page.to_image(resolution=72 * zoomin, antialias=True).annotated
                self.page_images.append(rendered)
                self.page_cum_height.append(self.page_cum_height[-1] + rendered.size[1] / zoomin)
                self.page_layout.append([])
        return self.page_images

    def parse_into_bboxes(
        self,
        filename: Union[str, bytes, Path],
    ) -> List[DeepDocPdfBox]:
        pdf_source = str(filename) if not isinstance(filename, bytes) else BytesIO(filename)
        boxes: List[DeepDocPdfBox] = []
        with pdfplumber.open(pdf_source) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(
                    keep_blank_chars=False,
                    use_text_flow=False,
                    extra_attrs=[],
                ) or []
                page_lines = self._layout_extractor.extract_page_lines(words, page_number=page_index)
                for line in page_lines:
                    position_tag = self._line_tag(line)
                    boxes.append(
                        DeepDocPdfBox(
                            page=page_index,
                            x0=float(line["x0"]),
                            x1=float(line["x1"]),
                            top=float(line["top"]),
                            bottom=float(line["bottom"]),
                            text=str(line["text"]),
                            col_id=int(line.get("col_id", 0)),
                            position_tag=position_tag,
                            positions=[
                                [
                                    float(page_index),
                                    float(line["x0"]),
                                    float(line["x1"]),
                                    float(line["top"]),
                                    float(line["bottom"]),
                                ]
                            ],
                        )
                    )
        return boxes

    def crop(self, text: str, ZM: int = 3, need_position: bool = False):
        poss = self.extract_positions(text)
        if not poss:
            if need_position:
                return None, None
            return self.remove_tag(text)

        if not getattr(self, "page_images", None):
            if need_position:
                return None, None
            return self.remove_tag(text)

        imgs = []
        page_count = len(self.page_images)
        filtered_poss = []
        for pns, left, right, top, bottom in poss:
            valid_pns = [pn for pn in pns if 0 <= pn < page_count]
            if valid_pns:
                filtered_poss.append((valid_pns, left, right, top, bottom))
        poss = filtered_poss
        if not poss:
            if need_position:
                return None, None
            return self.remove_tag(text)

        GAP = 6
        pos = poss[0]
        poss.insert(0, ([pos[0][0]], pos[1], pos[2], max(0, pos[3] - 120), max(pos[3] - GAP, 0)))
        pos = poss[-1]
        last_page_idx = pos[0][-1]
        last_page_height = self.page_images[last_page_idx].size[1]
        poss.append(([last_page_idx], pos[1], pos[2], min(last_page_height, pos[4] + GAP), min(last_page_height, pos[4] + 120)))

        positions = []
        for ii, (pns, left, right, top, bottom) in enumerate(poss):
            if bottom <= top:
                bottom = top + 2
            img0 = self.page_images[pns[0]]
            x0, y0, x1, y1 = int(left), int(top), int(right), int(min(bottom, img0.size[1]))
            if x1 <= x0 or y1 <= y0:
                continue
            crop0 = img0.crop((x0, y0, x1, y1))
            imgs.append(crop0)
            if 0 < ii < len(poss) - 1:
                positions.append((pns[0] + self.page_from, x0, x1, y0, y1))
            remain_bottom = bottom - img0.size[1]
            for pn in pns[1:]:
                if remain_bottom <= 0:
                    break
                page = self.page_images[pn]
                x0, y0, x1, y1 = int(left), 0, int(right), int(min(remain_bottom, page.size[1]))
                if x1 <= x0 or y1 <= y0:
                    remain_bottom -= page.size[1]
                    continue
                cimgp = page.crop((x0, y0, x1, y1))
                imgs.append(cimgp)
                if 0 < ii < len(poss) - 1:
                    positions.append((pn + self.page_from, x0, x1, y0, y1))
                remain_bottom -= page.size[1]

        if not imgs:
            if need_position:
                return None, None
            return self.remove_tag(text)

        total_height = sum(img.size[1] + GAP for img in imgs)
        max_width = max(img.size[0] for img in imgs)
        pic = Image.new("RGB", (int(max_width), int(total_height)), (245, 245, 245))
        current_y = 0
        for index, img in enumerate(imgs):
            pic.paste(img, (0, int(current_y)))
            current_y += img.size[1] + GAP
        return (pic, positions) if need_position else pic

    def get_position(self, bx, ZM):
        poss = []
        pn = bx["page_number"]
        top = bx["top"] - self.page_cum_height[pn - 1]
        bott = bx["bottom"] - self.page_cum_height[pn - 1]
        poss.append((pn, bx["x0"], bx["x1"], top, min(bott, self.page_images[pn - 1].size[1] / ZM)))
        while bott * ZM > self.page_images[pn - 1].size[1]:
            bott -= self.page_images[pn - 1].size[1] / ZM
            top = 0
            pn += 1
            poss.append((pn, bx["x0"], bx["x1"], top, min(bott, self.page_images[pn - 1].size[1] / ZM)))
        return poss

    def __height(self, box):
        if isinstance(box, dict):
            return float(box.get("bottom", 0.0)) - float(box.get("top", 0.0))
        return float(getattr(box, "bottom", 0.0)) - float(getattr(box, "top", 0.0))

    def __char_width(self, box):
        if isinstance(box, dict):
            return float(box.get("x1", 0.0)) - float(box.get("x0", 0.0))
        return float(getattr(box, "x1", 0.0)) - float(getattr(box, "x0", 0.0))

    def _x_dis(self, a, b):
        return max(0.0, float(b["x0"]) - float(a["x1"]))

    def _y_dis(self, a, b):
        return max(0.0, float(b["top"]) - float(a["bottom"]))

    def _updown_concat_features(self, upper, lower):
        return {
            "x_gap": self._x_dis(upper, lower),
            "y_gap": self._y_dis(upper, lower),
            "same_page": int(upper["page_number"] == lower["page_number"]),
        }

    def _match_proj(self, line):
        return self.proj_match(line)

    def _merge_with_same_bullet(self, boxes):
        return list(boxes)

    def _naive_vertical_merge(self, boxes):
        return list(boxes)

    def _concat_downward(self, boxes):
        return list(boxes)

    def _text_merge(self, boxes, zoomin=3):
        """对同栏、同版面块的纯文本行做横向拼接。

        先分栏，再按行间距与水平间隙合并相邻文本行。
        """
        if not boxes:
            return boxes
        boxes = self._assign_column(boxes, zoomin)
        boxes = Recognizer.sort_Y_firstly(
            [b.to_dict() for b in boxes],
            max(b.height for b in boxes) * 0.5,
        )
        boxes = [DeepDocPdfBox.from_dict(b) for b in boxes]

        merged: list[DeepDocPdfBox] = []
        for box in boxes:
            if box.layout_type not in {"text", ""} or not box.text.strip():
                merged.append(box)
                continue
            if not merged:
                merged.append(box)
                continue

            last = merged[-1]
            same_page = box.page == last.page
            same_col = box.col_id == last.col_id
            same_layout = box.layoutno and box.layoutno == last.layoutno
            vertical_gap = abs(last.bottom - box.bottom)
            horizontal_gap = box.x0 - last.x1
            char_h = max(box.height, last.height, 1e-6)

            if (
                same_page
                and same_col
                and same_layout
                and vertical_gap < char_h * 0.6
                and horizontal_gap > 0
                and horizontal_gap < char_h * 2.5
            ):
                last.text += box.text
                last.x1 = max(last.x1, box.x1)
                last.bottom = max(last.bottom, box.bottom)
                last.top = min(last.top, box.top)
                continue
            merged.append(box)
        return merged

    def _filter_forpages(self, boxes):
        return list(boxes)

    def __filterout_scraps(self, boxes, ZM):
        return list(boxes)

    def _offset_position_tag(self, box, offset):
        return box

    def _parse_loaded_window_into_bboxes(self, *args, **kwargs):
        return []

    def _evaluate_table_orientation(self, *args, **kwargs):
        return 0

    def _ocr_rotated_tables(self, *args, **kwargs):
        return []

    def __ocr(self, *args, **kwargs):
        return []

    def _layouts_rec(self, ZM, drop=True):
        return self.page_layout

    def _assign_column(self, boxes, zoomin=3):
        """调用 PdfLayoutExtractor 的 assign_columns 给文本框标 col_id。"""
        if not boxes:
            return boxes
        if self._layout_extractor is None:
            return boxes

        dict_boxes = []
        for box in boxes:
            d = box.to_dict()
            d["page_number"] = box.page
            dict_boxes.append(d)
        assigned = self._layout_extractor.assign_columns(dict_boxes)
        return [DeepDocPdfBox.from_dict(b) for b in assigned]

    def _extract_table_figure(self, *args, **kwargs):
        return [], []

    def _table_transformer_job(self, ZM, auto_rotate=True):
        self.tb_cpns = []
        self.table_rotations = {}
        self.rotated_table_imgs = {}
        return []

    def _to_global_boxes(self, boxes):
        global_boxes = []
        for box in boxes:
            copied = dict(box)
            page_number = int(copied.get("page_number", 1))
            offset = self.page_cum_height[page_number - 1] if 0 <= page_number - 1 < len(self.page_cum_height) else 0
            copied["top"] = float(copied.get("top", 0.0)) + float(offset)
            copied["bottom"] = float(copied.get("bottom", 0.0)) + float(offset)
            global_boxes.append(copied)
        return global_boxes

    def _final_reading_order_merge(self, entries):
        return sorted(
            entries,
            key=lambda item: (
                int(item.get("page", item.get("page_number", 0))),
                float(item.get("top", item.get("bbox", {}).get("top", 0.0))),
                float(item.get("x0", item.get("bbox", {}).get("x0", 0.0))),
            ),
        )

    @staticmethod
    def remove_tag(text: str) -> str:
        # 委托到 core.models.strip_position_tags，保持全包唯一的坐标标记清洗正则。
        return strip_position_tags(text)

    @staticmethod
    def extract_positions(text: str):
        positions = []
        for tag in re.findall(r"@@[0-9-]+\t[0-9.\t]+##", text):
            page_number, left, right, top, bottom = tag.strip("#").strip("@").split("\t")
            left, right, top, bottom = float(left), float(right), float(top), float(bottom)
            positions.append(([int(page) - 1 for page in page_number.split("-")], left, right, top, bottom))
        return positions

    @staticmethod
    def _line_tag(line: Dict[str, Any]) -> str:
        return "@@{}\t{:.1f}\t{:.1f}\t{:.1f}\t{:.1f}##".format(
            int(line.get("page_number", 1)),
            float(line["x0"]),
            float(line["x1"]),
            float(line["top"]),
            float(line["bottom"]),
        )

    def _parse_plain(
        self,
        filename: Union[str, bytes, Path],
        *,
        chunk_size: int,
    ) -> DeepDocParseResult:
        plain_sections, _, outlines = self._plain_parser(filename)
        plain_lines = [line for line, _ in plain_sections if line.strip()]
        full_text = "\n".join(plain_lines).strip()
        chunks = self._chunk_blocks(plain_lines or [full_text], chunk_size=chunk_size)
        return DeepDocParseResult(
            full_text=full_text,
            chunks=chunks,
            metadata={
                "parser": "deepdoc",
                "file_type": "pdf",
                "pdf_mode": "plain",
                "outlines": outlines,
                "plain_sections": plain_sections,
                "source": "ragflow-adapted",
                "parser_class": "RAGFlowPdfParser",
            },
        )

    def _parse_full(
        self,
        filename: Union[str, bytes, Path],
        *,
        chunk_size: int,
        formula_recognition: bool | None = None,
    ) -> DeepDocParseResult:
        """上游对齐的默认全量流水线：每页 OCR 检测 + 逐框文字层融合 + 乱码回退 OCR
        （_extract_fused_pages）→ ONNX 版面贴标签 → 段落合并 → 页眉过滤 → 表格/图片
        抽取 → 阅读顺序 → 结构化 chunks。后续步骤复用原 vision 路径的尾巴。"""
        plain_sections, _, outlines = self._plain_parser(filename)
        image_list, fused_pages, layout_pages, fusion_meta = self._extract_fused_pages(filename)
        page_count = len(image_list)
        effective_zooms: list[int] = fusion_meta.get("effective_zooms", [2] * page_count)
        layout_boxes, page_layout = self._get_layout_recognizer()(
            image_list,
            fused_pages,
            scale_factor=effective_zooms,
            layouts=layout_pages,
            # drop=True 对齐上游 _layouts_rec 默认行为：页眉/页脚/参考文献框
            # （garbage_layouts）从正文剔除，否则每页重复的页眉页脚垃圾全部进 MD。
            # keep_features 例外已与上游一致（footer 不在页底 90% 下方、header
            # 不在页顶 10% 上方时保留）。
            drop=True,
        )
        # 布局分类已消费 image_list，立即释放整份渲染 buffer：大 PDF 逐页 OCR 检测
        # 用的 numpy 页 + 后续 artifact 的 PIL 页若同时存活会双倍内存（doc 565 实测 OOM）。
        image_list.clear()
        del image_list
        gc.collect()

        all_boxes = [
            DeepDocPdfBox(
                page=int(box.get("page_number", 0)) + 1,
                x0=float(box["x0"]),
                x1=float(box["x1"]),
                top=float(box["top"]),
                bottom=float(box["bottom"]),
                text=str(box.get("text", "")),
                col_id=int(box.get("col_id", 0)),
                position_tag=self._line_tag(
                    {
                        "page_number": int(box.get("page_number", 0)) + 1,
                        "x0": float(box["x0"]),
                        "x1": float(box["x1"]),
                        "top": float(box["top"]),
                        "bottom": float(box["bottom"]),
                    }
                ),
                positions=[
                    [
                        float(int(box.get("page_number", 0)) + 1),
                        float(box["x0"]),
                        float(box["x1"]),
                        float(box["top"]),
                        float(box["bottom"]),
                    ]
                ],
                layout_type=str(box.get("layout_type", "")),
                layoutno=str(box.get("layoutno", "")),
            )
            for box in layout_boxes
        ]
        # 公式识别：layout 的 equation 区域跑 pix2text-mfr → LaTeX box，
        # 同时剔除区域内的 OCR 碎片框（rec 模型把公式读成的乱码短串）。
        # 模型缺失时 WARNING 软降级（公式保留 OCR 碎片，与 layout/text_concat 回退口径一致）。
        page_zoom_map = {page: zoom for page, zoom in enumerate(effective_zooms, start=1)}
        formula_results, formula_meta = self._recognize_equation_regions(
            filename,
            page_layout,
            zoom_map=page_zoom_map,
            enabled=formula_recognition,
        )
        if formula_results:
            all_boxes, replaced_fragments = self._apply_formula_boxes(all_boxes, formula_results)
            formula_meta["replaced_fragment_boxes"] = replaced_fragments
        text_boxes = [box for box in all_boxes if box.text.strip()]
        # 先做列检测 + 横向合并，再做纵向段落合并。上游 _text_merge 负责把同行文字
        # 碎片合并，避免双栏论文中一个标题/句子被切成多个 chunk。
        text_boxes = self._text_merge(text_boxes)
        merged_boxes, merge_strategy = self._merge_vertical_boxes_with_strategy(text_boxes)
        filtered_boxes, filter_meta = self._filter_boxes_with_meta(merged_boxes or text_boxes, total_pages=page_count)
        chunk_boxes = filtered_boxes or merged_boxes or text_boxes
        artifact_boxes = self._collect_artifact_boxes(all_boxes, chunk_boxes)
        # artifact 页从 fitz 按需渲染 PIL（仅含表格/图片的页，_collect_group_crops 按 page key 查）。
        # 关键：image_list 已在布局分类后整体释放，numpy 阶段与 PIL 阶段不再重叠，
        # 峰值从「全量 numpy + 工件页 PIL」双份降为单份，避免大 PDF 双倍内存 OOM（doc 565）。
        artifacts = self._extract_artifacts(
            artifact_boxes,
            page_images=self._render_artifact_pages(filename, artifact_boxes, zoom_map=page_zoom_map),
            zoom_map=page_zoom_map,
        )
        table_regions = self._build_table_regions_metadata(artifacts)
        figure_regions = self._build_figure_regions_metadata(
            artifacts,
            raster_images_by_page=fusion_meta.get("raster_images_by_page") or {},
        )
        # 被保留 table artifact 的成员框已随 [TABLE]/HTML entry 进入 reading_order，
        # 从正文按成员逐框剔除（对齐上游 tag-pop 语义），否则表格内容（OCR 散落
        # 数字流）在 MD 里重复出现两份；非成员正文不因 region bbox 误判被删。
        reading_order_text_boxes = self._drop_boxes_consumed_by_tables(chunk_boxes, table_regions)
        # 已挂载题注的框从正文 pop（对齐上游 caption 出正文流）：题注文本已随
        # table/figure entry 的 caption 字段输出，留正文则重复两份。
        reading_order_text_boxes = self._drop_attached_caption_boxes(
            reading_order_text_boxes,
            table_regions,
            figure_regions,
        )
        reading_order = self._build_reading_order_metadata(
            reading_order_text_boxes,
            table_regions,
            figure_regions,
        )
        # 分阶段诊断：定位「整页内容丢失」类问题。按页统计各阶段文本字符数，
        # 配合 filter_meta（toc/dirty 移除页）可一眼看出内容在哪一步被丢。
        logger.info(
            "DeepDoc full 流水线分阶段统计",
            page_count=page_count,
            layout_chars_by_page=self._chars_by_page(all_boxes),
            text_merge_chars_by_page=self._chars_by_page(text_boxes),
            vertical_merge_chars_by_page=self._chars_by_page(merged_boxes),
            filter_chars_by_page=self._chars_by_page(filtered_boxes),
            filter_meta=filter_meta,
            reading_order_entries_by_page=self._reading_order_entries_by_page(reading_order),
            chunk_boxes_count=len(chunk_boxes),
        )
        # 用 reading_order 构建完整 MD：文本段 + 表格占位/HTML + 图片占位符。
        # 图片占位符将在 document_pipeline 上传 MinIO 后替换为真实 URL。
        full_text = "\n\n".join(
            self._reading_order_entry_text(entry) for entry in reading_order
        ).strip()
        chunks, chunk_structure = self._build_structured_chunks(reading_order, chunk_size=chunk_size)
        return DeepDocParseResult(
            full_text=full_text,
            chunks=chunks,
            metadata={
                "parser": "deepdoc",
                "file_type": "pdf",
                "pdf_mode": "full",
                "text_source": "fused",
                "pages": page_count,
                "outlines": outlines,
                "plain_sections": plain_sections,
                "vision_strategy": fusion_meta["vision_strategy"],
                "layout_source": fusion_meta["layout_source"],
                "layout_model_error": fusion_meta.get("layout_model_error"),
                "paragraph_merge_strategy": merge_strategy,
                "page_filter": filter_meta,
                "artifacts": artifacts,
                "table_regions": table_regions,
                "figure_regions": figure_regions,
                "formula_recognition": formula_meta,
                "reading_order": reading_order,
                "chunk_structure": chunk_structure,
                "text_concat_model": self._updown_concat.model_status(),
                "ocr_sources": self._collect_ocr_sources(fused_pages),
                "layout_bboxes": [asdict(box) for box in all_boxes],
                "merged_bboxes": [asdict(box) for box in chunk_boxes],
                "page_layout": page_layout,
                "source": "ragflow-adapted",
                "parser_class": "RAGFlowPdfParser",
            },
        )

    def _extract_fused_pages(
        self,
        filename: Union[str, bytes, Path],
    ) -> tuple[list[np.ndarray], list[list[dict[str, Any]]], list[list[dict[str, Any]]], dict[str, Any]]:
        """上游 RAGFlow __images__+__ocr 对齐：渲染每页 → 抽 pdfplumber 文字层字符 →
        每页 OCR.detect 拿框 → 文字层字符按坐标匹配进框 → 逐框裁决（干净用文字层 /
        乱码回退 OCR / 无字符走 OCR）→ 空框 recognize_batch。产出 fused_pages 与原
        ocr_pages 同形状，供 _get_layout_recognizer() 贴 layout_type。

        对无文字层的页（扫描页）直接以 zoom=3（216 DPI，对齐上游 zoomin=3）起检，
        OCR 是其唯一文本来源，低清渲染会直接伤识别精度；有文字层的页维持 zoom=2。
        仍未检出文字框的页面按上游 zoom *= 3 递进重试（上限 9）；每页 effective_zoom
        随返回元组传出，供后续 layout/artifact 保持比例。
        """
        fitz = self._import_fitz()
        pdf_source = str(filename) if not isinstance(filename, bytes) else BytesIO(filename)
        image_list: list[np.ndarray] = []
        fused_pages: list[list[dict[str, Any]]] = []
        effective_zooms: list[int] = []
        raster_images_by_page: dict[int, list[dict[str, Any]]] = {}
        base_zoom = 2
        doc = fitz.open(stream=filename, filetype="pdf") if isinstance(filename, bytes) else fitz.open(str(filename))
        plumber_pdf = None
        try:
            try:
                plumber_pdf = pdfplumber.open(pdf_source)
            except Exception as exc:
                logger.warning("DeepDoc pdfplumber 打开失败，文字层融合退化为纯 OCR", error=str(exc))
                plumber_pdf = None
            plumber_pages = plumber_pdf.pages if plumber_pdf is not None else []
            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                # 记录该页内嵌栅格图 bbox（页面坐标），供 figure 判真使用：
                # 真实图表是内嵌位图对象，公式区是矢量绘制、无内嵌图。
                try:
                    raster_images_by_page[page_index + 1] = [
                        {"x0": float(info["bbox"][0]), "top": float(info["bbox"][1]),
                         "x1": float(info["bbox"][2]), "bottom": float(info["bbox"][3])}
                        for info in page.get_image_info()
                        if info.get("width", 0) >= 32 and info.get("height", 0) >= 32
                    ]
                except Exception:
                    raster_images_by_page[page_index + 1] = []
                # 无文字层的页（扫描页/乱码清空页）OCR 是唯一文本来源，按上游
                # zoomin=3（216 DPI）渲染：144 DPI 下五号字仅 ~21px 高，rec 模型
                # 要拉到 48px 需 2 倍上采样糊化笔画，中文形近字错误率高（扫描版
                # 错字的主因）。有文字层的页文本来自 pdfplumber 字符，像素仅供
                # det 检测，维持 zoom=2 控内存（doc 565 OOM 教训：全量 numpy 渲染
                # buffer 是内存大头）。
                page_chars = self._extract_page_chars(plumber_pages, page_index)
                page_zoom = 3 if not page_chars else base_zoom
                img: np.ndarray | None = None
                fused: list[dict[str, Any]] = []
                while page_zoom <= 9:
                    pix = page.get_pixmap(matrix=fitz.Matrix(page_zoom, page_zoom), alpha=False)
                    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                    if pix.n == 4:
                        img = img[:, :, :3]
                    fused = self._fuse_page(img, page_chars, page_index, page_zoom)
                    if fused:
                        break
                    page_zoom = min(page_zoom * 3, 9)
                    logger.info("DeepDoc 页面在 zoom=%s 未检出文字，递进重试", page_zoom, page_index=page_index)
                image_list.append(img if img is not None else np.zeros((1, 1, 3), dtype=np.uint8))
                fused_pages.append(fused)
                effective_zooms.append(page_zoom)
        finally:
            if plumber_pdf is not None:
                plumber_pdf.close()
            doc.close()

        layout_pages, layout_meta = self._resolve_layout_pages(
            image_list=image_list,
            ocr_pages=fused_pages,
            zooms=effective_zooms,
        )
        layout_meta["vision_strategy"] = self._build_vision_strategy(
            self._collect_ocr_sources(fused_pages),
            layout_meta["layout_source"],
        )
        layout_meta["effective_zooms"] = effective_zooms
        layout_meta["raster_images_by_page"] = raster_images_by_page
        return image_list, fused_pages, layout_pages, layout_meta

    def _extract_page_chars(self, plumber_pages: Sequence[Any], page_index: int) -> list[dict[str, Any]]:
        """抽该页 pdfplumber 文字层字符；乱码页（CID/PUA 字符或子集字体编码错乱）
        直接清空，强制该页全走 OCR。接线上游 __images__ 的乱码预清洗。

        子集字体编码检测（``_is_garbled_by_font_encoding``）不能单独作为清空
        整页的依据：现代 LaTeX 引擎（XeLaTeX/LuaLaTeX）产出的 PDF 字体几乎全部
        是 ``XXXXXX+`` 子集字体，表格页/参考文献页恰好又以 ASCII 为主，会 100%
        命中该检测而把本来干净的文字层整页丢弃、强制走 OCR，密集数字表格 OCR
        出来即粘连错串。因此这里要求「字符级乱码特征」也同时命中才清空整页；
        仅子集字体可疑时交给 ``_fuse_page`` 的逐框裁决（garbled/total >= 0.5 或
        子集字体编码乱码）兜底，乱码框仍会回退 OCR，但干净框保留文字层。
        """
        if not plumber_pages or page_index >= len(plumber_pages):
            return []
        try:
            ppage = plumber_pages[page_index]
            chars = [c for c in ppage.dedupe_chars().chars if self._has_color(c)]
        except Exception:
            return []
        sample_text = "".join(str(c.get("text", "") or "") for c in chars[:200])
        if self._is_garbled_text(sample_text):
            logger.info("DeepDoc 检测到乱码文字层（字符级特征），该页改走 OCR", page_index=page_index)
            return []
        if self._is_garbled_by_font_encoding(chars) and self._is_garbled_by_font_encoding(chars, require_garbled_chars=True):
            logger.info("DeepDoc 检测到乱码文字层（子集字体编码 + 字符级乱码同时命中），该页改走 OCR", page_index=page_index)
            return []
        return self._insert_word_spaces(chars)

    def _insert_word_spaces(self, chars: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """对英文 PDF 字符层，按同行字符间隙补空格，恢复单词边界。

        仅对非 CJK、非空格字符生效；避免中文文档被误插空格。
        """
        if not chars:
            return chars

        def _is_cjk(text: str) -> bool:
            return any("一" <= ch <= "鿿" for ch in text)

        sorted_chars = sorted(chars, key=lambda c: (float(c.get("top", 0.0)), float(c.get("x0", 0.0))))
        widths = [max(1.0, float(c.get("width", 0.0)) or float(c.get("x1", 0.0)) - float(c.get("x0", 0.0))) for c in sorted_chars]
        mean_width = float(np.mean(widths)) if widths else 1.0
        result: list[dict[str, Any]] = []
        for index, char in enumerate(sorted_chars):
            result.append(char)
            if index + 1 >= len(sorted_chars):
                continue
            next_char = sorted_chars[index + 1]
            text = str(char.get("text", "") or "")
            next_text = str(next_char.get("text", "") or "")
            if not text or not next_text:
                continue
            if text.isspace() or next_text.isspace():
                continue
            if _is_cjk(text) or _is_cjk(next_text):
                continue
            if not re.match(r"[a-zA-Z0-9,.!?;:%]", text[-1]) or not re.match(r"[a-zA-Z0-9,.!?;:%]", next_text[0]):
                continue
            gap = float(next_char.get("x0", 0.0)) - float(char.get("x1", 0.0))
            same_line = abs(float(next_char.get("top", 0.0)) - float(char.get("top", 0.0))) < mean_width * 0.8
            if same_line and gap > mean_width * 0.6:
                space_char = dict(char)
                space_char["text"] = " "
                space_char["x0"] = float(char.get("x1", 0.0))
                space_char["x1"] = float(next_char.get("x0", 0.0))
                result.append(space_char)
        return result

    def _fuse_page(
        self,
        img: np.ndarray,
        page_chars: list[dict[str, Any]],
        page_index: int,
        zoom: int,
        device_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """上游 __ocr 逐框融合：OCR.detect 拿框 → pdfplumber chars 按坐标 find_overlapped
        匹配进框 → 逐框裁决（干净用文字层 / 乱码或无字符回退 OCR）→ 空框 recognize_batch。"""
        from novamind.engines.document.integrations.deepdoc.vision.recognizer import Recognizer

        if self._ocr is None:
            from novamind.engines.document.integrations.deepdoc.vision.ocr import OCR

            logger.info("DeepDoc OCR 引擎首次加载模型", page_index=page_index)
            self._ocr = OCR(autoload=True)
            self._artifact_extractor._ocr = self._ocr

        if device_id is None and self._ocr.parallel_devices > 1:
            device_id = page_index % self._ocr.parallel_devices
        device_id = device_id or 0

        img_np = np.asarray(img)
        try:
            detected = list(self._ocr.detect(img_np, device_id=device_id) or [])
        except Exception as exc:
            logger.warning("DeepDoc OCR detect 失败", page_index=page_index, error=str(exc))
            return []
        if not detected:
            return []

        boxes: list[dict[str, Any]] = []
        for box_px, _score in detected:
            pts = np.asarray(box_px, dtype=np.float32)
            x0 = float(np.min(pts[:, 0]) / zoom)
            x1 = float(np.max(pts[:, 0]) / zoom)
            top = float(np.min(pts[:, 1]) / zoom)
            bottom = float(np.max(pts[:, 1]) / zoom)
            if x0 >= x1 or top >= bottom:
                continue
            boxes.append(
                {
                    "x0": x0,
                    "x1": x1,
                    "top": top,
                    "bottom": bottom,
                    "text": "",
                    "chars": [],
                    "ocr_source": "text_layer",
                    "page_number": page_index,
                }
            )
        if not boxes:
            return []
        mean_h = float(np.median([b["bottom"] - b["top"] for b in boxes])) or 1.0
        boxes = Recognizer.sort_Y_firstly(boxes, mean_h / 3)

        # 1) pdfplumber 字符按坐标匹配进 OCR 检测框
        for c in page_chars:
            ii = Recognizer.find_overlapped(c, boxes)
            if ii is None:
                self.lefted_chars.append(c)
                continue
            ch = float(c["bottom"]) - float(c["top"])
            bh = boxes[ii]["bottom"] - boxes[ii]["top"]
            if abs(ch - bh) / max(ch, bh) >= 0.7 and str(c.get("text", "")) != " ":
                self.lefted_chars.append(c)
                continue
            boxes[ii]["chars"].append(c)

        # 2) 逐框裁决：文字层干净则用，乱码（PUA/CID 或子集字体编码）则清空回退 OCR
        for b in boxes:
            if not b["chars"]:
                b.pop("chars", None)
                continue
            m_ht = float(np.mean([float(c.get("height", 0.0)) for c in b["chars"]])) or 0.0
            garbled = 0
            total = 0
            text_parts: list[str] = []
            for c in Recognizer.sort_Y_firstly(b["chars"], m_ht):
                t = str(c.get("text", "") or "")
                if t == " " and text_parts:
                    if re.match(r"[0-9a-zA-Z,.?;:!%]", text_parts[-1][-1]):
                        text_parts.append(" ")
                else:
                    text_parts.append(t)
                    for ch in t:
                        if not ch.isspace():
                            total += 1
                            if self._is_garbled_char(ch):
                                garbled += 1
            box_chars = b.pop("chars", [])
            b["text"] = "".join(text_parts)
            # 框级回退 OCR 同样要求「字符级乱码」信号：单独的子集字体信号对
            # LaTeX 产出的 PDF（字体全带 XXXXXX+ 前缀、表格/参考文献纯 ASCII）
            # 几乎必然误报，会把干净的参考文献/表格框清空后交给 OCR 认成粘连串。
            if total > 0 and (
                garbled / total >= 0.5
                or (self._is_garbled_by_font_encoding(box_chars) and garbled > 0)
            ):
                b["text"] = ""
                b["ocr_source"] = "vendored_ocr"

        # 3) 空文本框批量 OCR 识别
        empty_boxes = [b for b in boxes if not b["text"]]
        if empty_boxes:
            crops = []
            for b in empty_boxes:
                pts = np.array(
                    [
                        [b["x0"] * zoom, b["top"] * zoom],
                        [b["x1"] * zoom, b["top"] * zoom],
                        [b["x1"] * zoom, b["bottom"] * zoom],
                        [b["x0"] * zoom, b["bottom"] * zoom],
                    ],
                    dtype=np.float32,
                )
                crops.append(self._ocr.get_rotate_crop_image(img_np, pts, device_id=device_id))
            try:
                texts = self._ocr.recognize_batch(crops, device_id=device_id) or []
            except Exception as exc:
                logger.warning("DeepDoc OCR recognize_batch 失败", page_index=page_index, error=str(exc))
                texts = []
            for b, t in zip(empty_boxes, texts):
                b["text"] = str(t or "").strip()
                if b["text"]:
                    b["ocr_source"] = "vendored_ocr"

        # 4) 产出块（过滤空文本）
        blocks: list[dict[str, Any]] = []
        for b in boxes:
            text = b["text"].strip()
            if not text:
                continue
            blocks.append(
                {
                    "text": text,
                    "x0": b["x0"],
                    "x1": b["x1"],
                    "top": b["top"],
                    "bottom": b["bottom"],
                    "page_number": page_index,
                    "font_size": 0.0,
                    "ocr_source": b.get("ocr_source", "text_layer"),
                }
            )
        return blocks

    def _resolve_layout_pages(
        self,
        *,
        image_list: list[np.ndarray],
        ocr_pages: list[list[dict[str, Any]]],
        zooms: list[int],
    ) -> tuple[list[list[dict[str, Any]]], dict[str, Any]]:
        health = get_vision_health_status()
        logger.info(
            "DeepDoc 布局识别开始",
            can_run_layout_inference=health.get("can_run_layout_inference", False),
            can_run_vendored_ocr=health.get("can_run_vendored_ocr", False),
            layout_models_available=health.get("layout_models_available", False),
            page_count=len(image_list),
            effective_zooms=zooms,
        )
        if health.get("can_run_layout_inference"):
            try:
                # _get_layout_recognizer() is built lazily (autoload=False) because the
                # same instance is reused at the apply-layouts step (pdf.py ~619),
                # which only needs pre-computed layouts, not the model. Load explicitly
                # only here, right before detection. Any failure (model missing/corrupt,
                # onnxruntime unavailable, etc.) falls through to the heuristic fallback.
                recognizer = self._get_layout_recognizer()
                if not recognizer.loaded:
                    logging.info("DeepDoc 布局识别器首次加载模型")
                    recognizer.load()
                layout_pages = recognizer.forward(image_list, thr=0.2, batch_size=16)
                logger.info(
                    "DeepDoc 布局识别完成（ONNX 模型）",
                    page_count=len(layout_pages),
                )
                return list(layout_pages), {"layout_source": "onnx", "layout_model_error": None}
            except Exception as exc:
                logger.warning(
                    "DeepDoc 布局识别 ONNX 推理失败，回退到启发式",
                    error=str(exc),
                )
                heuristic_pages = self._build_heuristic_layout_pages(image_list, ocr_pages, zooms=zooms)
                return heuristic_pages, {"layout_source": "heuristic", "layout_model_error": str(exc)}

        logging.info("DeepDoc 布局识别不可用，使用启发式布局")
        heuristic_pages = self._build_heuristic_layout_pages(image_list, ocr_pages, zooms=zooms)
        return heuristic_pages, {"layout_source": "heuristic", "layout_model_error": None}

    def _build_heuristic_layout_pages(
        self,
        image_list: list[np.ndarray],
        ocr_pages: list[list[dict[str, Any]]],
        *,
        zooms: list[int],
    ) -> list[list[dict[str, Any]]]:
        layout_pages: list[list[dict[str, Any]]] = []
        for image, blocks, zoom in zip(image_list, ocr_pages, zooms):
            height, width = image.shape[:2]
            layout_pages.append(
                self._build_heuristic_layouts(
                    blocks,
                    page_width=float(width / zoom),
                    page_height=float(height / zoom),
                    zoom=zoom,
                )
            )
        return layout_pages

    @staticmethod
    def _build_heuristic_layouts(
        blocks: list[dict[str, Any]],
        page_width: float,
        page_height: float,
        zoom: int,
    ) -> list[dict[str, Any]]:
        if not blocks:
            return []
        font_sizes = [float(block.get("font_size", 0.0)) for block in blocks if float(block.get("font_size", 0.0)) > 0]
        median_font = median(font_sizes) if font_sizes else 0.0
        layouts = []
        sorted_blocks = sorted(blocks, key=lambda item: (item["top"], item["x0"]))
        for index, block in enumerate(sorted_blocks):
            text = block["text"].strip()
            layout_type = "text"
            lowered = text.lower()
            if re.match(r"^(figure|fig\.?)\s+\d+", lowered):
                layout_type = "figure caption"
            elif re.match(r"^table\s+\d+", lowered):
                layout_type = "table caption"
            elif block["top"] <= page_height * 0.06 and len(text) < 80:
                layout_type = "header"
            elif block["bottom"] >= page_height * 0.94 and len(text) < 80:
                layout_type = "footer"
            elif index == 0 and (float(block.get("font_size", 0.0)) >= median_font * 1.15 or len(text) < 120):
                layout_type = "title"
            elif text.count("|") >= 2 or text.count(";") >= 2:
                layout_type = "table"
            layouts.append(
                {
                    "type": layout_type,
                    "score": 0.95 if layout_type in {"title", "table", "text"} else 0.85,
                    "bbox": [
                        float(block["x0"] * zoom),
                        float(block["top"] * zoom),
                        float(block["x1"] * zoom),
                        float(block["bottom"] * zoom),
                    ],
                }
            )
        return layouts

    @staticmethod
    def _collect_ocr_sources(pages: list[list[dict[str, Any]]]) -> list[str]:
        sources = []
        for page in pages:
            source = next((str(block.get("ocr_source")) for block in page if block.get("ocr_source")), "fitz_text")
            sources.append(source)
        return sources

    @staticmethod
    def _build_vision_strategy(ocr_sources: list[str], layout_source: str) -> str:
        source_set = set(ocr_sources)
        if source_set == {"text_layer"}:
            text_source = "text-layer"
        elif source_set == {"vendored_ocr"}:
            text_source = "vendored-ocr"
        elif source_set == {"text_layer", "vendored_ocr"}:
            text_source = "fused"
        elif source_set == {"fitz_text"}:
            text_source = "fitz"
        elif source_set == {"fitz_ocr"}:
            text_source = "fitz-ocr"
        else:
            text_source = "hybrid-ocr"
        layout_part = "onnx-layout" if layout_source == "onnx" else "heuristic-layout"
        return f"{text_source}+{layout_part}"

    @staticmethod
    def _chunk_blocks(blocks: Sequence[str], chunk_size: int) -> List[str]:
        chunks: List[str] = []
        current_parts: List[str] = []
        current_length = 0

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            addition = len(block) + (2 if current_parts else 0)
            if current_parts and current_length + addition > chunk_size:
                chunks.append("\n\n".join(current_parts))
                current_parts = [block]
                current_length = len(block)
                continue

            current_parts.append(block)
            current_length += addition

        if current_parts:
            chunks.append("\n\n".join(current_parts))
        return chunks

    def _merge_vertical_boxes(self, boxes: Sequence[DeepDocPdfBox]) -> List[DeepDocPdfBox]:
        merged, _ = self._merge_vertical_boxes_with_strategy(boxes)
        return merged

    def _merge_vertical_boxes_with_strategy(
        self,
        boxes: Sequence[DeepDocPdfBox],
    ) -> tuple[List[DeepDocPdfBox], str]:
        merged, strategy = self._updown_concat.merge(list(boxes))
        return list(merged), strategy

    def _filter_boxes_with_meta(
        self,
        boxes: Sequence[DeepDocPdfBox],
        *,
        total_pages: int | None = None,
    ) -> tuple[List[DeepDocPdfBox], dict[str, Any]]:
        filtered, meta = self._page_filter.filter_boxes(list(boxes), total_pages=total_pages)
        return list(filtered), meta

    def _extract_artifacts(
        self,
        boxes: Sequence[DeepDocPdfBox],
        *,
        page_images: dict[int, Image.Image] | None = None,
        zoom_map: dict[int, float] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        return self._artifact_extractor.extract(list(boxes), page_images=page_images, zoom_map=zoom_map)

    def _render_artifact_pages(
        self,
        filename: Union[str, bytes, Path],
        artifact_boxes: Sequence[DeepDocPdfBox],
        zoom_map: dict[int, float] | None = None,
    ) -> dict[int, Image.Image]:
        """把含表格/图片 artifact 的页从 fitz 渲染为 PIL，只渲染这些页。

        与 _extract_fused_pages 的全量 numpy 渲染串行（调用方先释放 image_list），
        避免大 PDF 同时持有全量渲染 buffer 与 artifact PIL 页导致双倍内存 OOM。
        """
        artifact_pages = sorted({box.page for box in artifact_boxes if box.page >= 1})
        return self._render_pages(filename, artifact_pages, zoom_map=zoom_map)

    def _render_pages(
        self,
        filename: Union[str, bytes, Path],
        pages: Sequence[int],
        *,
        zoom_map: dict[int, float] | None = None,
    ) -> dict[int, Image.Image]:
        """按需把指定页（1-based）从 fitz 渲染为 PIL，其余页零开销。"""
        if not pages:
            return {}
        fitz = self._import_fitz()
        doc = fitz.open(stream=filename, filetype="pdf") if isinstance(filename, bytes) else fitz.open(str(filename))
        try:
            def _page_image(page_num: int) -> Image.Image:
                zoom = float(zoom_map.get(page_num, 2.0) if zoom_map else 2.0)
                pix = doc.load_page(page_num - 1).get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                return Image.fromarray(img[:, :, :3] if pix.n == 4 else img)

            return {page_num: _page_image(page_num) for page_num in pages}
        finally:
            doc.close()

    # ------------------------------------------------------------------
    # 公式识别（pix2text-mfr）：layout equation 区域 → LaTeX box
    # ------------------------------------------------------------------

    @classmethod
    def _collect_equation_regions(cls, page_layout: Sequence[Sequence[dict[str, Any]]]) -> list[dict[str, Any]]:
        """从 page_layout 收集 equation 区域（PDF 点坐标，1-based 页码）。

        page_layout 是 apply_layouts 返回的逐页 normalized_layouts，type 大小写
        不稳定（YOLOv10 类定义是 "Equation"、forward 输出实测为小写 "equation"），
        统一 lower() 比较。同时做嵌套去重：layout 模型对同一公式常同时给出
        整块框与逐行拆分框，子区域 ≥80% 面积嵌套进另一区域时丢弃子区域。

        表题/图题行常被误检成 equation（表题里满是斜体数学符号，如
        "不同m,n,r,OS下算法迭代步数比"）：与 caption 类版面区域 ≥70% 重叠的
        equation 区域直接跳过，避免表题被识别成乱 LaTeX（重复且丢表题）。
        """
        regions: list[dict[str, Any]] = []
        for page_index, layouts in enumerate(page_layout):
            caption_layouts = [
                {
                    "page": page_index + 1,
                    "x0": float(item["x0"]),
                    "x1": float(item["x1"]),
                    "top": float(item["top"]),
                    "bottom": float(item["bottom"]),
                }
                for item in (layouts or [])
                if "caption" in str(item.get("type", "")).lower()
            ]
            for item in layouts or []:
                if str(item.get("type", "")).lower() != "equation":
                    continue
                if float(item.get("score", 0.0)) < cls.FORMULA_LAYOUT_SCORE_THR:
                    continue
                region = {
                    "page": page_index + 1,
                    "x0": float(item["x0"]),
                    "x1": float(item["x1"]),
                    "top": float(item["top"]),
                    "bottom": float(item["bottom"]),
                }
                if any(
                    cls._region_contain_ratio(region, caption) >= cls.FORMULA_BOX_CONTAIN_RATIO
                    for caption in caption_layouts
                ):
                    continue
                regions.append(region)
        return cls._dedupe_equation_regions(regions)

    @classmethod
    def _dedupe_equation_regions(cls, regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """嵌套区域去重：保留外围大框（整块公式），丢弃被包住 ≥80% 的逐行碎框。"""
        kept: list[dict[str, Any]] = []
        for region in regions:
            if any(
                other is not region
                and other["page"] == region["page"]
                and cls._region_contain_ratio(region, other) >= cls.FORMULA_REGION_DEDUPE_RATIO
                for other in regions
            ):
                continue
            kept.append(region)
        return kept

    @staticmethod
    def _region_contain_ratio(inner: dict[str, Any], outer: dict[str, Any]) -> float:
        """inner 面积落入 outer 的比例（同页局部坐标；跨页恒为 0）。"""
        if inner["page"] != outer["page"]:
            return 0.0
        overlap_w = min(inner["x1"], outer["x1"]) - max(inner["x0"], outer["x0"])
        overlap_h = min(inner["bottom"], outer["bottom"]) - max(inner["top"], outer["top"])
        if overlap_w <= 0 or overlap_h <= 0:
            return 0.0
        inner_area = max((inner["x1"] - inner["x0"]) * (inner["bottom"] - inner["top"]), 1e-6)
        return (overlap_w * overlap_h) / inner_area

    @staticmethod
    def _box_in_region_ratio(box: DeepDocPdfBox, region: dict[str, Any]) -> float:
        """box 面积落入公式区域的比例。"""
        overlap_w = min(box.x1, region["x1"]) - max(box.x0, region["x0"])
        overlap_h = min(box.bottom, region["bottom"]) - max(box.top, region["top"])
        if overlap_w <= 0 or overlap_h <= 0:
            return 0.0
        box_area = max((box.x1 - box.x0) * (box.bottom - box.top), 1e-6)
        return (overlap_w * overlap_h) / box_area

    def _recognize_equation_regions(
        self,
        filename: Union[str, bytes, Path],
        page_layout: Sequence[Sequence[dict[str, Any]]],
        *,
        zoom_map: dict[int, float] | None = None,
        enabled: bool | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """equation 区域 → LaTeX 识别结果 + 元信息。

        返回的每个 result dict 含 page/bbox/latex/inline/text（text 已带 $ 格式），
        供 _apply_formula_boxes 合成 box。模型缺失/识别失败均软降级，不抛错。
        """
        if enabled is False:
            return [], {"source": "disabled", "equation_regions": 0}
        regions = self._collect_equation_regions(page_layout)
        if not regions:
            return [], {"source": "none", "equation_regions": 0}
        status = get_formula_model_status()
        if not status["available"]:
            # 回退必须可见（历史教训：xgboost 静默回退 4 个月无人知）。
            logger.warning(
                "DeepDoc 公式识别模型不可用，公式区域保留 OCR 文本（公式输出质量下降）",
                model_dir=status["model_dir"],
                missing=", ".join(status["missing"]),
                equation_regions=len(regions),
            )
            return [], {
                "source": "skipped_model_unavailable",
                "equation_regions": len(regions),
                "missing": status["missing"],
            }
        recognizer = load_formula_recognizer()

        page_images = self._render_pages(
            filename, sorted({region["page"] for region in regions}), zoom_map=zoom_map
        )
        results: list[dict[str, Any]] = []
        failed = 0
        for region in regions:
            page_image = page_images.get(region["page"])
            if page_image is None:
                failed += 1
                continue
            zoom = float(zoom_map.get(region["page"], 2.0) if zoom_map else 2.0)
            crop = self._crop_formula_image(page_image, region, zoom)
            if crop is None:
                failed += 1
                continue
            try:
                latex = recognizer.recognize(crop)
            except Exception as exc:
                # 单个公式失败不阻断整篇解析；该区域保留 OCR 碎片。
                logger.warning(
                    "DeepDoc 公式识别失败（该区域保留 OCR 文本）",
                    error=str(exc),
                    page=region["page"],
                )
                failed += 1
                continue
            if not latex:
                failed += 1
                continue
            inline = (region["x1"] - region["x0"]) < self.FORMULA_INLINE_WIDTH_RATIO * page_image.size[0] / zoom
            results.append(
                {
                    **region,
                    "latex": latex,
                    "inline": inline,
                    "text": f"${latex}$" if inline else f"$$\n{latex}\n$$",
                }
            )
        meta = {
            "source": "pix2text_mfr",
            "precision": recognizer.precision,
            "equation_regions": len(regions),
            "recognized": len(results),
            "failed": failed,
        }
        logger.info(
            "DeepDoc 公式识别完成",
            equation_regions=len(regions),
            recognized=len(results),
            failed=failed,
            precision=recognizer.precision,
        )
        return results, meta

    def _crop_formula_image(
        self,
        page_image: Image.Image,
        region: dict[str, Any],
        zoom: float,
    ) -> np.ndarray | None:
        """按 PDF 点坐标（含 padding）从渲染页图裁出公式区域 numpy 图。"""
        pad = self.FORMULA_CROP_PADDING
        img_h, img_w = page_image.size[1], page_image.size[0]
        x0 = max(0, int((region["x0"] - pad) * zoom))
        x1 = min(img_w, int((region["x1"] + pad) * zoom))
        top = max(0, int((region["top"] - pad) * zoom))
        bottom = min(img_h, int((region["bottom"] + pad) * zoom))
        if x1 - x0 < 12 or bottom - top < 8:
            return None
        return np.asarray(page_image)[top:bottom, x0:x1]

    def _apply_formula_boxes(
        self,
        all_boxes: List[DeepDocPdfBox],
        formula_results: Sequence[dict[str, Any]],
    ) -> tuple[List[DeepDocPdfBox], int]:
        """把公式识别结果合成为文本 box，并剔除区域内的 OCR 碎片框。

        合成 box 的 layout_type 沿用 "figure"（与公式内 OCR 碎片现状一致，
        _text_merge 只横向合并 {"text",""}，figure 框独立成行不被并入段落），
        layoutno 用 "equation-synth-N" 前缀：_collect_artifact_boxes 据此把
        公式 box 挡在 artifact 流外（公式不是图片，无需 crop/判真）。
        col_id 取被剔除碎片框的多数列（双栏论文阅读顺序依赖列号）。
        """
        kept: List[DeepDocPdfBox] = []
        # 先把所有区域内碎片框标记待剔除；被剔除框的 col_id 用于合成 box 列号。
        # caption/title 框不剔：layout 常把公式编号行（如 "(19)"）检成 equation，
        # 其区域与表题/图题行高度重叠，误剔会把表题从 MD 里整行抹掉（实测回
        # 归：一份论文 6 个表题全部消失）。剔除目标只是公式区内部的 OCR 碎片。
        removed: List[DeepDocPdfBox] = []
        for box in all_boxes:
            layout_type = (box.layout_type or "").lower()
            layoutno = (box.layoutno or "").lower()
            if (
                layout_type == "table"
                or "caption" in layout_type
                or "caption" in layoutno
                or layout_type == "title"
            ):
                kept.append(box)
                continue
            if any(
                self._box_in_region_ratio(box, region) >= self.FORMULA_BOX_CONTAIN_RATIO
                for region in formula_results
            ):
                removed.append(box)
                continue
            kept.append(box)
        for index, result in enumerate(formula_results):
            col_counter: dict[int, int] = {}
            for box in removed:
                if self._box_in_region_ratio(box, result) >= self.FORMULA_BOX_CONTAIN_RATIO:
                    col_counter[box.col_id] = col_counter.get(box.col_id, 0) + 1
            col_id = max(col_counter, key=col_counter.get) if col_counter else 0
            kept.append(
                DeepDocPdfBox(
                    page=result["page"],
                    x0=result["x0"],
                    x1=result["x1"],
                    top=result["top"],
                    bottom=result["bottom"],
                    text=result["text"],
                    col_id=col_id,
                    position_tag=self._line_tag(
                        {
                            "page_number": result["page"],
                            "x0": result["x0"],
                            "x1": result["x1"],
                            "top": result["top"],
                            "bottom": result["bottom"],
                        }
                    ),
                    positions=[
                        [
                            float(result["page"]),
                            result["x0"],
                            result["x1"],
                            result["top"],
                            result["bottom"],
                        ]
                    ],
                    layout_type="figure",
                    layoutno=f"equation-synth-{index}",
                )
            )
        # 合成 box 插回原 all_boxes 顺序位置不必要：下游统一按 (page, col, top, x0) 排序。
        return kept, len(removed)

    @staticmethod
    def _build_table_regions_metadata(
        artifacts: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        table_regions: list[dict[str, Any]] = []
        ordered_tables = sorted(
            artifacts.get("tables", []),
            key=lambda table: (
                min(table.get("pages") or [0]),
                float((table.get("bbox") or {}).get("top", 0.0)),
                float((table.get("bbox") or {}).get("x0", 0.0)),
            ),
        )
        per_page_index: dict[int, int] = {}
        for table in ordered_tables:
            table_structure = dict(table.get("table_structure") or {})
            structured_boxes = list(table_structure.get("structured_boxes") or [])
            pages = list(table.get("pages") or [])
            first_page = min(pages) if pages else 0
            region_index_on_page = per_page_index.get(first_page, 0)
            per_page_index[first_page] = region_index_on_page + 1
            member_texts = [
                str(member.get("text", "")).strip()
                for member in table.get("members", [])
                if str(member.get("text", "")).strip()
            ]
            row_ids = sorted({str(box.get("R")) for box in structured_boxes if box.get("R") is not None})
            col_ids = sorted({str(box.get("C")) for box in structured_boxes if box.get("C") is not None})
            # 成员框（页级 bbox）供正文剔除按框匹配：联合 bbox 应用到 pages 全部页
            # 在跨页/误检时不可信（见 _drop_boxes_consumed_by_tables）。
            member_bboxes = [
                {
                    "page": int(member.get("page", 0) or 0),
                    "x0": float(member.get("x0", 0.0)),
                    "x1": float(member.get("x1", 0.0)),
                    "top": float(member.get("top", 0.0)),
                    "bottom": float(member.get("bottom", 0.0)),
                }
                for member in table.get("members", [])
            ]
            table_regions.append(
                {
                    "artifact_id": table.get("artifact_id"),
                    "pages": pages,
                    "page_start": first_page,
                    "region_index_on_page": region_index_on_page,
                    "bbox": dict(table.get("bbox") or {}),
                    "caption": table.get("caption", ""),
                    "text": table.get("text", ""),
                    "member_texts": member_texts,
                    "member_text_count": len(member_texts),
                    "member_bboxes": member_bboxes,
                    "html": table.get("html", ""),
                    "html_source": table.get("html_source", ""),
                    "table_structure_source": table_structure.get("source", ""),
                    "prediction_pages": int(table_structure.get("prediction_pages") or 0),
                    "prediction_count": int(table_structure.get("prediction_count") or 0),
                    "row_count": len(row_ids),
                    "column_count": len(col_ids),
                    "structured_box_count": len(structured_boxes),
                    "structured_boxes": structured_boxes,
                    "has_image": bool(table.get("has_image")),
                    "caption_boxes": list(table.get("caption_boxes") or []),
                }
            )
        return table_regions

    @staticmethod
    def _build_figure_regions_metadata(
        artifacts: dict[str, list[dict[str, Any]]],
        *,
        raster_images_by_page: dict[int, list[dict[str, Any]]] | None = None,
    ) -> list[dict[str, Any]]:
        """构建 figure regions。

        ``raster_images_by_page`` 提供时（full 流水线始终提供），figure 组必须与
        该组所在某页的 PDF 内嵌栅格图有实际重叠才保留。layout 模型常把行间
        公式区标成 figure，公式是矢量绘制、没有内嵌位图，据此把公式组降级
        （不进 reading_order、不生成 ![Figure N:] 占位符），避免正文公式推导
        被占位符切碎（实测一份论文里 Figure 2 占位符在公式区重复出现 7 次）。
        未提供时（调用方拿不到栅格信息，如旧测试）退回旧行为按 has_image 判。
        """
        figure_regions: list[dict[str, Any]] = []
        ordered_figures = sorted(
            artifacts.get("figures", []),
            key=lambda figure: (
                min(figure.get("pages") or [0]),
                float((figure.get("bbox") or {}).get("top", 0.0)),
                float((figure.get("bbox") or {}).get("x0", 0.0)),
            ),
        )
        per_page_index: dict[int, int] = {}
        dropped_no_image = 0
        for figure in ordered_figures:
            image = figure.get("image")
            image_blobs = list(getattr(image, "blobs", [])) if image is not None else []
            keep = bool(image_blobs)
            if keep and raster_images_by_page:
                keep = any(
                    PdfArtifactExtractor.bbox_overlap_ratio(
                        dict(figure.get("bbox") or {}),
                        raster,
                    ) > 0.05
                    for page in (figure.get("pages") or [])
                    for raster in (raster_images_by_page.get(int(page)) or [])
                )
            if not keep:
                dropped_no_image += 1
                continue
            pages = list(figure.get("pages") or [])
            first_page = min(pages) if pages else 0
            region_index_on_page = per_page_index.get(first_page, 0)
            per_page_index[first_page] = region_index_on_page + 1
            member_texts = [
                str(member.get("text", "")).strip()
                for member in figure.get("members", [])
                if str(member.get("text", "")).strip()
            ]
            figure_regions.append(
                {
                    "artifact_id": figure.get("artifact_id"),
                    "pages": pages,
                    "page_start": first_page,
                    "region_index_on_page": region_index_on_page,
                    "bbox": dict(figure.get("bbox") or {}),
                    "caption": figure.get("caption", ""),
                    "text": figure.get("text", ""),
                    "member_texts": member_texts,
                    "member_text_count": len(member_texts),
                    "has_image": True,
                    "image_blobs": image_blobs,
                    "caption_boxes": list(figure.get("caption_boxes") or []),
                }
            )
        if dropped_no_image:
            logger.info(
                "DeepDoc figure 无内嵌栅格图组已降级（不生成占位符）",
                dropped_count=dropped_no_image,
            )
        return figure_regions

    @staticmethod
    def _drop_boxes_consumed_by_tables(
        text_boxes: Sequence[DeepDocPdfBox],
        table_regions: Sequence[dict[str, Any]],
        *,
        overlap_threshold: float = 0.6,
    ) -> list[DeepDocPdfBox]:
        """剔除「被保留 table artifact 的成员框」覆盖的正文框（同页 IoMin > threshold）。

        对齐上游 _extract_table_figure 的标签语义：上游只把 layout_type=="table"
        的框 pop 出正文流，正文不因几何误判被删。我们的等价物是按**成员框逐框
        匹配**（成员即 layout 打标的 table 框），而不是把组联合 bbox 应用到
        region["pages"] 的全部页——联合 bbox 在误检时不具备整页代表性（实测
        误标题注曾把表组撑成 6 页近全页 bbox，几何剔除整章删除 §1-§3）。
        region 缺 member_bboxes（旧调用方）时回退联合 bbox 口径。
        表格文字已随 [TABLE]/HTML entry 进入 reading_order，留在正文会重复两份；
        质量门降级的假表不进 table_regions，其文本自然保留正文。"""
        if not text_boxes or not table_regions:
            return list(text_boxes)
        member_bboxes_by_page: dict[int, list[dict[str, Any]]] = {}
        fallback_regions_by_page: dict[int, list[dict[str, Any]]] = {}
        for region in table_regions:
            member_bboxes = list(region.get("member_bboxes") or [])
            if member_bboxes:
                for member in member_bboxes:
                    member_bboxes_by_page.setdefault(int(member.get("page", 0)), []).append(member)
                continue
            bbox = region.get("bbox") or {}
            if not bbox:
                continue
            for page in region.get("pages") or [region.get("page_start")]:
                if page is None:
                    continue
                fallback_regions_by_page.setdefault(int(page), []).append(bbox)
        kept: list[DeepDocPdfBox] = []
        for box in text_boxes:
            page = int(box.page)
            candidates_by_page = member_bboxes_by_page.get(page) or fallback_regions_by_page.get(page)
            if candidates_by_page and any(
                PdfArtifactExtractor.bbox_overlap_ratio(
                    {
                        "x0": box.x0,
                        "x1": box.x1,
                        "top": box.top,
                        "bottom": box.bottom,
                    },
                    region_bbox,
                )
                > overlap_threshold
                for region_bbox in candidates_by_page
            ):
                continue
            kept.append(box)
        return kept

    @staticmethod
    def _drop_attached_caption_boxes(
        text_boxes: Sequence[DeepDocPdfBox],
        table_regions: Sequence[dict[str, Any]],
        figure_regions: Sequence[dict[str, Any]],
        *,
        overlap_threshold: float = 0.5,
    ) -> list[DeepDocPdfBox]:
        """把已挂载到表/图组的题注框从正文流剔除（对齐上游 caption 框出正文流）。

        题注文本已随 table/figure entry 的 caption 字段进入 reading_order，留在
        正文会重复（且与组内公式编号混排）。只剔「挂载成功」的题注坐标：未挂载
        的题注（跨页/悬空/误标框）保留正文，绝不按 layout_type 几何批量删——
        上游的 caption pop 也只针对真实挂载的那几个框。"""
        caption_bboxes_by_page: dict[int, list[dict[str, Any]]] = {}
        for regions in (table_regions, figure_regions):
            for region in regions:
                for cap in region.get("caption_boxes") or []:
                    caption_bboxes_by_page.setdefault(int(cap.get("page", 0)), []).append(cap)
        if not caption_bboxes_by_page or not text_boxes:
            return list(text_boxes)
        kept: list[DeepDocPdfBox] = []
        for box in text_boxes:
            caps = caption_bboxes_by_page.get(int(box.page))
            if caps and any(
                PdfArtifactExtractor.bbox_overlap_ratio(
                    {
                        "x0": box.x0,
                        "x1": box.x1,
                        "top": box.top,
                        "bottom": box.bottom,
                    },
                    {"x0": cap["x0"], "x1": cap["x1"], "top": cap["top"], "bottom": cap["bottom"]},
                )
                > overlap_threshold
                for cap in caps
            ):
                continue
            kept.append(box)
        return kept

    @staticmethod
    def _build_reading_order_metadata(
        text_boxes: Sequence[DeepDocPdfBox],
        table_regions: Sequence[dict[str, Any]],
        figure_regions: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []

        for box in text_boxes:
            bbox = {
                "x0": float(box.x0),
                "x1": float(box.x1),
                "top": float(box.top),
                "bottom": float(box.bottom),
            }
            entries.append(
                {
                    "kind": "text",
                    "page": int(box.page),
                    "col_id": int(box.col_id),
                    "bbox": bbox,
                    "text": box.text,
                    "layout_type": box.layout_type or "text",
                    "position_tag": box.position_tag,
                    "source_id": box.position_tag or box.line_tag(),
                }
            )

        for region in table_regions:
            bbox = dict(region.get("bbox") or {})
            page = int(region.get("page_start") or (min(region.get("pages") or [1])))
            entries.append(
                {
                    "kind": "table",
                    "page": page,
                    "bbox": bbox,
                    "text": str(region.get("text", "")),
                    "caption": str(region.get("caption", "")),
                    "layout_type": "table",
                    "artifact_id": region.get("artifact_id"),
                    "source_id": region.get("artifact_id"),
                    "html": region.get("html", ""),
                    "html_source": region.get("html_source", ""),
                    "table_structure_source": region.get("table_structure_source", ""),
                }
            )

        for region in figure_regions:
            bbox = dict(region.get("bbox") or {})
            page = int(region.get("page_start") or (min(region.get("pages") or [1])))
            artifact_id = str(region.get("artifact_id") or "")
            entries.append(
                {
                    "kind": "figure",
                    "page": page,
                    "bbox": bbox,
                    "text": str(region.get("text", "")),
                    "caption": str(region.get("caption", "")),
                    "layout_type": "figure",
                    "artifact_id": artifact_id,
                    "source_id": artifact_id,
                    "image_placeholder": f"__FIGURE_URL__{artifact_id}__" if artifact_id else "",
                }
            )

        ordered = sorted(
            entries,
            key=lambda item: (
                int(item.get("page", 0)),
                int(item.get("col_id", 0)),
                float((item.get("bbox") or {}).get("top", 0.0)),
                float((item.get("bbox") or {}).get("x0", 0.0)),
                0 if item.get("kind") == "text" else 1 if item.get("kind") == "table" else 2,
            ),
        )

        page_counters: dict[int, int] = {}
        for global_index, entry in enumerate(ordered):
            page = int(entry.get("page", 0))
            order_on_page = page_counters.get(page, 0)
            page_counters[page] = order_on_page + 1
            entry["global_order"] = global_index
            entry["order_on_page"] = order_on_page
        return ordered

    @staticmethod
    def _reading_order_entry_text(entry: dict[str, Any]) -> str:
        kind = str(entry.get("kind", "text"))
        if kind == "text":
            return str(entry.get("text", "")).strip()
        if kind == "table":
            caption = str(entry.get("caption", "")).strip()
            # TSR 识别出的 HTML 表格直接内联（对齐上游 return_html 行为）；
            # 无 HTML 时回退 [TABLE] + 成员文本，保证可读。
            html = str(entry.get("html", "")).strip()
            if html:
                parts = [part for part in [caption, html] if part]
                return "\n\n".join(parts)
            text = str(entry.get("text", "")).strip()
            prefix = "[TABLE]"
            parts = [part for part in [prefix, caption, text] if part]
            return "\n".join(parts).strip()
        if kind == "figure":
            caption = str(entry.get("caption", "")).strip()
            artifact_id = str(entry.get("source_id", "") or "")
            placeholder = str(entry.get("image_placeholder", "") or "")
            alt = caption or f"Figure {artifact_id}" if artifact_id else "Figure"
            if placeholder:
                return f"![{alt}]({placeholder})"
            # 没有占位符时回退到纯文本标记，保证即使上传失败也有可读内容
            text = str(entry.get("text", "")).strip()
            parts = [part for part in ["[FIGURE]", caption, text] if part]
            return "\n".join(parts).strip()
        return str(entry.get("text", "")).strip()

    @classmethod
    def _build_structured_chunks(
        cls,
        reading_order: Sequence[dict[str, Any]],
        *,
        chunk_size: int,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        chunks: list[str] = []
        chunk_structure: list[dict[str, Any]] = []
        current_parts: list[str] = []
        current_entries: list[dict[str, Any]] = []
        current_length = 0

        def flush() -> None:
            nonlocal current_parts, current_entries, current_length
            if not current_parts:
                return
            chunk_text = "\n\n".join(current_parts).strip()
            if not chunk_text:
                current_parts = []
                current_entries = []
                current_length = 0
                return
            chunks.append(chunk_text)
            chunk_structure.append(
                {
                    "chunk_index": len(chunks) - 1,
                    "entry_kinds": [str(entry.get("kind", "")) for entry in current_entries],
                    "entry_source_ids": [str(entry.get("source_id", "")) for entry in current_entries],
                    "pages": sorted({int(entry.get("page", 0)) for entry in current_entries}),
                    "entry_count": len(current_entries),
                }
            )
            current_parts = []
            current_entries = []
            current_length = 0

        for entry in reading_order:
            block = cls._reading_order_entry_text(entry)
            if not block:
                continue
            addition = len(block) + (2 if current_parts else 0)
            if current_parts and current_length + addition > chunk_size:
                flush()
            current_parts.append(block)
            current_entries.append(dict(entry))
            current_length += len(block) + (2 if len(current_parts) > 1 else 0)

        flush()
        if chunks:
            return chunks, chunk_structure
        fallback = cls._chunk_blocks(
            [cls._reading_order_entry_text(entry) for entry in reading_order if cls._reading_order_entry_text(entry)],
            chunk_size=chunk_size,
        )
        return fallback, []

    @staticmethod
    def _chars_by_page(boxes: Sequence[DeepDocPdfBox]) -> dict[int, int]:
        """按页统计 boxes 文本字符数，用于分阶段诊断整页内容丢失。"""
        totals: dict[int, int] = {}
        for box in boxes:
            page = int(box.page)
            totals[page] = totals.get(page, 0) + len(str(box.text or ""))
        return totals

    @staticmethod
    def _reading_order_entries_by_page(reading_order: Sequence[dict[str, Any]]) -> dict[int, int]:
        counts: dict[int, int] = {}
        for entry in reading_order:
            page = int(entry.get("page", 0))
            counts[page] = counts.get(page, 0) + 1
        return counts

    @staticmethod
    def _collect_artifact_boxes(
        all_boxes: Sequence[DeepDocPdfBox],
        chunk_boxes: Sequence[DeepDocPdfBox],
    ) -> list[DeepDocPdfBox]:
        kept_pages = {box.page for box in chunk_boxes}
        if not kept_pages:
            kept_pages = {box.page for box in all_boxes}
        return [
            box
            for box in all_boxes
            # layoutno "equation-*"（公式内 OCR 碎片 + 公式识别合成 box）不是图片
            # artifact：进 artifact 流只会被栅格判真丢弃，白付 crop 成本。
            if box.page in kept_pages
            and not (box.layoutno or "").lower().startswith("equation")
            and (box.text.strip() or (box.layout_type or "").lower() in {"table", "figure", "figure caption", "table caption"})
        ]
