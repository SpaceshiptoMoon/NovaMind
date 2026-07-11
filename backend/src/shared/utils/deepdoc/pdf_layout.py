from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from src.shared.utils.deepdoc.logging_compat import get_logger

logger = get_logger(__name__)


class PdfLayoutExtractor:
    """Structured PDF extractor adapted toward RAGFlow's column-aware reading order."""

    def extract_page_lines(self, words: Sequence[Dict[str, Any]], page_number: int) -> List[Dict[str, Any]]:
        if not words:
            return []

        boxes = [
            {
                "page_number": page_number,
                "text": str(word.get("text", "")).strip(),
                "x0": float(word["x0"]),
                "x1": float(word["x1"]),
                "top": float(word["top"]),
                "bottom": float(word["bottom"]),
            }
            for word in words
            if str(word.get("text", "")).strip()
        ]
        if not boxes:
            return []

        boxes.sort(key=lambda item: (float(item["top"]), float(item["x0"])))
        lines: List[Dict[str, Any]] = []
        current_line: Optional[Dict[str, Any]] = None
        heights = [float(word["bottom"]) - float(word["top"]) for word in boxes]
        char_widths = [
            (float(word["x1"]) - float(word["x0"])) / max(1, len(str(word.get("text", "")).strip()))
            for word in boxes
            if str(word.get("text", "")).strip()
        ]
        line_tolerance = max(3.0, float(np.median(heights)) * 0.45) if heights else 3.0
        gap_tolerance = max(20.0, float(np.median(char_widths)) * 4.0) if char_widths else 20.0

        for word in boxes:
            word_gap = float(word["x0"]) - float(current_line["x1"]) if current_line is not None else 0.0
            if (
                current_line is None
                or abs(float(word["top"]) - float(current_line["top"])) > line_tolerance
                or word_gap > gap_tolerance
            ):
                if current_line is not None and current_line["text"].strip():
                    lines.append(current_line)
                current_line = {
                    "text": word["text"],
                    "page_number": word["page_number"],
                    "x0": float(word["x0"]),
                    "x1": float(word["x1"]),
                    "top": float(word["top"]),
                    "bottom": float(word["bottom"]),
                }
                continue

            current_line["text"] += f" {word['text']}"
            current_line["x0"] = min(current_line["x0"], float(word["x0"]))
            current_line["x1"] = max(current_line["x1"], float(word["x1"]))
            current_line["bottom"] = max(current_line["bottom"], float(word["bottom"]))

        if current_line is not None and current_line["text"].strip():
            lines.append(current_line)
        lines = self.assign_columns(lines)
        return self.final_reading_order(lines)

    def assign_columns(self, boxes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        boxes = [dict(box) for box in boxes]
        if not boxes:
            return boxes
        if all("col_id" in box for box in boxes):
            return boxes

        try:
            from sklearn.cluster import KMeans
            from sklearn.metrics import silhouette_score
        except Exception:
            logger.warning("DeepDoc column clustering unavailable", reason="sklearn_import_failed")
            for box in boxes:
                box["col_id"] = 0
            return boxes

        by_page: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for box in boxes:
            by_page[int(box["page_number"])].append(box)

        page_cols: Dict[int, int] = {}
        for page_number, page_boxes in by_page.items():
            if len(page_boxes) < 4:
                page_cols[page_number] = 1
                continue

            x0s_raw = np.array([float(box["x0"]) for box in page_boxes], dtype=float)
            min_x0 = float(np.min(x0s_raw))
            max_x1 = float(np.max([float(box["x1"]) for box in page_boxes]))
            width = max_x1 - min_x0
            indent_tol = width * 0.12
            x0s = np.array(
                [[min_x0 if abs(x - min_x0) < indent_tol else x] for x in x0s_raw],
                dtype=float,
            )

            distinct_x0 = {round(float(value[0]), 1) for value in x0s}
            max_try = min(4, len(page_boxes), max(1, len(distinct_x0)))
            best_k = 1
            best_score = -1.0
            for k in range(1, max_try + 1):
                try:
                    model = KMeans(n_clusters=k, n_init="auto", random_state=0)
                    labels = model.fit_predict(x0s)
                    centers = np.sort(model.cluster_centers_.flatten())
                    score = silhouette_score(x0s, labels) if len(centers) > 1 else 0.0
                except Exception:
                    continue
                if score > best_score:
                    best_score = score
                    best_k = k

            page_cols[page_number] = best_k

        global_cols = Counter(page_cols.values()).most_common(1)[0][0] if page_cols else 1
        logger.info("DeepDoc detected PDF columns", global_columns=global_cols, by_page=page_cols)

        for page_number, page_boxes in by_page.items():
            k = page_cols.get(page_number, global_cols)
            if len(page_boxes) < k:
                k = 1
            try:
                model = KMeans(
                    n_clusters=k,
                    n_init="auto",
                    random_state=0,
                )
                x0s = np.array([[float(box["x0"])] for box in page_boxes], dtype=float)
                labels = model.fit_predict(x0s)
                centers = model.cluster_centers_.flatten()
                order = np.argsort(centers)
                remap = {int(orig): int(new) for new, orig in enumerate(order)}
                for box, label in zip(page_boxes, labels):
                    box["col_id"] = remap[int(label)]
            except Exception as exc:
                logger.warning("DeepDoc final column assignment failed", page_number=page_number, error=str(exc))
                for box in page_boxes:
                    box["col_id"] = 0

        return boxes

    @staticmethod
    def final_reading_order(boxes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            boxes,
            key=lambda item: (
                int(item.get("page_number", 1)),
                int(item.get("col_id", 0)),
                float(item["top"]),
                float(item["x0"]),
            ),
        )
