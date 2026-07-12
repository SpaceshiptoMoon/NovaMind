from __future__ import annotations

# Adapted from RAGFlow deepdoc/vision/table_structure_recognizer.py

import logging
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from novamind.shared.knowledge.integrations.deepdoc.compat import rag_tokenizer
from novamind.shared.knowledge.integrations.deepdoc.vision.recognizer import Recognizer


def _default_model_dir() -> Path:
    env_dir = os.getenv("DEEPDOC_MODEL_DIR")
    if env_dir:
        return Path(env_dir)
    repo_root = Path(__file__).resolve().parents[6]
    return repo_root / ".cache" / "deepdoc"


class TableStructureRecognizer(Recognizer):
    labels = [
        "table",
        "table column",
        "table row",
        "table column header",
        "table projected row header",
        "table spanning cell",
    ]

    def __init__(self, *, autoload: bool = False):
        super().__init__(self.labels, domain="tsr", model_dir=_default_model_dir(), autoload=False)
        if autoload:
            self.load()

    def normalize_predictions(self, predictions: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
        res = []
        for table in predictions:
            normalized = [
                {
                    "label": item["type"],
                    "score": float(item["score"]),
                    "x0": item["bbox"][0],
                    "x1": item["bbox"][2],
                    "top": item["bbox"][1],
                    "bottom": item["bbox"][-1],
                }
                for item in table
            ]
            if not normalized:
                continue

            left = [box["x0"] for box in normalized if "row" in box["label"] or "header" in box["label"]]
            right = [box["x1"] for box in normalized if "row" in box["label"] or "header" in box["label"]]
            if left:
                left_edge = float(np.mean(left)) if len(left) > 4 else float(np.min(left))
                right_edge = float(np.mean(right)) if len(right) > 4 else float(np.max(right))
                for box in normalized:
                    if "row" in box["label"] or "header" in box["label"]:
                        if box["x0"] > left_edge:
                            box["x0"] = left_edge
                        if box["x1"] < right_edge:
                            box["x1"] = right_edge

            top = [box["top"] for box in normalized if box["label"] == "table column"]
            bottom = [box["bottom"] for box in normalized if box["label"] == "table column"]
            if top:
                top_edge = float(np.median(top)) if len(top) > 4 else float(np.min(top))
                bottom_edge = float(np.median(bottom)) if len(bottom) > 4 else float(np.max(bottom))
                for box in normalized:
                    if box["label"] == "table column":
                        if box["top"] > top_edge:
                            box["top"] = top_edge
                        if box["bottom"] < bottom_edge:
                            box["bottom"] = bottom_edge

            res.append(normalized)
        return res

    def __call__(self, images, thr=0.2, predictions=None):
        if predictions is None:
            predictions = self.forward(images, thr=thr)
        return self.normalize_predictions(predictions)

    def decode_outputs(self, outputs, metas: list[dict[str, Any]], thr: float = 0.2):
        if not outputs:
            return [[] for _ in metas]
        batch_output = outputs[0]
        decoded: list[list[dict[str, Any]]] = []
        for batch_index, meta in enumerate(metas):
            predictions = batch_output[batch_index] if isinstance(batch_output, np.ndarray) and batch_output.ndim >= 3 else batch_output
            table_predictions = []
            for row in predictions:
                values = np.asarray(row).reshape(-1)
                if values.size < 6:
                    continue
                x0, y0, x1, y1, score, class_id = values[:6]
                if float(score) < thr:
                    continue
                bbox = self.scale_bbox_to_original([float(x0), float(y0), float(x1), float(y1)], meta)
                table_predictions.append(
                    {
                        "type": self.labels[int(class_id)] if int(class_id) < len(self.labels) else str(int(class_id)),
                        "score": float(score),
                        "bbox": bbox,
                    }
                )
            decoded.append(table_predictions)
        return decoded

    @staticmethod
    def is_caption(box):
        patterns = [
            r"(?i)^fig(?:ure)?\.?\s*\d+",
            r"(?i)^table\s+\d+",
            r"^[\u56fe\u8868][ 0-9:\uFF1A]{2,}",
        ]
        text = (box.get("text") or "").strip()
        return any(re.match(pattern, text) for pattern in patterns) or "caption" in box.get("layout_type", "")

    @staticmethod
    def blockType(box):
        patterns = [
            (r"^(20|19)[0-9]{2}[-/][0-9]{1,2}[-/][0-9]{1,2}$", "Dt"),
            (r"^(20|19)[0-9]{2}$", "Dt"),
            (r"^[0-9.,+%/ -]+$", "Nu"),
            (r"^[0-9A-Z/\._~-]+$", "Ca"),
            (r"^[A-Z]*[a-z' -]+$", "En"),
            (r"^[0-9.,+-]+[0-9A-Za-z/$<>\(\)' -]+$", "NE"),
            (r"^.{1}$", "Sg"),
        ]
        text = (box.get("text") or "").strip()
        for pattern, name in patterns:
            if re.search(pattern, text):
                return name

        tokens = [token for token in rag_tokenizer.tokenize(text).split() if len(token) > 1]
        if len(tokens) > 3:
            return "Tx" if len(tokens) < 12 else "Lx"
        if len(tokens) == 1 and rag_tokenizer.tag(tokens[0]) == "nr":
            return "Nr"
        return "Ot"

    @staticmethod
    def construct_table(boxes, is_english=False, html=True, **kwargs):
        boxes = [dict(box) for box in boxes]
        caption = ""
        i = 0
        while i < len(boxes):
            if TableStructureRecognizer.is_caption(boxes[i]):
                if is_english and caption:
                    caption += " "
                caption += boxes[i]["text"]
                boxes.pop(i)
                continue
            i += 1

        if not boxes:
            return []

        for box in boxes:
            box["btype"] = TableStructureRecognizer.blockType(box)

        type_counts = Counter(box["btype"] for box in boxes)
        max_type = max(type_counts.items(), key=lambda item: item[1])[0] if type_counts else ""
        logging.debug("MAXTYPE: %s", max_type)

        row_heights = [box["R_bott"] - box["R_top"] for box in boxes if "R_bott" in box and "R_top" in box]
        row_threshold = float(np.min(row_heights)) if row_heights else 0
        boxes = Recognizer.sort_R_firstly(boxes, row_threshold / 2)
        boxes[0]["rn"] = 0
        rows = [[boxes[0]]]
        bottom = boxes[0]["bottom"]
        for box in boxes[1:]:
            box["rn"] = len(rows) - 1
            last_row = rows[-1]
            if last_row[-1].get("R", "") != box.get("R", "") or (box["top"] >= bottom - 3 and last_row[-1].get("R", "-1") != box.get("R", "-2")):
                bottom = box["bottom"]
                box["rn"] += 1
                rows.append([box])
                continue
            bottom = (bottom + box["bottom"]) / 2.0
            rows[-1].append(box)

        col_widths = [box["C_right"] - box["C_left"] for box in boxes if "C_right" in box and "C_left" in box]
        col_threshold = float(np.min(col_widths)) if col_widths else 0
        crosspage = len({box.get("page_number", 0) for box in boxes}) > 1
        boxes = Recognizer.sort_X_firstly(boxes, col_threshold / 2) if crosspage else Recognizer.sort_C_firstly(boxes, col_threshold / 2)
        boxes[0]["cn"] = 0
        cols = [[boxes[0]]]
        right = boxes[0]["x1"]
        for box in boxes[1:]:
            box["cn"] = len(cols) - 1
            last_col = cols[-1]
            if (int(box.get("C", "1")) - int(last_col[-1].get("C", "1")) == 1 and box.get("page_number", 0) == last_col[-1].get("page_number", 0)) or (
                box["x0"] >= right and last_col[-1].get("C", "-1") != box.get("C", "-2")
            ):
                right = box["x1"]
                box["cn"] += 1
                cols.append([box])
                continue
            right = (right + box["x1"]) / 2.0
            cols[-1].append(box)

        table = [[[] for _ in range(len(cols))] for _ in range(len(rows))]
        for box in boxes:
            table[box["rn"]][box["cn"]].append(box)

        if len(rows) >= 4:
            col_index = 0
            while col_index < len(table[0]):
                count, row_index = 0, 0
                for row_no in range(len(table)):
                    if table[row_no][col_index]:
                        count += 1
                        row_index = row_no
                    if count > 1:
                        break
                if count > 1:
                    col_index += 1
                    continue
                left_has_text = (col_index > 0 and table[row_index][col_index - 1] and table[row_index][col_index - 1][0].get("text")) or col_index == 0
                right_has_text = (col_index + 1 < len(table[row_index]) and table[row_index][col_index + 1] and table[row_index][col_index + 1][0].get("text")) or col_index + 1 >= len(table[row_index])
                if left_has_text and right_has_text:
                    col_index += 1
                    continue
                box = table[row_index][col_index][0]
                logging.debug("Relocate column single: %s", box["text"])
                left_distance, right_distance = 100000, 100000
                if col_index > 0 and not left_has_text:
                    for row_no in range(len(table)):
                        if table[row_no][col_index - 1]:
                            left_distance = min(left_distance, np.min([box["x0"] - item["x1"] for item in table[row_no][col_index - 1]]))
                if col_index + 1 < len(table[0]) and not right_has_text:
                    for row_no in range(len(table)):
                        if table[row_no][col_index + 1]:
                            right_distance = min(right_distance, np.min([item["x0"] - box["x1"] for item in table[row_no][col_index + 1]]))
                if left_distance < right_distance:
                    for adjust_col in range(col_index, len(table[0])):
                        for row_no in range(len(table)):
                            for item in table[row_no][adjust_col]:
                                item["cn"] -= 1
                    if table[row_index][col_index - 1]:
                        table[row_index][col_index - 1].extend(table[row_index][col_index])
                    else:
                        table[row_index][col_index - 1] = table[row_index][col_index]
                    for row_no in range(len(table)):
                        table[row_no].pop(col_index)
                else:
                    for adjust_col in range(col_index + 1, len(table[0])):
                        for row_no in range(len(table)):
                            for item in table[row_no][adjust_col]:
                                item["cn"] -= 1
                    if table[row_index][col_index + 1]:
                        table[row_index][col_index + 1].extend(table[row_index][col_index])
                    else:
                        table[row_index][col_index + 1] = table[row_index][col_index]
                    for row_no in range(len(table)):
                        table[row_no].pop(col_index)
                cols.pop(col_index)

        assert len(cols) == len(table[0]), "Column NO. miss matched: %d vs %d" % (len(cols), len(table[0]))

        if len(cols) >= 4:
            row_index = 0
            while row_index < len(table):
                count, col_index = 0, 0
                for col_no in range(len(table[row_index])):
                    if table[row_index][col_no]:
                        count += 1
                        col_index = col_no
                    if count > 1:
                        break
                if count > 1:
                    row_index += 1
                    continue
                up_has_text = (row_index > 0 and table[row_index - 1][col_index] and table[row_index - 1][col_index][0].get("text")) or row_index == 0
                down_has_text = (row_index + 1 < len(table) and table[row_index + 1][col_index] and table[row_index + 1][col_index][0].get("text")) or row_index + 1 >= len(table)
                if up_has_text and down_has_text:
                    row_index += 1
                    continue

                box = table[row_index][col_index][0]
                logging.debug("Relocate row single: %s", box["text"])
                up_distance, down_distance = 100000, 100000
                if row_index > 0 and not up_has_text:
                    for scan_col in range(len(table[row_index - 1])):
                        if table[row_index - 1][scan_col]:
                            up_distance = min(up_distance, np.min([box["top"] - item["bottom"] for item in table[row_index - 1][scan_col]]))
                if row_index + 1 < len(table) and not down_has_text:
                    for scan_col in range(len(table[row_index + 1])):
                        if table[row_index + 1][scan_col]:
                            down_distance = min(down_distance, np.min([item["top"] - box["bottom"] for item in table[row_index + 1][scan_col]]))
                if up_distance < down_distance:
                    for adjust_row in range(row_index, len(table)):
                        for scan_col in range(len(table[adjust_row])):
                            for item in table[adjust_row][scan_col]:
                                item["rn"] -= 1
                    if table[row_index - 1][col_index]:
                        table[row_index - 1][col_index].extend(table[row_index][col_index])
                    else:
                        table[row_index - 1][col_index] = table[row_index][col_index]
                    table.pop(row_index)
                else:
                    for adjust_row in range(row_index + 1, len(table)):
                        for scan_col in range(len(table[adjust_row])):
                            for item in table[adjust_row][scan_col]:
                                item["rn"] -= 1
                    if table[row_index + 1][col_index]:
                        table[row_index + 1][col_index].extend(table[row_index][col_index])
                    else:
                        table[row_index + 1][col_index] = table[row_index][col_index]
                    table.pop(row_index)
                rows.pop(row_index)

        header_rows = set()
        for row_index in range(len(table)):
            count, header_count = 0, 0
            for arr in table[row_index]:
                if not arr:
                    continue
                count += 1
                if max_type == "Nu" and arr[0]["btype"] == "Nu":
                    continue
                if any(item.get("H") for item in arr) or (max_type == "Nu" and arr[0]["btype"] != "Nu"):
                    header_count += 1
            if count and header_count / count > 0.5:
                header_rows.add(row_index)

        span_table = TableStructureRecognizer.__cal_spans(boxes, rows, cols, table, html)
        if html:
            return TableStructureRecognizer.__html_table(caption, header_rows, span_table)
        return TableStructureRecognizer.__desc_table(caption, header_rows, span_table, is_english)

    @staticmethod
    def __html_table(caption, header_rows, table):
        html = "<table>"
        if caption:
            html += f"<caption>{caption}</caption>"
        for row_index in range(len(table)):
            row = "<tr>"
            texts = []
            for arr in table[row_index]:
                if arr is None:
                    continue
                if not arr:
                    row += "<th></th>" if row_index in header_rows else "<td></td>"
                    continue
                threshold = min(float(np.min([cell["bottom"] - cell["top"] for cell in arr])) / 2, 10) if arr else 0
                txt = " ".join(cell["text"] for cell in Recognizer.sort_Y_firstly(arr, threshold))
                texts.append(txt)
                attrs = ""
                if arr[0].get("colspan"):
                    attrs = f" colspan={arr[0]['colspan']}"
                if arr[0].get("rowspan"):
                    attrs += f" rowspan={arr[0]['rowspan']}"
                tag = "th" if row_index in header_rows else "td"
                row += f"<{tag}{attrs}>{txt}</{tag}>"
            if row_index in header_rows:
                if all(text in header_rows for text in texts):
                    continue
                for text in texts:
                    header_rows.add(text)
            row += "</tr>"
            html += "\n" + row
        html += "\n</table>"
        return html

    @staticmethod
    def __desc_table(caption, header_row_numbers, table, is_english):
        column_count = len(table[0])
        row_count = len(table)
        headers = {}
        header_texts = []
        joiner = " for " if is_english else " of "

        for row_index in sorted(header_row_numbers):
            headers[row_index] = ["" for _ in range(column_count)]
            for col_index in range(column_count):
                if table[row_index][col_index]:
                    headers[row_index][col_index] = " ".join(item["text"].strip() for item in table[row_index][col_index])
            if all(not text for text in headers[row_index]):
                del headers[row_index]
                continue
            for col_index in range(column_count):
                if not headers[row_index][col_index] and col_index < len(header_texts):
                    headers[row_index][col_index] = header_texts[col_index]
            header_texts = headers[row_index]
        for row_index in range(row_count):
            if row_index not in header_row_numbers:
                continue
            for next_row_index in range(row_index + 1, row_count):
                if next_row_index not in header_row_numbers:
                    break
                for col_index in range(column_count):
                    if not headers[row_index][col_index]:
                        continue
                    if headers[next_row_index][col_index].find(headers[row_index][col_index]) >= 0:
                        continue
                    if len(headers[next_row_index][col_index]) > len(headers[row_index][col_index]):
                        headers[next_row_index][col_index] += (joiner if headers[next_row_index][col_index] else "") + headers[row_index][col_index]
                    else:
                        headers[next_row_index][col_index] = headers[row_index][col_index] + (joiner if headers[row_index][col_index] else "") + headers[next_row_index][col_index]

        row_text = []
        for row_index in range(row_count):
            if row_index in header_row_numbers:
                continue
            nearest_header = 0
            if headers:
                candidates = [(row_index - header_index, header_index) for header_index in headers if header_index < row_index]
                if candidates:
                    _, nearest_header = min(candidates, key=lambda item: item[0])

            parts = []
            for col_index in range(column_count):
                if not table[row_index][col_index]:
                    continue
                txt = "".join(item["text"].strip() for item in table[row_index][col_index])
                if not txt:
                    continue
                label = headers.get(nearest_header, [""] * column_count)[col_index] if nearest_header in headers else ""
                parts.append(f"{label}: {txt}" if label else txt)
            if parts:
                row_text.append("; ".join(parts))

        if caption:
            suffix = f" in {caption}" if is_english else f" from {caption}"
            row_text = [text + "\t--" + suffix for text in row_text]
        return row_text

    @staticmethod
    def __cal_spans(boxes, rows, cols, table, html=True):
        col_left = [float(np.mean([cell.get("C_left", cell["x0"]) for cell in col])) for col in cols]
        col_right = [float(np.mean([cell.get("C_right", cell["x1"]) for cell in col])) for col in cols]
        row_top = [float(np.mean([cell.get("R_top", cell["top"]) for cell in row])) for row in rows]
        row_bottom = [float(np.mean([cell.get("R_btm", cell["bottom"]) for cell in row])) for row in rows]

        for box in boxes:
            if "SP" not in box:
                continue
            box["colspan"] = [box["cn"]]
            box["rowspan"] = [box["rn"]]
            for col_index in range(len(col_left)):
                if col_index == box["cn"]:
                    continue
                if col_left[col_index] + (col_right[col_index] - col_left[col_index]) / 2 < box["H_left"]:
                    continue
                if col_right[col_index] - (col_right[col_index] - col_left[col_index]) / 2 > box["H_right"]:
                    continue
                box["colspan"].append(col_index)
            for row_index in range(len(row_top)):
                if row_index == box["rn"]:
                    continue
                if row_top[row_index] + (row_bottom[row_index] - row_top[row_index]) / 2 < box["H_top"]:
                    continue
                if row_bottom[row_index] - (row_bottom[row_index] - row_top[row_index]) / 2 > box["H_bott"]:
                    continue
                box["rowspan"].append(row_index)

        def join(arr):
            if not arr:
                return ""
            return "".join(item["text"] for item in arr)

        for row_index in range(len(table)):
            for col_index, arr in enumerate(table[row_index]):
                if not arr:
                    continue
                if all("rowspan" not in item and "colspan" not in item for item in arr):
                    continue
                rowspans, colspans = [], []
                for item in arr:
                    if isinstance(item.get("rowspan"), list):
                        rowspans.extend(item["rowspan"])
                    if isinstance(item.get("colspan"), list):
                        colspans.extend(item["colspan"])
                rowspans, colspans = sorted(set(rowspans)), sorted(set(colspans))
                if len(rowspans) < 2 and len(colspans) < 2:
                    for item in arr:
                        item.pop("rowspan", None)
                        item.pop("colspan", None)
                    continue
                rowspans = list(range(rowspans[0], rowspans[-1] + 1))
                colspans = list(range(colspans[0], colspans[-1] + 1))
                merged = []
                for row_no in rowspans:
                    for col_no in colspans:
                        merged_text = join(merged)
                        if table[row_no][col_no] and join(table[row_no][col_no]) != merged_text:
                            merged.extend(table[row_no][col_no])
                        table[row_no][col_no] = None if html else merged
                for item in merged:
                    if len(rowspans) > 1:
                        item["rowspan"] = len(rowspans)
                    else:
                        item.pop("rowspan", None)
                    if len(colspans) > 1:
                        item["colspan"] = len(colspans)
                    else:
                        item.pop("colspan", None)
                table[rowspans[0]][colspans[0]] = merged

        return table
