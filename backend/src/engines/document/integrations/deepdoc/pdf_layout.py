"""PDF 版面分析：阅读顺序恢复、双栏合并、区块排序。"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

import numpy as np
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# k 相对 k-1 的 silhouette 提升低于该值时判为非显著、回落到小 k（防孤立框
# 把双栏页聚成 3/4 栏；清晰多栏结构的提升远高于此值）。
SILHOUETTE_MARGIN = 0.05


class PdfLayoutExtractor:
    """Structured PDF extractor adapted toward RAGFlow's column-aware reading order."""

    def extract_page_lines(self, words: Sequence[dict[str, Any]], page_number: int) -> list[dict[str, Any]]:
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
        lines: list[dict[str, Any]] = []
        current_line: dict[str, Any] | None = None
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

    def assign_columns(self, boxes: Sequence[dict[str, Any]], *, force: bool = False) -> list[dict[str, Any]]:
        boxes = [dict(box) for box in boxes]
        if not boxes:
            return boxes
        if not force and all("col_id" in box for box in boxes):
            return boxes

        try:
            from sklearn.cluster import KMeans
            from sklearn.metrics import silhouette_score
        except Exception:
            logger.warning("DeepDoc column clustering unavailable", reason="sklearn_import_failed")
            for box in boxes:
                box["col_id"] = 0
            return boxes

        by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for box in boxes:
            by_page[int(box["page_number"])].append(box)

        page_cols: dict[int, int] = {}
        page_scores: dict[int, dict[int, float]] = {}
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
            # silhouette 显著性门槛：k 相对 k-1 的提升 < SILHOUETTE_MARGIN 时判为
            # 非显著、回落到小 k——双栏正文页的孤立框（居中标题/表格行）常被
            # KMeans 以极微弱优势聚成第 3/4 栏，左右栏行级交错（doc568 实测
            # by_page 4 栏页 15 个）。清晰多栏结构 silhouette(k) 远高于 k-1，
            # margin 不会误伤。
            scores_by_k: dict[int, float] = {}
            for k in range(1, max_try + 1):
                try:
                    model = KMeans(n_clusters=k, n_init="auto", random_state=0)
                    labels = model.fit_predict(x0s)
                    centers = np.sort(model.cluster_centers_.flatten())
                    score = silhouette_score(x0s, labels) if len(centers) > 1 else 0.0
                except Exception:
                    continue
                scores_by_k[k] = score
            best_k = 1
            for k in sorted(scores_by_k):
                if k == 1:
                    best_k = 1
                    continue
                prev = scores_by_k.get(k - 1)
                if prev is not None and scores_by_k[k] - prev < SILHOUETTE_MARGIN:
                    break
                best_k = k

            page_cols[page_number] = best_k
            page_scores[page_number] = scores_by_k

        global_cols = Counter(page_cols.values()).most_common(1)[0][0] if page_cols else 1
        # 全局一致性回退：文档主体 2 栏、单页聚出 4 栏属过切（孤立框作祟），
        # 信息量充足（框数 >= global_cols*3）时该页固定 k=global_cols 重聚；
        # 框数不足的页（首页标题跨栏等）保持 per-page 结论。
        divergent_pages = [
            pg
            for pg, cols in page_cols.items()
            if cols - global_cols > 1 and len(by_page.get(pg, [])) >= global_cols * 3
        ]
        for pg in list(divergent_pages):
            # silhouette 显著性豁免：该页单页结论的 silhouette 显著高于强制
            # global_cols 时（差 > margin），说明多出的栏是真实版面结构（如
            # 主体双栏文档里真四栏的附录页），尊重单页结论，不强砍——强砍
            # 恰好制造本回退要修的行级交错，只是换了一页。
            page_score = page_scores.get(pg, {}).get(page_cols[pg])
            global_score = page_scores.get(pg, {}).get(global_cols)
            if (
                page_score is not None
                and global_score is not None
                and page_score - global_score > SILHOUETTE_MARGIN
            ):
                divergent_pages.remove(pg)
                logger.info(
                    "DeepDoc 分栏全局回退豁免：单页 silhouette 显著更高",
                    page=pg,
                    page_cols=page_cols[pg],
                    page_score=page_score,
                    global_score=global_score,
                )
                continue
            page_cols[pg] = global_cols
        logger.info(
            "DeepDoc detected PDF columns",
            global_columns=global_cols,
            by_page=page_cols,
            divergent_pages=divergent_pages,
        )

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
    def final_reading_order(boxes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            boxes,
            key=lambda item: (
                int(item.get("page_number", 1)),
                int(item.get("col_id", 0)),
                float(item["top"]),
                float(item["x0"]),
            ),
        )
