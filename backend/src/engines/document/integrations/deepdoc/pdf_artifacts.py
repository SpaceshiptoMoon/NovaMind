"""PDF 版面产物：页面级解析中间产物（文本块 / 表格 / 图像区域）的数据结构。"""
from __future__ import annotations

from io import BytesIO
from dataclasses import asdict
import os
import re
from types import SimpleNamespace
from typing import Any, Sequence

import numpy as np
from PIL import Image

from novamind.engines.document.integrations.deepdoc.compat import LazyImage
from novamind.engines.document.integrations.deepdoc.logging_compat import get_logger
from novamind.engines.document.integrations.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer
from novamind.engines.document.integrations.deepdoc.vision_runtime import get_vision_health_status

logger = get_logger(__name__)


class PdfArtifactExtractor:
    """Adapted toward RAGFlow `_extract_table_figure` grouping behavior."""

    def __init__(self, ocr=None):
        self._ocr = ocr
        self._tsr: "TableStructureRecognizer | None" = None
        self._tsr_attempted = False

    def extract(
        self,
        boxes: Sequence[Any],
        *,
        page_images: dict[int, Image.Image] | None = None,
        zoom: float = 1.0,
        zoom_map: dict[int, float] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        table_groups: dict[str, list[Any]] = {}
        figure_groups: dict[str, list[Any]] = {}
        captions: list[Any] = []

        for box in boxes:
            layout_type = (getattr(box, "layout_type", "") or "").lower()
            if not layout_type:
                continue
            if self._is_caption_box(box):
                captions.append(box)
                continue
            if layout_type == "table":
                table_groups.setdefault(self._group_key(box), []).append(box)
            elif layout_type == "figure":
                figure_groups.setdefault(self._group_key(box), []).append(box)

        # 上游 lout_no = page-layoutno 是区域身份：同区域框天然同组，不同区域永不
        # 相并。此前用几何邻近重造分组，把版面模型标好的 6 个表格区域撕成 22 个
        # 碎组并跨页粘连（实测 18 页论文：表1/表3 题注跨页混挂、单字格碎片表）。
        # 跨页延续只经 _merge_cross_page_groups 的物理边界带判据合并。
        table_groups = self._merge_cross_page_groups(table_groups, page_images=page_images, zoom_map=zoom_map)
        figure_groups = self._merge_cross_page_groups(figure_groups, page_images=page_images, zoom_map=zoom_map)

        self._attach_captions(table_groups, figure_groups, captions)

        # 质量门降级必须可见：假表降级数量进日志，静默丢弃不可审计。
        built_tables: list[dict[str, Any]] = []
        dropped_tables = 0
        for group_key, group in sorted(table_groups.items()):
            artifact = self._maybe_build_table_artifact(
                group_key,
                group,
                page_images=page_images,
                zoom=zoom,
                zoom_map=zoom_map,
            )
            if artifact is None:
                dropped_tables += 1
                continue
            built_tables.append(artifact)
        if dropped_tables:
            logger.info(
                "DeepDoc 表格质量门降级（1x1/无内容假表不进 reading_order，文本保留正文）",
                dropped_count=dropped_tables,
                kept_count=len(built_tables),
            )

        return {
            "tables": built_tables,
            "figures": [
                self._build_figure_artifact(group_key, group, page_images=page_images, zoom=zoom, zoom_map=zoom_map)
                for group_key, group in sorted(figure_groups.items())
            ],
        }

    @staticmethod
    def _group_key(box: Any) -> str:
        # artifact_id 会以 __FIGURE_URL__{id}__ 形式嵌入 full_text，并随后被
        # strip_position_tags（@@...## 正则）清洗。id 里不能带 position_tag 的
        # 坐标标记，否则正文被腐蚀成 __FIGURE_URL__N:__，而 pipeline 替换用的
        # 原始 id 永远匹配不上（占位符原样落盘）。
        # 优先 layoutno 区域身份（上游 lout_no = page-layoutno，apply_layouts 已给
        # 每个版面框打上区域号）；无 layoutno 的合成框回退坐标摘要。
        page = int(getattr(box, "page", 1))
        layoutno = str(getattr(box, "layoutno", "") or "").strip()
        if layoutno:
            return f"{page}:{layoutno}"
        return f"{page}:{int(getattr(box, 'top', 0))}:{int(getattr(box, 'x0', 0))}"

    @classmethod
    def _merge_cross_page_groups(
        cls,
        groups: dict[str, list[Any]],
        *,
        page_images: dict[int, Image.Image] | None = None,
        zoom_map: dict[int, float] | None = None,
    ) -> dict[str, list[Any]]:
        """相邻页同名区域的组，仅当物理连续（后继组首成员贴近页顶）时合并。

        对齐上游 merge table on different pages 的保守意图（相邻页 + 物理距离
        限制），但用页边界带替代其全局 y_dis 判据——我们的框是页局部坐标，
        跨页 y 相减无物理意义。边界带按真实页高折算（page_images 可得页像素高
        /zoom），不能按组框高折算：大表组高可达半页，按组高折算会把页中部
        的独立表格也判成"页顶延续"（实测每页 table-0 被串成 pages=[1..5] 怪组）。"""
        if not groups:
            return groups
        page_heights = cls._page_heights(page_images=page_images, zoom_map=zoom_map)
        ordered_keys = sorted(
            groups,
            key=lambda k: (
                int(k.split(":", 1)[0]),
                min(float(getattr(m, "top", 0.0)) for m in groups[k]),
            ),
        )
        consumed: set[str] = set()
        result: dict[str, list[Any]] = {}
        for key in ordered_keys:
            if key in consumed:
                continue
            members = list(groups[key])
            page, _, name = key.partition(":")
            current_page = max(int(getattr(m, "page", 1)) for m in members)
            while True:
                next_key = f"{current_page + 1}:{name}"
                candidate = groups.get(next_key)
                if candidate is None or next_key in consumed:
                    break
                adjacent_members = [m for m in members if int(getattr(m, "page", 1)) == current_page]
                if not adjacent_members or not cls._cross_page_continues(
                    adjacent_members,
                    candidate,
                    previous_page_height=page_heights.get(current_page),
                    next_page_height=page_heights.get(current_page + 1),
                ):
                    break
                members.extend(candidate)
                consumed.add(next_key)
                current_page += 1
            result[key] = members
        return result

    @staticmethod
    def _page_heights(
        *,
        page_images: dict[int, Image.Image] | None,
        zoom_map: dict[int, float] | None,
    ) -> dict[int, float]:
        heights: dict[int, float] = {}
        if not page_images:
            return heights
        for page, image in page_images.items():
            zoom = float(zoom_map.get(int(page), 1.0)) if zoom_map else 1.0
            heights[int(page)] = float(image.size[1]) / max(zoom, 1e-6)
        return heights

    @classmethod
    def _cross_page_continues(
        cls,
        previous_members: Sequence[Any],
        next_members: Sequence[Any],
        *,
        previous_page_height: float | None = None,
        next_page_height: float | None = None,
    ) -> bool:
        prev_bbox = PdfArtifactExtractor._group_bbox(previous_members)
        next_bbox = PdfArtifactExtractor._group_bbox(next_members)
        if not prev_bbox or not next_bbox:
            return False
        prev_width = max(1.0, prev_bbox["x1"] - prev_bbox["x0"])
        next_width = max(1.0, next_bbox["x1"] - next_bbox["x0"])
        horizontal_overlap = min(prev_bbox["x1"], next_bbox["x1"]) - max(prev_bbox["x0"], next_bbox["x0"])
        if horizontal_overlap / min(prev_width, next_width) <= 0.2:
            return False
        # 页边界带按真实页高折算（缺页高时退保守固定值）。跨页延续须两侧同时
        # 满足物理连续：前组贴页底 + 后继组贴页顶。只判后一半会把「每页顶部
        # 各排一张独立表格」的排版误判成跨页延续（实测论文表1-表6 恰好都在
        # 各页顶部，被串成 pages=[1..5] 怪组）。
        prev_edge_band = max(24.0, 0.12 * float(previous_page_height)) if previous_page_height else 48.0
        next_edge_band = max(24.0, 0.12 * float(next_page_height)) if next_page_height else 48.0
        if prev_bbox["bottom"] < float(previous_page_height or 1e9) - prev_edge_band:
            return False
        return next_bbox["top"] <= next_edge_band

    @staticmethod
    def _is_caption_box(box: Any) -> bool:
        from novamind.engines.document.integrations.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

        return TableStructureRecognizer.is_caption(
            {
                "text": getattr(box, "text", ""),
                "layout_type": getattr(box, "layout_type", ""),
            }
        ) or "caption" in ((getattr(box, "layout_type", "") or "").lower())

    def _attach_captions(
        self,
        table_groups: dict[str, list[Any]],
        figure_groups: dict[str, list[Any]],
        captions: list[Any],
    ) -> None:
        for caption in captions:
            best_group = None
            best_kind = None
            best_distance = float("inf")
            for kind, groups in (("table", table_groups), ("figure", figure_groups)):
                for group_key, members in groups.items():
                    distance = self._caption_distance(caption, members)
                    if distance < best_distance:
                        best_distance = distance
                        best_group = group_key
                        best_kind = kind
            if best_group is None:
                continue
            target_groups = table_groups if best_kind == "table" else figure_groups
            target_groups[best_group].insert(0, caption)

    @staticmethod
    def _caption_distance(caption: Any, members: Sequence[Any]) -> float:
        """题注到组的距离。页内坐标跨页比较无物理意义：同页成员优先，组在题注
        所在页无成员时（跨页区域）才回退全成员比较——修复表1/表3 题注跨页混挂。"""
        if not members:
            return float("inf")

        def _min_distance(target_members: Sequence[Any]) -> float:
            distances = []
            for member in target_members:
                vertical = abs(((getattr(caption, "top", 0.0) + getattr(caption, "bottom", 0.0)) / 2) - ((getattr(member, "top", 0.0) + getattr(member, "bottom", 0.0)) / 2))
                horizontal = abs(((getattr(caption, "x0", 0.0) + getattr(caption, "x1", 0.0)) / 2) - ((getattr(member, "x0", 0.0) + getattr(member, "x1", 0.0)) / 2))
                distances.append(vertical * vertical + horizontal * horizontal)
            return min(distances)

        same_page = [
            member
            for member in members
            if int(getattr(member, "page", 1)) == int(getattr(caption, "page", 1))
        ]
        if same_page:
            return _min_distance(same_page)
        # 跨页回退加惩罚：页局部坐标跨页比较是数值撞车（p5 某框 top 与 p1 题注
        # top 可任意接近），不惩罚时无同页成员的组会以更小的伪距离抢走题注
        # （实测表1 题注被 p5 组以 1087 < 1441 抢走，真组在同页）。
        return _min_distance(members) + 1e9

    def _maybe_build_table_artifact(
        self,
        group_key: str,
        members: Sequence[Any],
        *,
        page_images: dict[int, Image.Image] | None = None,
        zoom: float = 1.0,
        zoom_map: dict[int, float] | None = None,
    ) -> dict[str, Any] | None:
        """质量门：结构识别后仅 1x1（行列都 ≤1）的"表"降级为 None（不进
        table_regions），其成员文本自然保留在正文流中。

        降级对象是版面模型把公式碎片/孤立行误标成 table 的小区域——此前这类
        假表以单字格 <table> 形式混进 MD（实测 22 个抽取"表"里 16 个是假表）。
        真表至少有 2 行或 2 列结构。"""
        artifact = self._build_table_artifact(
            group_key,
            members,
            page_images=page_images,
            zoom=zoom,
            zoom_map=zoom_map,
        )
        if not artifact:
            return None
        structured = artifact.get("table_structure") or {}
        structured_boxes = list(structured.get("structured_boxes") or [])
        if structured_boxes:
            row_count = len({str(box.get("R")) for box in structured_boxes if box.get("R") is not None})
            col_count = len({str(box.get("C")) for box in structured_boxes if box.get("C") is not None})
            if row_count < 2 and col_count < 2:
                return None
        # 无 TSR 结构时按产出内容判定（不能看原始 members：旋转表的内容框来自
        # 旋转 OCR 重识别，members 里可能是空文本框）。
        elif not (artifact.get("text") or "").strip():
            return None
        return artifact

    def _build_table_artifact(
        self,
        group_key: str,
        members: Sequence[Any],
        *,
        page_images: dict[int, Image.Image] | None = None,
        zoom: float = 1.0,
        zoom_map: dict[int, float] | None = None,
    ) -> dict[str, Any]:
        ordered = sorted(members, key=lambda item: (getattr(item, "page", 1), getattr(item, "top", 0.0), getattr(item, "x0", 0.0)))
        caption = "\n".join(
            getattr(item, "text", "").strip()
            for item in ordered
            if self._is_caption_box(item)
        ).strip()
        content_boxes = [item for item in ordered if not self._is_caption_box(item)]
        crop_descriptors = self._collect_group_crops(ordered, page_images=page_images, zoom=zoom, zoom_map=zoom_map)

        auto_rotate = os.environ.get("TABLE_AUTO_ROTATE", "true").lower() != "false"
        if self._ocr is not None and auto_rotate and crop_descriptors:
            rotated_content_boxes: list[Any] = []
            for descriptor in crop_descriptors:
                rotated = self._build_rotated_table_content_boxes(descriptor, self._ocr, zoom)
                if rotated:
                    rotated_content_boxes.extend(rotated)
            if rotated_content_boxes:
                content_boxes = rotated_content_boxes

        # 跨页表格物理拼接对齐上游：所有页旋转角均为 0（正向）时，把各页 crop 竖向
        # 拼成一张合成图，TSR 跑一次，R/C 在合成图坐标系天然全局连续（对齐上游
        # cropout + construct_table 跨页分支 sort_X_firstly）。任一页需旋转则退回
        # per-page row_offset 缝合（旋转 + 合成图坐标映射复杂，跨页旋转表属边缘情况）。
        angles = [int(descriptor.get("rotation_angle", 0)) for descriptor in crop_descriptors]
        modal_angle = max(set(angles), key=angles.count) if angles else 0
        composite_enabled = os.environ.get("DEEPDOC_CROSSPAGE_COMPOSITE", "true").lower() != "false"
        composite_image: Image.Image | None = None
        y_offsets: list[int] = []
        eligible_crops = [descriptor["crop"] for descriptor in crop_descriptors if descriptor.get("crop") is not None]
        is_cross_page = len({int(descriptor["page"]) for descriptor in crop_descriptors}) > 1
        if (
            composite_enabled
            and is_cross_page
            and len(eligible_crops) == len(crop_descriptors)
            and all(angle == 0 for angle in angles)
        ):
            composite_image, y_offsets, _ = self._stack_crops_vertical(eligible_crops)

        content_text = "\n".join(getattr(item, "text", "").strip() for item in content_boxes if getattr(item, "text", "").strip())
        html, html_source, table_structure = self._table_html_from_boxes(
            content_boxes,
            caption=caption,
            crop_descriptors=crop_descriptors,
            zoom=zoom,
            zoom_map=zoom_map,
            composite_image=composite_image,
            y_offsets=y_offsets,
        )
        image = self._encode_group_crops(crop_descriptors)
        return {
            "artifact_id": group_key,
            "type": "table",
            "caption": caption,
            "text": content_text,
            "html": html,
            "html_source": html_source,
            "table_structure": table_structure,
            "pages": sorted({int(getattr(item, "page", 1)) for item in ordered}),
            "bbox": self._group_bbox(ordered),
            "image": image,
            "has_image": bool(image),
            "members": [asdict(item) for item in ordered],
            "rotation_angle": modal_angle,
        }

    def _build_figure_artifact(
        self,
        group_key: str,
        members: Sequence[Any],
        *,
        page_images: dict[int, Image.Image] | None = None,
        zoom: float = 1.0,
        zoom_map: dict[int, float] | None = None,
    ) -> dict[str, Any]:
        ordered = sorted(members, key=lambda item: (getattr(item, "page", 1), getattr(item, "top", 0.0), getattr(item, "x0", 0.0)))
        caption = "\n".join(
            getattr(item, "text", "").strip()
            for item in ordered
            if self._is_caption_box(item)
        ).strip()
        content_text = "\n".join(
            getattr(item, "text", "").strip()
            for item in ordered
            if not self._is_caption_box(item) and getattr(item, "text", "").strip()
        )
        crop_descriptors = self._collect_group_crops(ordered, page_images=page_images, zoom=zoom, zoom_map=zoom_map)
        image = self._encode_group_crops(crop_descriptors)
        return {
            "artifact_id": group_key,
            "type": "figure",
            "caption": caption,
            "text": content_text,
            "pages": sorted({int(getattr(item, "page", 1)) for item in ordered}),
            "bbox": self._group_bbox(ordered),
            "image": image,
            "has_image": bool(image),
            "members": [asdict(item) for item in ordered],
        }

    @staticmethod
    def _group_bbox(members: Sequence[Any]) -> dict[str, float] | None:
        if not members:
            return None
        return {
            "x0": float(min(getattr(item, "x0", 0.0) for item in members)),
            "x1": float(max(getattr(item, "x1", 0.0) for item in members)),
            "top": float(min(getattr(item, "top", 0.0) for item in members)),
            "bottom": float(max(getattr(item, "bottom", 0.0) for item in members)),
        }

    @staticmethod
    def bbox_overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
        """两个页面坐标 bbox 的交面积 / 较小框面积（IoMin）。0 表示不相交。"""
        left = max(float(a.get("x0", 0.0)), float(b.get("x0", 0.0)))
        right = min(float(a.get("x1", 0.0)), float(b.get("x1", 0.0)))
        top = max(float(a.get("top", 0.0)), float(b.get("top", 0.0)))
        bottom = min(float(a.get("bottom", 0.0)), float(b.get("bottom", 0.0)))
        if right <= left or bottom <= top:
            return 0.0
        intersection = (right - left) * (bottom - top)
        area_a = max(1e-6, (float(a.get("x1", 0.0)) - float(a.get("x0", 0.0))) * (float(a.get("bottom", 0.0)) - float(a.get("top", 0.0))))
        area_b = max(1e-6, (float(b.get("x1", 0.0)) - float(b.get("x0", 0.0))) * (float(b.get("bottom", 0.0)) - float(b.get("top", 0.0))))
        return float(intersection / min(area_a, area_b))

    def _table_html_from_boxes(
        self,
        content_boxes: Sequence[Any],
        *,
        caption: str = "",
        crop_descriptors: Sequence[dict[str, Any]] | None = None,
        zoom: float = 1.0,
        zoom_map: dict[int, float] | None = None,
        composite_image: Image.Image | None = None,
        y_offsets: Sequence[int] | None = None,
    ) -> tuple[str, str, dict[str, Any]]:
        tsr_structured_boxes, tsr_meta = self._infer_structured_boxes_from_tsr_model(
            content_boxes,
            crop_descriptors=crop_descriptors,
            zoom=zoom,
            zoom_map=zoom_map,
            composite_image=composite_image,
            y_offsets=y_offsets,
        )
        if tsr_structured_boxes:
            try:
                from novamind.engines.document.integrations.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

                is_english = self._estimate_is_english([box.get("text", "") for box in tsr_structured_boxes])
                html = TableStructureRecognizer.construct_table(tsr_structured_boxes, html=True, is_english=is_english)
                return html, "tsr_model", {**tsr_meta, "is_english": is_english, "structured_boxes": [dict(box) for box in tsr_structured_boxes]}
            except Exception:
                pass

        structured_boxes = self._infer_structured_table_boxes(content_boxes, caption=caption)
        if structured_boxes:
            try:
                from novamind.engines.document.integrations.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

                return (
                    TableStructureRecognizer.construct_table(structured_boxes, html=True),
                    "tsr_constructed",
                    {
                        "source": "tsr_constructed",
                        "prediction_pages": 0,
                        "prediction_count": 0,
                        "structured_boxes": [dict(box) for box in structured_boxes],
                    },
                )
            except Exception:
                pass
        return (
            self._heuristic_table_html(content_boxes, caption=caption),
            "heuristic",
            {"source": "heuristic", "prediction_pages": 0, "prediction_count": 0, "structured_boxes": []},
        )

    def _infer_structured_boxes_from_tsr_model(
        self,
        content_boxes: Sequence[Any],
        *,
        crop_descriptors: Sequence[dict[str, Any]] | None = None,
        zoom: float = 1.0,
        zoom_map: dict[int, float] | None = None,
        composite_image: Image.Image | None = None,
        y_offsets: Sequence[int] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        recognizer = self._get_tsr_recognizer()
        if recognizer is None or not crop_descriptors or not content_boxes:
            return [], {"source": "unavailable", "prediction_pages": 0, "prediction_count": 0}

        if composite_image is not None:
            return self._infer_structured_boxes_composite(
                recognizer,
                content_boxes,
                crop_descriptors=crop_descriptors,
                zoom=zoom,
                zoom_map=zoom_map,
                composite_image=composite_image,
                y_offsets=list(y_offsets or []),
            )

        images = [np.array(descriptor["crop"]) for descriptor in crop_descriptors if descriptor.get("crop") is not None]
        if not images:
            return [], {"source": "unavailable", "prediction_pages": 0, "prediction_count": 0}

        try:
            predictions = recognizer(images, thr=0.2)
        except Exception as exc:
            return [], {"source": "error", "prediction_pages": 0, "prediction_count": 0, "error": str(exc)}

        structured_boxes: list[dict[str, Any]] = []
        prediction_count = 0
        row_offset = 0
        crosspage_row_offset: list[int] = []
        for descriptor, page_predictions in zip(crop_descriptors, predictions):
            page_prediction_count = len(page_predictions or [])
            prediction_count += page_prediction_count
            if not page_predictions:
                crosspage_row_offset.append(row_offset)
                continue
            page_zoom = float(zoom_map.get(int(descriptor["page"]), zoom) if zoom_map else zoom)
            page_boxes = self._assign_tsr_predictions_to_boxes(
                descriptor=descriptor,
                content_boxes=content_boxes,
                predictions=page_predictions,
                zoom=page_zoom,
                angle=int(descriptor.get("rotation_angle", 0)),
                rotated_size=descriptor.get("rotation_size"),
            )
            if page_boxes:
                max_row = max(int(box.get("R", 0)) for box in page_boxes)
                for box in page_boxes:
                    box["R"] = str(int(box["R"]) + row_offset)
                    if "R_top" in box:
                        box["R_top"] = box["R_top"]
                    if "R_bott" in box:
                        box["R_bott"] = box["R_bott"]
                    if "R_btm" in box:
                        box["R_btm"] = box["R_btm"]
                row_offset = max_row + row_offset + 1
                structured_boxes.extend(page_boxes)
            crosspage_row_offset.append(row_offset)
        if not structured_boxes:
            return [], {"source": "empty", "prediction_pages": len(images), "prediction_count": prediction_count, "crosspage_row_offset": crosspage_row_offset}
        return structured_boxes, {
            "source": "tsr_model",
            "prediction_pages": len(images),
            "prediction_count": prediction_count,
            "crosspage_row_offset": crosspage_row_offset,
        }

    def _infer_structured_boxes_composite(
        self,
        recognizer: Any,
        content_boxes: Sequence[Any],
        *,
        crop_descriptors: Sequence[dict[str, Any]],
        zoom: float,
        zoom_map: dict[int, float] | None,
        composite_image: Image.Image,
        y_offsets: list[int],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """跨页合成图模式：TSR 在竖向拼接的合成图上跑一次，R/C 全局连续。

        各页 box 经 ``y_offsets[p]`` 平移到合成图像素坐标后，匹配同一份全局
        row/column 预测；``crosspage_row_offset`` 记录每页首行的全局 R 起点（诊断用）。
        对齐上游 ``cropout`` + ``construct_table`` 跨页分支。
        """
        try:
            predictions = recognizer([np.array(composite_image)], thr=0.2)
        except Exception as exc:
            return [], {"source": "error", "prediction_pages": 1, "prediction_count": 0, "error": str(exc)}
        page_predictions = predictions[0] if predictions else []

        structured_boxes: list[dict[str, Any]] = []
        crosspage_row_offset: list[int] = []
        for index, descriptor in enumerate(crop_descriptors):
            y_offset = int(y_offsets[index]) if index < len(y_offsets) else 0
            page_zoom = float(zoom_map.get(int(descriptor["page"]), zoom) if zoom_map else zoom)
            page_boxes = self._assign_tsr_predictions_to_boxes(
                descriptor=descriptor,
                content_boxes=content_boxes,
                predictions=page_predictions,
                zoom=page_zoom,
                angle=0,
                rotated_size=None,
                y_offset=y_offset,
            )
            if page_boxes:
                crosspage_row_offset.append(min(int(box["R"]) for box in page_boxes))
                structured_boxes.extend(page_boxes)
            else:
                crosspage_row_offset.append(-1)

        if not structured_boxes:
            return [], {
                "source": "empty",
                "prediction_pages": 1,
                "prediction_count": len(page_predictions),
                "crosspage_row_offset": crosspage_row_offset,
                "composite": True,
            }
        return structured_boxes, {
            "source": "tsr_model",
            "prediction_pages": 1,
            "prediction_count": len(page_predictions),
            "crosspage_row_offset": crosspage_row_offset,
            "composite": True,
        }

    def _infer_structured_table_boxes(
        self,
        content_boxes: Sequence[Any],
        *,
        caption: str = "",
    ) -> list[dict[str, Any]]:
        if not content_boxes:
            return []
        rows: dict[int, list[Any]] = {}
        ordered = sorted(content_boxes, key=lambda item: (getattr(item, "top", 0.0), getattr(item, "x0", 0.0)))
        current_row = 0
        last_top = None
        for item in ordered:
            top = float(getattr(item, "top", 0.0))
            if last_top is None:
                last_top = top
            elif abs(top - last_top) > max(8.0, float(getattr(item, "bottom", 0.0) - getattr(item, "top", 0.0)) * 0.8):
                current_row += 1
                last_top = top
            rows.setdefault(current_row, []).append(item)

        structured_rows: list[list[dict[str, Any]]] = []
        max_cols = 0
        for row_index in sorted(rows):
            row_cells = self._infer_row_cells(rows[row_index])
            if not row_cells:
                continue
            structured_rows.append(row_cells)
            max_cols = max(max_cols, len(row_cells))

        if not structured_rows or max_cols == 0:
            return []

        header_rows = self._guess_header_rows(structured_rows)
        structured_boxes: list[dict[str, Any]] = []
        if caption:
            structured_boxes.append(
                {
                    "text": caption,
                    "layout_type": "table caption",
                    "x0": float(min(cell["x0"] for row in structured_rows for cell in row)),
                    "x1": float(max(cell["x1"] for row in structured_rows for cell in row)),
                    "top": float(min(cell["top"] for row in structured_rows for cell in row)),
                    "bottom": float(min(cell["top"] for row in structured_rows for cell in row)),
                    "page_number": int(min(cell["page_number"] for row in structured_rows for cell in row)),
                }
            )

        for row_index, row_cells in enumerate(structured_rows):
            for col_index, cell in enumerate(row_cells):
                structured_boxes.append(
                    {
                        "text": cell["text"],
                        "x0": cell["x0"],
                        "x1": cell["x1"],
                        "top": cell["top"],
                        "bottom": cell["bottom"],
                        "page_number": cell["page_number"],
                        "R": str(row_index),
                        "C": str(col_index),
                        "R_top": cell["top"],
                        "R_bott": cell["bottom"],
                        "R_btm": cell["bottom"],
                        "C_left": cell["x0"],
                        "C_right": cell["x1"],
                        "H": row_index in header_rows,
                    }
                )
        return structured_boxes

    def _infer_row_cells(self, row_boxes: Sequence[Any]) -> list[dict[str, Any]]:
        ordered = sorted(row_boxes, key=lambda item: getattr(item, "x0", 0.0))
        cells: list[dict[str, Any]] = []
        for box in ordered:
            box_text = getattr(box, "text", "").strip()
            if not box_text:
                continue
            split_cells = self._split_box_text_into_cells(box)
            if split_cells:
                cells.extend(split_cells)
                continue
            cells.append(
                {
                    "text": box_text,
                    "x0": float(getattr(box, "x0", 0.0)),
                    "x1": float(getattr(box, "x1", 0.0)),
                    "top": float(getattr(box, "top", 0.0)),
                    "bottom": float(getattr(box, "bottom", 0.0)),
                    "page_number": int(getattr(box, "page", 1)) - 1,
                }
            )
        return cells

    @staticmethod
    def _split_box_text_into_cells(box: Any) -> list[dict[str, Any]]:
        text = getattr(box, "text", "").strip()
        if not text:
            return []
        delimiters = [segment.strip() for segment in re.split(r"\s+\|\s+|\|+|\t+", text) if segment.strip()]
        if len(delimiters) <= 1:
            return []
        left = float(getattr(box, "x0", 0.0))
        right = float(getattr(box, "x1", 0.0))
        width = max(1.0, right - left)
        cell_width = width / len(delimiters)
        cells: list[dict[str, Any]] = []
        for index, value in enumerate(delimiters):
            cells.append(
                {
                    "text": value,
                    "x0": left + cell_width * index,
                    "x1": right if index == len(delimiters) - 1 else left + cell_width * (index + 1),
                    "top": float(getattr(box, "top", 0.0)),
                    "bottom": float(getattr(box, "bottom", 0.0)),
                    "page_number": int(getattr(box, "page", 1)) - 1,
                }
            )
        return cells

    @staticmethod
    def _guess_header_rows(rows: Sequence[Sequence[dict[str, Any]]]) -> set[int]:
        if not rows:
            return set()
        if len(rows) == 1:
            return {0}
        first_row = rows[0]
        second_row = rows[1] if len(rows) > 1 else []
        first_numeric_ratio = PdfArtifactExtractor._numeric_ratio(first_row)
        second_numeric_ratio = PdfArtifactExtractor._numeric_ratio(second_row) if second_row else 0.0
        if first_numeric_ratio <= 0.4 and second_numeric_ratio >= first_numeric_ratio:
            return {0}
        return set()

    @staticmethod
    def _numeric_ratio(cells: Sequence[dict[str, Any]]) -> float:
        if not cells:
            return 0.0
        numeric_count = 0
        for cell in cells:
            text = cell.get("text", "").strip()
            if text and re.fullmatch(r"[\d\s.,%+\-/:()]+", text):
                numeric_count += 1
        return numeric_count / len(cells)

    @staticmethod
    def _heuristic_table_html(content_boxes: Sequence[Any], *, caption: str = "") -> str:
        if not content_boxes:
            return ""
        rows: dict[int, list[Any]] = {}
        ordered = sorted(content_boxes, key=lambda item: (getattr(item, "top", 0.0), getattr(item, "x0", 0.0)))
        current_row = 0
        last_top = None
        for item in ordered:
            top = float(getattr(item, "top", 0.0))
            if last_top is None:
                last_top = top
            elif abs(top - last_top) > max(8.0, float(getattr(item, "bottom", 0.0) - getattr(item, "top", 0.0)) * 0.8):
                current_row += 1
                last_top = top
            rows.setdefault(current_row, []).append(item)

        html = "<table>"
        if caption:
            html += f"<caption>{caption}</caption>"
        for row_index in sorted(rows):
            html += "\n<tr>"
            for cell in sorted(rows[row_index], key=lambda item: getattr(item, "x0", 0.0)):
                html += f"<td>{getattr(cell, 'text', '').strip()}</td>"
            html += "</tr>"
        html += "\n</table>"
        return html

    def _collect_group_crops(
        self,
        members: Sequence[Any],
        *,
        page_images: dict[int, Image.Image] | None = None,
        zoom: float = 1.0,
        zoom_map: dict[int, float] | None = None,
    ) -> list[dict[str, Any]]:
        if not page_images or not members:
            return []
        crops: list[dict[str, Any]] = []
        grouped_by_page: dict[int, list[Any]] = {}
        for member in members:
            grouped_by_page.setdefault(int(getattr(member, "page", 1)), []).append(member)

        for page, page_members in sorted(grouped_by_page.items()):
            image = page_images.get(page)
            if image is None:
                continue
            bbox = self._group_bbox(page_members)
            if not bbox:
                continue
            page_zoom = float(zoom_map.get(page, zoom) if zoom_map else zoom)
            crop = self._crop_image(image, bbox, zoom=page_zoom)
            if crop is None:
                continue
            crops.append(
                {
                    "page": page,
                    "bbox": bbox,
                    "crop": crop,
                    "members": list(page_members),
                }
            )
        return crops

    def _encode_group_crops(self, crop_descriptors: Sequence[dict[str, Any]]) -> LazyImage:
        if not crop_descriptors:
            return LazyImage([])
        return LazyImage(self._encode_crops([descriptor["crop"] for descriptor in crop_descriptors if descriptor.get("crop") is not None]))

    def _get_tsr_recognizer(self):
        if self._tsr_attempted:
            return self._tsr
        self._tsr_attempted = True
        try:
            health = get_vision_health_status()
        except Exception:
            return None
        if not health.get("can_run_tsr_inference"):
            return None
        try:
            from novamind.engines.document.integrations.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

            self._tsr = TableStructureRecognizer(autoload=True)
        except Exception:
            self._tsr = None
        return self._tsr

    def _assign_tsr_predictions_to_boxes(
        self,
        *,
        descriptor: dict[str, Any],
        content_boxes: Sequence[Any],
        predictions: Sequence[dict[str, Any]],
        zoom: float,
        angle: int = 0,
        rotated_size: tuple[int, int] | None = None,
        y_offset: int = 0,
    ) -> list[dict[str, Any]]:
        page = int(descriptor["page"])
        bbox = descriptor["bbox"]
        page_boxes = [
            box
            for box in content_boxes
            if int(getattr(box, "page", 1)) == page and not self._is_caption_box(box) and getattr(box, "text", "").strip()
        ]
        if not page_boxes:
            return []

        predictions = self._map_predictions_to_original_crop(predictions, angle=angle, rotated_size=rotated_size)
        rows = [pred for pred in predictions if pred.get("label") == "table row"]
        columns = [pred for pred in predictions if pred.get("label") == "table column"]
        headers = [pred for pred in predictions if pred.get("label") in {"table column header", "table projected row header"}]
        spans = [pred for pred in predictions if pred.get("label") == "table spanning cell"]
        if not rows or not columns:
            return []

        rows = sorted(rows, key=lambda item: (item["top"], item["x0"]))
        columns = sorted(columns, key=lambda item: (item["x0"], item["top"]))
        structured_boxes: list[dict[str, Any]] = []
        for box in page_boxes:
            local_box = self._to_local_box(box, bbox=bbox, zoom=zoom)
            # 合成图模式：把页内 crop 坐标平移到合成图像素坐标，匹配合成图预测。
            if y_offset:
                local_box["top"] += y_offset
                local_box["bottom"] += y_offset
            row_index = self._best_prediction_index(local_box, rows)
            col_index = self._best_prediction_index(local_box, columns)
            if row_index is None or col_index is None:
                continue

            row_pred = rows[row_index]
            col_pred = columns[col_index]
            # R_top/R_bott 存页面坐标：合成图预测的 y 减回 y_offset 再 /zoom + bbox.top。
            row_top_page = float(row_pred["top"]) - y_offset
            row_bottom_page = float(row_pred["bottom"]) - y_offset
            structured_box = {
                "text": getattr(box, "text", "").strip(),
                "x0": float(getattr(box, "x0", 0.0)),
                "x1": float(getattr(box, "x1", 0.0)),
                "top": float(getattr(box, "top", 0.0)),
                "bottom": float(getattr(box, "bottom", 0.0)),
                "page_number": page - 1,
                "R": str(row_index),
                "C": str(col_index),
                "R_top": self._from_local_coord(row_top_page, bbox["top"], zoom),
                "R_bott": self._from_local_coord(row_bottom_page, bbox["top"], zoom),
                "R_btm": self._from_local_coord(row_bottom_page, bbox["top"], zoom),
                "C_left": self._from_local_coord(col_pred["x0"], bbox["x0"], zoom),
                "C_right": self._from_local_coord(col_pred["x1"], bbox["x0"], zoom),
                "H": any(self._prediction_overlap(local_box, header) > 0.3 for header in headers),
            }
            span_pred = self._best_prediction(local_box, spans)
            if span_pred is not None and self._prediction_overlap(local_box, span_pred) > 0.3:
                span_top_page = float(span_pred["top"]) - y_offset
                span_bottom_page = float(span_pred["bottom"]) - y_offset
                structured_box["SP"] = True
                structured_box["H_left"] = self._from_local_coord(span_pred["x0"], bbox["x0"], zoom)
                structured_box["H_right"] = self._from_local_coord(span_pred["x1"], bbox["x0"], zoom)
                structured_box["H_top"] = self._from_local_coord(span_top_page, bbox["top"], zoom)
                structured_box["H_bott"] = self._from_local_coord(span_bottom_page, bbox["top"], zoom)
            structured_boxes.append(structured_box)
        return structured_boxes

    @staticmethod
    def _map_predictions_to_original_crop(
        predictions: Sequence[dict[str, Any]],
        *,
        angle: int = 0,
        rotated_size: tuple[int, int] | None = None,
    ) -> list[dict[str, Any]]:
        """TSR 在旋转后的 crop 上预测，把预测框坐标映射回原 crop 坐标。"""
        if angle == 0 or not rotated_size:
            return list(predictions)
        orig_w, orig_h = rotated_size
        mapped: list[dict[str, Any]] = []
        for pred in predictions:
            corners = [
                (pred["x0"], pred["top"]),
                (pred["x1"], pred["top"]),
                (pred["x1"], pred["bottom"]),
                (pred["x0"], pred["bottom"]),
            ]
            original_corners = [
                PdfArtifactExtractor._map_rotated_point_to_original(rx, ry, angle, orig_w, orig_h)
                for rx, ry in corners
            ]
            xs = [p[0] for p in original_corners]
            ys = [p[1] for p in original_corners]
            mapped.append(
                {
                    **pred,
                    "x0": min(xs),
                    "x1": max(xs),
                    "top": min(ys),
                    "bottom": max(ys),
                }
            )
        return mapped

    @staticmethod
    def _map_rotated_point_to_original(
        rx: float,
        ry: float,
        angle: int,
        orig_width: int,
        orig_height: int,
    ) -> tuple[float, float]:
        """顺时针旋转后图像中的点映射回原图坐标。"""
        if angle == 90:
            return float(ry), float(orig_height - 1 - rx)
        if angle == 180:
            return float(orig_width - 1 - rx), float(orig_height - 1 - ry)
        if angle == 270:
            return float(orig_width - 1 - ry), float(rx)
        return float(rx), float(ry)

    @staticmethod
    def _evaluate_table_orientation(
        crop_image: Image.Image,
        ocr: Any,
    ) -> tuple[int, Image.Image, dict[int, float]]:
        """对表格 crop 评估 0/90/180/270°，选择 OCR 综合得分最高的方向。"""
        if ocr is None:
            return 0, crop_image, {0: 0.0}

        candidates: list[tuple[int, Image.Image, float]] = []
        scores: dict[int, float] = {}
        for angle in (0, 90, 180, 270):
            if angle == 0:
                rotated = crop_image
            else:
                rotated = crop_image.rotate(-angle, expand=True, fillcolor=(255, 255, 255))
            img_np = np.asarray(rotated)
            try:
                ocr_result = ocr(img_np, device_id=0)
            except Exception:
                ocr_result = None
            # OCR.__call__ 返回 [(box, (text, score)), ...]（检测到文字）或
            # (None, None, time_dict) 三元组（无文字 / img 为 None）。
            # 早期代码误以为返回 (boxes, rec_results) 二元组，在恰好 2 个框时会
            # 静默错配并在下游解包崩溃（too many values to unpack）。这里归一化。
            pairs = ocr_result if isinstance(ocr_result, list) else []
            if not pairs:
                scores[angle] = 0.0
                candidates.append((angle, rotated, 0.0))
                continue
            mean_score = float(np.mean([float(rec[1][1]) for rec in pairs]))
            # 综合得分 = 平均置信度 × 识别框数量，避免单个大框误胜。
            composite = mean_score * len(pairs)
            scores[angle] = composite
            candidates.append((angle, rotated, composite))

        best_angle, best_image, best_score = max(candidates, key=lambda item: (item[2], -item[0]))
        if best_score <= 0:
            return 0, crop_image, scores
        return best_angle, best_image, scores

    def _build_rotated_table_content_boxes(
        self,
        descriptor: dict[str, Any],
        ocr: Any,
        zoom: float,
    ) -> list[Any]:
        """若表格 crop 需旋转，在旋转图上重 OCR，把 box 映射回页面坐标。"""
        crop = descriptor.get("crop")
        if crop is None or ocr is None:
            return []

        angle, rotated_image, _ = self._evaluate_table_orientation(crop, ocr)
        if angle == 0:
            return []

        orig_w, orig_h = crop.size
        descriptor["crop"] = rotated_image
        descriptor["rotation_angle"] = angle
        descriptor["rotation_size"] = (orig_w, orig_h)

        img_np = np.asarray(rotated_image)
        try:
            ocr_result = ocr(img_np, device_id=0)
        except Exception:
            ocr_result = None
        # OCR.__call__ 返回 [(box, (text, score)), ...] 或 (None, None, time_dict)；
        # 归一化为 (box, (text, score)) 列表（已是 zip 后的成对结果，无需再 zip）。
        pairs = ocr_result if isinstance(ocr_result, list) else []
        if not pairs:
            return []

        page = int(descriptor["page"])
        bbox = descriptor["bbox"]
        content_boxes: list[Any] = []
        for quad, (text, _score) in pairs:
            if not text or not text.strip():
                continue
            original_points = [
                self._map_rotated_point_to_original(float(rx), float(ry), angle, orig_w, orig_h)
                for rx, ry in quad
            ]
            xs = [p[0] for p in original_points]
            ys = [p[1] for p in original_points]
            x0_crop, x1_crop = min(xs), max(xs)
            y0_crop, y1_crop = min(ys), max(ys)
            content_boxes.append(
                SimpleNamespace(
                    page=page,
                    x0=x0_crop / zoom + bbox["x0"],
                    x1=x1_crop / zoom + bbox["x0"],
                    top=y0_crop / zoom + bbox["top"],
                    bottom=y1_crop / zoom + bbox["top"],
                    text=text.strip(),
                    layout_type="table",
                )
            )
        return content_boxes

    @staticmethod
    def _to_local_box(box: Any, *, bbox: dict[str, float], zoom: float) -> dict[str, float]:
        return {
            "x0": (float(getattr(box, "x0", 0.0)) - bbox["x0"]) * zoom,
            "x1": (float(getattr(box, "x1", 0.0)) - bbox["x0"]) * zoom,
            "top": (float(getattr(box, "top", 0.0)) - bbox["top"]) * zoom,
            "bottom": (float(getattr(box, "bottom", 0.0)) - bbox["top"]) * zoom,
        }

    @staticmethod
    def _from_local_coord(value: float, offset: float, zoom: float) -> float:
        return float(value) / float(zoom) + float(offset)

    def _best_prediction_index(self, box: dict[str, float], predictions: Sequence[dict[str, Any]]) -> int | None:
        best_index = None
        best_score = 0.0
        for index, prediction in enumerate(predictions):
            score = self._prediction_overlap(box, prediction)
            if score > best_score:
                best_index = index
                best_score = score
        return best_index

    def _best_prediction(self, box: dict[str, float], predictions: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
        best_prediction = None
        best_score = 0.0
        for prediction in predictions:
            score = self._prediction_overlap(box, prediction)
            if score > best_score:
                best_prediction = prediction
                best_score = score
        return best_prediction

    @staticmethod
    def _prediction_overlap(box: dict[str, float], prediction: dict[str, Any]) -> float:
        left = max(box["x0"], prediction["x0"])
        right = min(box["x1"], prediction["x1"])
        top = max(box["top"], prediction["top"])
        bottom = min(box["bottom"], prediction["bottom"])
        if right <= left or bottom <= top:
            return 0.0
        intersection = (right - left) * (bottom - top)
        area = max(1.0, (box["x1"] - box["x0"]) * (box["bottom"] - box["top"]))
        return float(intersection / area)

    @staticmethod
    def _estimate_is_english(texts: Sequence[str]) -> bool:
        """根据单元格文本中英文字母比例估计表格是否为英文。"""
        total = 0
        latin = 0
        for text in texts:
            for ch in text:
                if ch.isalpha():
                    total += 1
                    if ch.isascii():
                        latin += 1
        return total > 0 and latin / total > 0.5

    @staticmethod
    def _stack_crops_vertical(
        crops: Sequence[Image.Image],
    ) -> tuple[Image.Image, list[int], list[int]]:
        """竖向拼接 crops：width=max, height=sum, paste at (0, cursor_y)。

        返回 ``(composite, y_offsets, page_heights)``：``y_offsets[p]`` 为第 p 张 crop
        在合成图中的顶端 y 像素，用于把 TSR 在合成图上的预测框映射回各页 crop 坐标。
        对齐上游 RAGFlow ``cropout`` 的跨页拼接方式。
        """
        if not crops:
            raise ValueError("_stack_crops_vertical 至少需要一张 crop")
        composite_width = max(image.size[0] for image in crops)
        composite_height = sum(image.size[1] for image in crops)
        composite = Image.new("RGB", (composite_width, composite_height), (245, 245, 245))
        y_offsets: list[int] = []
        page_heights: list[int] = []
        cursor_y = 0
        for crop in crops:
            y_offsets.append(cursor_y)
            page_heights.append(crop.size[1])
            composite.paste(crop, (0, cursor_y))
            cursor_y += crop.size[1]
        return composite, y_offsets, page_heights

    def _encode_crops(self, crops: Sequence[Image.Image]) -> list[bytes]:
        if not crops:
            return []
        ordered_crops = list(crops)
        blobs: list[bytes] = []

        if len(ordered_crops) == 1:
            buffer = BytesIO()
            ordered_crops[0].save(buffer, format="PNG")
            return [buffer.getvalue()]

        composite, _, _ = self._stack_crops_vertical(ordered_crops)
        composite_buffer = BytesIO()
        composite.save(composite_buffer, format="PNG")
        blobs.append(composite_buffer.getvalue())

        for crop in ordered_crops:
            buffer = BytesIO()
            crop.save(buffer, format="PNG")
            blobs.append(buffer.getvalue())
        return blobs

    @staticmethod
    def _crop_image(image: Image.Image, bbox: dict[str, float], *, zoom: float = 1.0) -> Image.Image | None:
        left = max(0, int(bbox["x0"] * zoom))
        top = max(0, int(bbox["top"] * zoom))
        right = min(image.size[0], max(left + 1, int(bbox["x1"] * zoom)))
        bottom = min(image.size[1], max(top + 1, int(bbox["bottom"] * zoom)))
        if right <= left or bottom <= top:
            return None
        return image.crop((left, top, right, bottom))
