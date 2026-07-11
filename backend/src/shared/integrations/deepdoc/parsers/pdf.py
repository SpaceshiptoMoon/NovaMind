from __future__ import annotations

# Adapted around RAGFlow deepdoc/parser/pdf_parser.py class layout.

from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
import logging
import re
from statistics import median
from typing import Any, Dict, List, Sequence, Union

import numpy as np
import pdfplumber
from PIL import Image

from src.shared.integrations.deepdoc.compat import MAXIMUM_PAGE_NUMBER
from src.shared.integrations.deepdoc.core.models import DeepDocParseResult
from src.shared.integrations.deepdoc.page_filter import PageNoiseFilter
from src.shared.integrations.deepdoc.pdf_artifacts import PdfArtifactExtractor
from src.shared.integrations.deepdoc.pdf_layout import PdfLayoutExtractor
from src.shared.integrations.deepdoc.parsers.pdf_plain import RAGFlowPlainPdfParser
from src.shared.integrations.deepdoc.updown_concat import UpDownConcatMerger
from src.shared.integrations.deepdoc.vision_runtime import get_vision_health_status


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

    def as_tagged_text(self) -> str:
        return f"{self.position_tag or self.line_tag()}{self.text}"

    def line_tag(self) -> str:
        return f"@@{self.page}\t{self.x0:.1f}\t{self.x1:.1f}\t{self.top:.1f}\t{self.bottom:.1f}##"


class RAGFlowPdfParser:
    """Vendored PDF parser facade modeled after RAGFlowPdfParser."""

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
            from src.shared.integrations.deepdoc.vision.layout_recognizer import LayoutRecognizer

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
    def _is_garbled_by_font_encoding(cls, page_chars):
        if not page_chars:
            return False
        suspicious = 0
        sample_size = min(len(page_chars), 200)
        for char in page_chars[:sample_size]:
            text = str(char.get("text", "") or "")
            fontname = char.get("fontname", "")
            if cls._has_subset_font_prefix(fontname) and text and all(ord(ch) < 128 for ch in text):
                suspicious += 1
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
        pdf_mode: str = "layout",
        chunk_size: int = 1000,
    ) -> DeepDocParseResult:
        if pdf_mode == "plain":
            return self._parse_plain(filename, chunk_size=chunk_size)
        if pdf_mode == "layout":
            return self._parse_layout(filename, chunk_size=chunk_size)
        if pdf_mode == "vision":
            return self._parse_vision(filename, chunk_size=chunk_size)
        raise ValueError(f"Unsupported DeepDoc PDF mode: {pdf_mode}")

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

    def _merge_vertical_boxes(self, boxes: Sequence[DeepDocPdfBox]) -> List[DeepDocPdfBox]:
        if not boxes:
            return []

        mean_height = median(max(1.0, box.bottom - box.top) for box in boxes)
        ordered_boxes = self.sort_x_by_page(boxes, threshold=max(8.0, mean_height * 0.8))
        merged: List[DeepDocPdfBox] = []
        current: DeepDocPdfBox | None = None

        for box in ordered_boxes:
            if current is None:
                current = DeepDocPdfBox(**asdict(box))
                continue

            if not self._should_merge_boxes(current, box, mean_height):
                merged.append(current)
                current = DeepDocPdfBox(**asdict(box))
                continue

            merged_text = (current.text.rstrip() + " " + box.text.lstrip()).strip()
            merged_positions = list(current.positions or [])
            if box.positions:
                merged_positions.extend(box.positions)
            current = DeepDocPdfBox(
                page=current.page,
                x0=min(current.x0, box.x0),
                x1=max(current.x1, box.x1),
                top=current.top,
                bottom=box.bottom,
                text=merged_text,
                col_id=current.col_id,
                position_tag=current.position_tag,
                positions=merged_positions,
            )

        if current is not None:
            merged.append(current)
        return merged

    def _should_merge_boxes(self, upper: DeepDocPdfBox, lower: DeepDocPdfBox, mean_height: float) -> bool:
        if upper.page != lower.page or upper.col_id != lower.col_id:
            return False
        if (upper.layout_type or "") != (lower.layout_type or ""):
            return False
        if not upper.text.strip() or not lower.text.strip():
            return False

        vertical_gap = lower.top - upper.bottom
        if vertical_gap > mean_height * 1.5:
            return False

        overlap = max(0.0, min(upper.x1, lower.x1) - max(upper.x0, lower.x0))
        min_width = max(1.0, min(upper.x1 - upper.x0, lower.x1 - lower.x0))
        if overlap / min_width < 0.3:
            return False

        if self.proj_match(upper.text) or self.proj_match(lower.text):
            return False

        concatting_features = [
            upper.text.strip()[-1] in ",;:'\"，、“；：",
            len(upper.text.strip()) > 1 and upper.text.strip()[-2] in ",;:'\"，‘“、；：",
            bool(lower.text.strip()) and lower.text.strip()[0] in "。；：？！?》】）),，、：",
        ]
        break_features = [
            upper.text.strip()[-1] in "。？！?",
            vertical_gap > mean_height * 1.2,
        ]
        detach_features = [upper.x1 < lower.x0, upper.x0 > lower.x1]

        return not ((any(break_features) and not any(concatting_features)) or any(detach_features))

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

    def _text_merge(self, boxes):
        return list(boxes)

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
        return boxes

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
        return re.sub(r"@@[\t0-9.-]+?##", "", text)

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

    def _parse_layout(
        self,
        filename: Union[str, bytes, Path],
        *,
        chunk_size: int,
    ) -> DeepDocParseResult:
        plain_sections, _, outlines = self._plain_parser(filename)
        boxes = self.parse_into_bboxes(filename)
        merged_boxes, merge_strategy = self._merge_vertical_boxes_with_strategy(boxes)
        filtered_boxes, filter_meta = self._filter_boxes_with_meta(merged_boxes or boxes, total_pages=len({box.page for box in boxes}))
        chunk_boxes = filtered_boxes or merged_boxes or boxes
        page_images = self._render_page_images(filename)
        artifacts = self._extract_artifacts(chunk_boxes, page_images=page_images, zoom=2.0)
        table_regions = self._build_table_regions_metadata(artifacts)
        figure_regions = self._build_figure_regions_metadata(artifacts)
        reading_order = self._build_reading_order_metadata(
            chunk_boxes,
            table_regions,
            figure_regions,
        )
        tagged_lines = [box.as_tagged_text() for box in chunk_boxes]
        full_text = "\n".join(tagged_lines).strip()
        chunks, chunk_structure = self._build_structured_chunks(reading_order, chunk_size=chunk_size)
        detected_columns = max((box.col_id for box in boxes), default=0) + 1 if boxes else 1
        return DeepDocParseResult(
            full_text=full_text,
            chunks=chunks,
            metadata={
                "parser": "deepdoc",
                "file_type": "pdf",
                "pdf_mode": "layout",
                "pages": len({box.page for box in boxes}),
                "detected_columns": detected_columns,
                "merged_block_count": len(chunk_boxes),
                "paragraph_merge_strategy": merge_strategy,
                "page_filter": filter_meta,
                "artifacts": artifacts,
                "table_regions": table_regions,
                "figure_regions": figure_regions,
                "reading_order": reading_order,
                "chunk_structure": chunk_structure,
                "text_concat_model": self._updown_concat.model_status(),
                "outlines": outlines,
                "plain_sections": plain_sections,
                "bboxes": [asdict(box) for box in boxes],
                "merged_bboxes": [asdict(box) for box in chunk_boxes],
                "source": "ragflow-adapted",
                "parser_class": "RAGFlowPdfParser",
            },
        )

    def _parse_vision(
        self,
        filename: Union[str, bytes, Path],
        *,
        chunk_size: int,
    ) -> DeepDocParseResult:
        plain_sections, _, outlines = self._plain_parser(filename)
        image_list, ocr_pages, layout_pages, vision_meta = self._extract_vision_pages(filename)
        layout_boxes, page_layout = self._get_layout_recognizer()(
            image_list,
            ocr_pages,
            scale_factor=2,
            layouts=layout_pages,
            drop=False,
        )

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
            )
            for box in layout_boxes
        ]
        text_boxes = [box for box in all_boxes if box.text.strip()]
        merged_boxes, merge_strategy = self._merge_vertical_boxes_with_strategy(text_boxes)
        filtered_boxes, filter_meta = self._filter_boxes_with_meta(merged_boxes or text_boxes, total_pages=len(image_list))
        chunk_boxes = filtered_boxes or merged_boxes or text_boxes
        artifact_boxes = self._collect_artifact_boxes(all_boxes, chunk_boxes)
        page_images = {
            index + 1: Image.fromarray(image)
            for index, image in enumerate(image_list)
        }
        artifacts = self._extract_artifacts(artifact_boxes, page_images=page_images, zoom=2.0)
        table_regions = self._build_table_regions_metadata(artifacts)
        figure_regions = self._build_figure_regions_metadata(artifacts)
        reading_order = self._build_reading_order_metadata(
            chunk_boxes,
            table_regions,
            figure_regions,
        )
        tagged_lines = [box.as_tagged_text() for box in chunk_boxes]
        full_text = "\n".join(tagged_lines).strip()
        chunks, chunk_structure = self._build_structured_chunks(reading_order, chunk_size=chunk_size)
        return DeepDocParseResult(
            full_text=full_text,
            chunks=chunks,
            metadata={
                "parser": "deepdoc",
                "file_type": "pdf",
                "pdf_mode": "vision",
                "pages": len(image_list),
                "outlines": outlines,
                "plain_sections": plain_sections,
                "vision_strategy": vision_meta["vision_strategy"],
                "layout_source": vision_meta["layout_source"],
                "layout_model_error": vision_meta.get("layout_model_error"),
                "paragraph_merge_strategy": merge_strategy,
                "page_filter": filter_meta,
                "artifacts": artifacts,
                "table_regions": table_regions,
                "figure_regions": figure_regions,
                "reading_order": reading_order,
                "chunk_structure": chunk_structure,
                "text_concat_model": self._updown_concat.model_status(),
                "ocr_sources": self._collect_ocr_sources(ocr_pages),
                "layout_bboxes": [asdict(box) for box in all_boxes],
                "merged_bboxes": [asdict(box) for box in chunk_boxes],
                "page_layout": page_layout,
                "source": "ragflow-adapted",
                "parser_class": "RAGFlowPdfParser",
            },
        )

    def _extract_vision_pages(
        self,
        filename: Union[str, bytes, Path],
    ) -> tuple[list[np.ndarray], list[list[dict[str, Any]]], list[list[dict[str, Any]]], dict[str, Any]]:
        fitz = self._import_fitz()
        doc = fitz.open(stream=filename, filetype="pdf") if isinstance(filename, bytes) else fitz.open(str(filename))
        image_list: list[np.ndarray] = []
        ocr_pages: list[list[dict[str, Any]]] = []
        zoom = 2
        try:
            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n == 4:
                    img = img[:, :, :3]
                image_list.append(img)

                blocks = self._extract_fitz_blocks(page)
                if not blocks:
                    blocks = self._extract_ocr_blocks(img, page, page_index, zoom)
                if not blocks:
                    blocks = self._fallback_plain_page_blocks(page, page_index)
                ocr_pages.append(blocks)
        finally:
            doc.close()

        layout_pages, layout_meta = self._resolve_layout_pages(
            image_list=image_list,
            ocr_pages=ocr_pages,
            zoom=zoom,
        )
        layout_meta["vision_strategy"] = self._build_vision_strategy(
            self._collect_ocr_sources(ocr_pages),
            layout_meta["layout_source"],
        )
        return image_list, ocr_pages, layout_pages, layout_meta

    def _resolve_layout_pages(
        self,
        *,
        image_list: list[np.ndarray],
        ocr_pages: list[list[dict[str, Any]]],
        zoom: int,
    ) -> tuple[list[list[dict[str, Any]]], dict[str, Any]]:
        health = get_vision_health_status()
        if health.get("can_run_layout_inference"):
            try:
                layout_pages = self._get_layout_recognizer().forward(image_list, thr=0.2, batch_size=16)
                return list(layout_pages), {"layout_source": "onnx", "layout_model_error": None}
            except Exception as exc:
                heuristic_pages = self._build_heuristic_layout_pages(image_list, ocr_pages, zoom=zoom)
                return heuristic_pages, {"layout_source": "heuristic", "layout_model_error": str(exc)}

        heuristic_pages = self._build_heuristic_layout_pages(image_list, ocr_pages, zoom=zoom)
        return heuristic_pages, {"layout_source": "heuristic", "layout_model_error": None}

    def _build_heuristic_layout_pages(
        self,
        image_list: list[np.ndarray],
        ocr_pages: list[list[dict[str, Any]]],
        *,
        zoom: int,
    ) -> list[list[dict[str, Any]]]:
        layout_pages: list[list[dict[str, Any]]] = []
        for image, blocks in zip(image_list, ocr_pages):
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

    def _extract_ocr_blocks(
        self,
        image: np.ndarray,
        page: Any,
        page_index: int,
        zoom: int,
    ) -> list[dict[str, Any]]:
        blocks = self._extract_vendored_ocr_blocks(image, page_index, zoom)
        if blocks:
            return blocks
        return self._extract_fitz_ocr_blocks(page, page_index)

    def _extract_vendored_ocr_blocks(
        self,
        image: np.ndarray,
        page_index: int,
        zoom: int,
    ) -> list[dict[str, Any]]:
        try:
            if self._ocr is None:
                from src.shared.integrations.deepdoc.vision.ocr import OCR

                self._ocr = OCR(autoload=True)
            result = self._ocr(image)
        except Exception:
            return []

        if not result:
            return []

        blocks = []
        for item in result:
            if not item or len(item) != 2:
                continue
            quad, rec = item
            if not rec or len(rec) != 2:
                continue
            text, score = rec
            if not text or float(score) < 0.5:
                continue
            pts = np.array(quad, dtype=np.float32)
            blocks.append(
                {
                    "text": str(text).strip(),
                    "x0": float(np.min(pts[:, 0]) / zoom),
                    "x1": float(np.max(pts[:, 0]) / zoom),
                    "top": float(np.min(pts[:, 1]) / zoom),
                    "bottom": float(np.max(pts[:, 1]) / zoom),
                    "page_number": page_index,
                    "font_size": 0.0,
                    "ocr_source": "vendored_ocr",
                }
            )
        return blocks

    @staticmethod
    def _extract_fitz_ocr_blocks(page: Any, page_index: int) -> list[dict[str, Any]]:
        try:
            textpage = page.get_textpage_ocr()
            text_dict = page.get_text("dict", textpage=textpage)
        except Exception:
            return []

        blocks = []
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            lines = block.get("lines", [])
            if not lines:
                continue
            texts = []
            for line in lines:
                spans = line.get("spans", [])
                line_text = "".join(span.get("text", "") for span in spans).strip()
                if line_text:
                    texts.append(line_text)
            text = " ".join(texts).strip()
            if not text:
                continue
            x0, top, x1, bottom = block["bbox"]
            blocks.append(
                {
                    "text": text,
                    "x0": float(x0),
                    "x1": float(x1),
                    "top": float(top),
                    "bottom": float(bottom),
                    "page_number": page_index,
                    "font_size": 0.0,
                    "ocr_source": "fitz_ocr",
                }
            )
        return blocks

    @staticmethod
    def _extract_fitz_blocks(page: Any) -> list[dict[str, Any]]:
        blocks = []
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            lines = block.get("lines", [])
            if not lines:
                continue
            texts = []
            font_sizes = []
            for line in lines:
                spans = line.get("spans", [])
                line_text = "".join(span.get("text", "") for span in spans).strip()
                if line_text:
                    texts.append(line_text)
                font_sizes.extend(float(span.get("size", 0.0)) for span in spans if span.get("size"))
            text = " ".join(texts).strip()
            if not text:
                continue
            x0, top, x1, bottom = block["bbox"]
            blocks.append(
                {
                    "text": text,
                    "x0": float(x0),
                    "x1": float(x1),
                    "top": float(top),
                    "bottom": float(bottom),
                    "page_number": page.number,
                    "font_size": max(font_sizes) if font_sizes else 0.0,
                }
            )
        return blocks

    @staticmethod
    def _fallback_plain_page_blocks(page: Any, page_index: int) -> list[dict[str, Any]]:
        words = page.get_text("words", sort=True) or []
        if not words:
            return []
        lines: dict[tuple[int, int], list[tuple[Any, ...]]] = {}
        for word in words:
            key = (int(round(word[1] / 8)), int(round(word[0] / 100)))
            lines.setdefault(key, []).append(word)
        blocks = []
        for group in sorted(lines.values(), key=lambda arr: (min(item[1] for item in arr), min(item[0] for item in arr))):
            group = sorted(group, key=lambda item: item[0])
            text = " ".join(str(item[4]) for item in group if str(item[4]).strip()).strip()
            if not text:
                continue
            blocks.append(
                {
                    "text": text,
                    "x0": float(min(item[0] for item in group)),
                    "x1": float(max(item[2] for item in group)),
                    "top": float(min(item[1] for item in group)),
                    "bottom": float(max(item[3] for item in group)),
                    "page_number": page_index,
                    "font_size": 0.0,
                }
            )
        return blocks

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
        if source_set == {"fitz_text"}:
            text_source = "fitz"
        elif source_set == {"vendored_ocr"}:
            text_source = "vendored-ocr"
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
        zoom: float = 1.0,
    ) -> dict[str, list[dict[str, Any]]]:
        return self._artifact_extractor.extract(list(boxes), page_images=page_images, zoom=zoom)

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
                    "html_source": table.get("html_source", ""),
                    "table_structure_source": table_structure.get("source", ""),
                    "prediction_pages": int(table_structure.get("prediction_pages") or 0),
                    "prediction_count": int(table_structure.get("prediction_count") or 0),
                    "row_count": len(row_ids),
                    "column_count": len(col_ids),
                    "structured_box_count": len(structured_boxes),
                    "structured_boxes": structured_boxes,
                    "has_image": bool(table.get("has_image")),
                }
            )
        return table_regions

    @staticmethod
    def _build_figure_regions_metadata(
        artifacts: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
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
        for figure in ordered_figures:
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
                    "has_image": bool(figure.get("has_image")),
                }
            )
        return figure_regions

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
                    "html_source": region.get("html_source", ""),
                    "table_structure_source": region.get("table_structure_source", ""),
                }
            )

        for region in figure_regions:
            bbox = dict(region.get("bbox") or {})
            page = int(region.get("page_start") or (min(region.get("pages") or [1])))
            entries.append(
                {
                    "kind": "figure",
                    "page": page,
                    "bbox": bbox,
                    "text": str(region.get("text", "")),
                    "caption": str(region.get("caption", "")),
                    "layout_type": "figure",
                    "artifact_id": region.get("artifact_id"),
                    "source_id": region.get("artifact_id"),
                }
            )

        ordered = sorted(
            entries,
            key=lambda item: (
                int(item.get("page", 0)),
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
            text = str(entry.get("text", "")).strip()
            prefix = "[TABLE]"
            parts = [part for part in [prefix, caption, text] if part]
            return "\n".join(parts).strip()
        if kind == "figure":
            caption = str(entry.get("caption", "")).strip()
            text = str(entry.get("text", "")).strip()
            prefix = "[FIGURE]"
            parts = [part for part in [prefix, caption, text] if part]
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
            if box.page in kept_pages
            and (box.text.strip() or (box.layout_type or "").lower() in {"table", "figure", "figure caption", "table caption"})
        ]

    def _render_page_images(
        self,
        filename: Union[str, bytes, Path],
        *,
        zoom: int = 2,
    ) -> dict[int, Image.Image]:
        fitz = self._import_fitz()
        doc = fitz.open(stream=filename, filetype="pdf") if isinstance(filename, bytes) else fitz.open(str(filename))
        images: dict[int, Image.Image] = {}
        try:
            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                mode = "RGB" if pix.n < 4 else "RGBA"
                image = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                if image.mode == "RGBA":
                    image = image.convert("RGB")
                images[page_index + 1] = image
        finally:
            doc.close()
        return images
