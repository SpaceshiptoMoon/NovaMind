from __future__ import annotations

from io import BytesIO
from dataclasses import asdict
import re
from typing import Any, Sequence

import numpy as np
from PIL import Image

from src.shared.utils.deepdoc.compat import LazyImage
from src.shared.integrations.deepdoc.vision_runtime import get_vision_health_status


class PdfArtifactExtractor:
    """Adapted toward RAGFlow `_extract_table_figure` grouping behavior."""

    def __init__(self):
        self._tsr: TableStructureRecognizer | None = None
        self._tsr_attempted = False

    def extract(
        self,
        boxes: Sequence[Any],
        *,
        page_images: dict[int, Image.Image] | None = None,
        zoom: float = 1.0,
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
                self._append_to_groups(table_groups, box)
            elif layout_type == "figure":
                self._append_to_groups(figure_groups, box)

        self._attach_captions(table_groups, figure_groups, captions)

        return {
            "tables": [
                self._build_table_artifact(group_key, group, page_images=page_images, zoom=zoom)
                for group_key, group in sorted(table_groups.items())
            ],
            "figures": [
                self._build_figure_artifact(group_key, group, page_images=page_images, zoom=zoom)
                for group_key, group in sorted(figure_groups.items())
            ],
        }

    @staticmethod
    def _group_key(box: Any) -> str:
        page = int(getattr(box, "page", 1))
        position = getattr(box, "position_tag", "") or f"{page}:{int(getattr(box, 'top', 0))}:{int(getattr(box, 'x0', 0))}"
        return f"{page}:{position}"

    def _append_to_groups(self, groups: dict[str, list[Any]], box: Any) -> None:
        for group_key, members in groups.items():
            if self._belongs_to_group(box, members):
                members.append(box)
                return
        groups[self._group_key(box)] = [box]

    @staticmethod
    def _belongs_to_group(box: Any, members: Sequence[Any]) -> bool:
        if not members:
            return False
        page = int(getattr(box, "page", 1))
        group_bbox = PdfArtifactExtractor._group_bbox(members)
        if not group_bbox:
            return False
        group_pages = sorted({int(getattr(member, "page", 1)) for member in members})
        min_page = group_pages[0]
        max_page = group_pages[-1]
        if page < min_page - 1 or page > max_page + 1:
            return False
        horizontal_overlap = min(float(getattr(box, "x1", 0.0)), group_bbox["x1"]) - max(float(getattr(box, "x0", 0.0)), group_bbox["x0"])
        min_width = max(1.0, min(float(getattr(box, "x1", 0.0) - getattr(box, "x0", 0.0)), group_bbox["x1"] - group_bbox["x0"]))
        if page in group_pages:
            row_overlap = min(float(getattr(box, "bottom", 0.0)), group_bbox["bottom"]) - max(float(getattr(box, "top", 0.0)), group_bbox["top"])
            min_height = max(1.0, min(float(getattr(box, "bottom", 0.0) - getattr(box, "top", 0.0)), group_bbox["bottom"] - group_bbox["top"]))
            horizontal_gap = min(
                abs(float(getattr(box, "x0", 0.0)) - group_bbox["x1"]),
                abs(group_bbox["x0"] - float(getattr(box, "x1", 0.0))),
            )
            if horizontal_overlap / min_width <= 0.2:
                if row_overlap / min_height <= 0.6 or horizontal_gap > max(36.0, min_width * 0.75):
                    return False
            vertical_gap = min(
                abs(float(getattr(box, "top", 0.0)) - group_bbox["bottom"]),
                abs(group_bbox["top"] - float(getattr(box, "bottom", 0.0))),
            )
            return vertical_gap < 48.0
        if horizontal_overlap / min_width <= 0.2:
            return False
        nearest_page_members = [
            member
            for member in members
            if int(getattr(member, "page", 1)) == (page - 1 if page > max_page else page + 1)
        ]
        if not nearest_page_members:
            nearest_page_members = [
                member
                for member in members
                if int(getattr(member, "page", 1)) in {min_page, max_page}
            ]
        adjacent_bbox = PdfArtifactExtractor._group_bbox(nearest_page_members)
        if not adjacent_bbox:
            return False
        vertical_gap = min(
            abs(float(getattr(box, "top", 0.0)) - adjacent_bbox["bottom"]),
            abs(adjacent_bbox["top"] - float(getattr(box, "bottom", 0.0))),
        )
        return vertical_gap < 120.0

    @staticmethod
    def _is_caption_box(box: Any) -> bool:
        from src.shared.integrations.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

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
        if not members:
            return float("inf")
        distances = []
        for member in members:
            vertical = abs(((getattr(caption, "top", 0.0) + getattr(caption, "bottom", 0.0)) / 2) - ((getattr(member, "top", 0.0) + getattr(member, "bottom", 0.0)) / 2))
            horizontal = abs(((getattr(caption, "x0", 0.0) + getattr(caption, "x1", 0.0)) / 2) - ((getattr(member, "x0", 0.0) + getattr(member, "x1", 0.0)) / 2))
            distances.append(vertical * vertical + horizontal * horizontal)
        return min(distances)

    def _build_table_artifact(
        self,
        group_key: str,
        members: Sequence[Any],
        *,
        page_images: dict[int, Image.Image] | None = None,
        zoom: float = 1.0,
    ) -> dict[str, Any]:
        ordered = sorted(members, key=lambda item: (getattr(item, "page", 1), getattr(item, "top", 0.0), getattr(item, "x0", 0.0)))
        caption = "\n".join(
            getattr(item, "text", "").strip()
            for item in ordered
            if self._is_caption_box(item)
        ).strip()
        content_boxes = [item for item in ordered if not self._is_caption_box(item)]
        content_text = "\n".join(getattr(item, "text", "").strip() for item in content_boxes if getattr(item, "text", "").strip())
        crop_descriptors = self._collect_group_crops(ordered, page_images=page_images, zoom=zoom)
        html, html_source, table_structure = self._table_html_from_boxes(
            content_boxes,
            caption=caption,
            crop_descriptors=crop_descriptors,
            zoom=zoom,
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
        }

    def _build_figure_artifact(
        self,
        group_key: str,
        members: Sequence[Any],
        *,
        page_images: dict[int, Image.Image] | None = None,
        zoom: float = 1.0,
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
        crop_descriptors = self._collect_group_crops(ordered, page_images=page_images, zoom=zoom)
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

    def _table_html_from_boxes(
        self,
        content_boxes: Sequence[Any],
        *,
        caption: str = "",
        crop_descriptors: Sequence[dict[str, Any]] | None = None,
        zoom: float = 1.0,
    ) -> tuple[str, str, dict[str, Any]]:
        tsr_structured_boxes, tsr_meta = self._infer_structured_boxes_from_tsr_model(
            content_boxes,
            crop_descriptors=crop_descriptors,
            zoom=zoom,
        )
        if tsr_structured_boxes:
            try:
                from src.shared.integrations.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

                html = TableStructureRecognizer.construct_table(tsr_structured_boxes, html=True)
                return html, "tsr_model", {**tsr_meta, "structured_boxes": [dict(box) for box in tsr_structured_boxes]}
            except Exception:
                pass

        structured_boxes = self._infer_structured_table_boxes(content_boxes, caption=caption)
        if structured_boxes:
            try:
                from src.shared.integrations.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

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
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        recognizer = self._get_tsr_recognizer()
        if recognizer is None or not crop_descriptors or not content_boxes:
            return [], {"source": "unavailable", "prediction_pages": 0, "prediction_count": 0}

        images = [np.array(descriptor["crop"]) for descriptor in crop_descriptors if descriptor.get("crop") is not None]
        if not images:
            return [], {"source": "unavailable", "prediction_pages": 0, "prediction_count": 0}

        try:
            predictions = recognizer(images, thr=0.2)
        except Exception as exc:
            return [], {"source": "error", "prediction_pages": 0, "prediction_count": 0, "error": str(exc)}

        structured_boxes: list[dict[str, Any]] = []
        prediction_count = 0
        for descriptor, page_predictions in zip(crop_descriptors, predictions):
            page_prediction_count = len(page_predictions or [])
            prediction_count += page_prediction_count
            if not page_predictions:
                continue
            structured_boxes.extend(
                self._assign_tsr_predictions_to_boxes(
                    descriptor=descriptor,
                    content_boxes=content_boxes,
                    predictions=page_predictions,
                    zoom=zoom,
                )
            )
        if not structured_boxes:
            return [], {"source": "empty", "prediction_pages": len(images), "prediction_count": prediction_count}
        return structured_boxes, {"source": "tsr_model", "prediction_pages": len(images), "prediction_count": prediction_count}

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
            crop = self._crop_image(image, bbox, zoom=zoom)
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
            from src.shared.integrations.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

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
            row_index = self._best_prediction_index(local_box, rows)
            col_index = self._best_prediction_index(local_box, columns)
            if row_index is None or col_index is None:
                continue

            row_pred = rows[row_index]
            col_pred = columns[col_index]
            structured_box = {
                "text": getattr(box, "text", "").strip(),
                "x0": float(getattr(box, "x0", 0.0)),
                "x1": float(getattr(box, "x1", 0.0)),
                "top": float(getattr(box, "top", 0.0)),
                "bottom": float(getattr(box, "bottom", 0.0)),
                "page_number": page - 1,
                "R": str(row_index),
                "C": str(col_index),
                "R_top": self._from_local_coord(row_pred["top"], bbox["top"], zoom),
                "R_bott": self._from_local_coord(row_pred["bottom"], bbox["top"], zoom),
                "R_btm": self._from_local_coord(row_pred["bottom"], bbox["top"], zoom),
                "C_left": self._from_local_coord(col_pred["x0"], bbox["x0"], zoom),
                "C_right": self._from_local_coord(col_pred["x1"], bbox["x0"], zoom),
                "H": any(self._prediction_overlap(local_box, header) > 0.3 for header in headers),
            }
            span_pred = self._best_prediction(local_box, spans)
            if span_pred is not None and self._prediction_overlap(local_box, span_pred) > 0.3:
                structured_box["SP"] = True
                structured_box["H_left"] = self._from_local_coord(span_pred["x0"], bbox["x0"], zoom)
                structured_box["H_right"] = self._from_local_coord(span_pred["x1"], bbox["x0"], zoom)
                structured_box["H_top"] = self._from_local_coord(span_pred["top"], bbox["top"], zoom)
                structured_box["H_bott"] = self._from_local_coord(span_pred["bottom"], bbox["top"], zoom)
            structured_boxes.append(structured_box)
        return structured_boxes

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

    def _encode_crops(self, crops: Sequence[Image.Image]) -> list[bytes]:
        if not crops:
            return []
        ordered_crops = list(crops)
        blobs: list[bytes] = []

        if len(ordered_crops) == 1:
            buffer = BytesIO()
            ordered_crops[0].save(buffer, format="PNG")
            return [buffer.getvalue()]

        composite_width = max(image.size[0] for image in ordered_crops)
        composite_height = sum(image.size[1] for image in ordered_crops)
        composite = Image.new("RGB", (composite_width, composite_height), (245, 245, 245))
        cursor_y = 0
        for crop in ordered_crops:
            composite.paste(crop, (0, cursor_y))
            cursor_y += crop.size[1]

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
