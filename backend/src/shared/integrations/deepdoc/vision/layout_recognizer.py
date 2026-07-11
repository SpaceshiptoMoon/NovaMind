from __future__ import annotations

# Adapted from RAGFlow deepdoc/vision/layout_recognizer.py

import logging
import os
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from src.shared.integrations.deepdoc.vision.recognizer import Recognizer


def _default_model_dir() -> Path:
    env_dir = os.getenv("DEEPDOC_MODEL_DIR")
    if env_dir:
        return Path(env_dir)
    repo_root = Path(__file__).resolve().parents[6]
    return repo_root / ".cache" / "deepdoc"


class LayoutRecognizer(Recognizer):
    labels = [
        "_background_",
        "Text",
        "Title",
        "Figure",
        "Figure caption",
        "Table",
        "Table caption",
        "Header",
        "Footer",
        "Reference",
        "Equation",
    ]

    def __init__(self, domain: str = "layout", *, autoload: bool = False):
        super().__init__(self.labels, domain=domain, model_dir=_default_model_dir(), autoload=False)
        self.garbage_layouts = ["footer", "header", "reference"]
        self.client = None
        self.input_shape = (640, 640)
        if autoload:
            self.load()

    def apply_layouts(self, image_list, ocr_res, layouts, scale_factor=3, drop=True):
        def is_garbage(box):
            patterns = [r"\(cid\s*:\s*\d+\s*\)"]
            return any(re.search(pattern, box.get("text", "")) for pattern in patterns)

        assert len(image_list) == len(ocr_res)
        boxes = []
        page_layout = []
        garbages: dict[str, list[str]] = {}
        assert len(image_list) == len(layouts)

        for page_number, raw_layouts in enumerate(layouts):
            page_boxes = [dict(box) for box in ocr_res[page_number]]
            normalized_layouts = [
                {
                    "type": item["type"],
                    "score": float(item["score"]),
                    "x0": item["bbox"][0] / scale_factor,
                    "x1": item["bbox"][2] / scale_factor,
                    "top": item["bbox"][1] / scale_factor,
                    "bottom": item["bbox"][-1] / scale_factor,
                    "page_number": page_number,
                }
                for item in raw_layouts
                if float(item["score"]) >= 0.4 or item["type"] not in self.garbage_layouts
            ]
            mean_height = np.mean([lt["bottom"] - lt["top"] for lt in normalized_layouts]) if normalized_layouts else 0
            normalized_layouts = self.sort_Y_firstly(normalized_layouts, mean_height / 2 if mean_height else 0)
            normalized_layouts = self.layouts_cleanup(page_boxes, normalized_layouts)
            page_layout.append(normalized_layouts)

            def find_layout(layout_type: str):
                nonlocal page_boxes, normalized_layouts
                candidates = [lt for lt in normalized_layouts if lt["type"] == layout_type]
                i = 0
                while i < len(page_boxes):
                    if page_boxes[i].get("layout_type"):
                        i += 1
                        continue
                    if is_garbage(page_boxes[i]):
                        page_boxes.pop(i)
                        continue
                    match_index = self.find_overlapped_with_threshold(page_boxes[i], candidates, thr=0.4)
                    if match_index is None:
                        page_boxes[i]["layout_type"] = ""
                        i += 1
                        continue
                    candidates[match_index]["visited"] = True
                    image_height = image_list[page_number].shape[0] if hasattr(image_list[page_number], "shape") else image_list[page_number].size[1]
                    keep_features = [
                        candidates[match_index]["type"] == "footer" and page_boxes[i]["bottom"] < image_height * 0.9 / scale_factor,
                        candidates[match_index]["type"] == "header" and page_boxes[i]["top"] > image_height * 0.1 / scale_factor,
                    ]
                    if drop and candidates[match_index]["type"] in self.garbage_layouts and not any(keep_features):
                        garbages.setdefault(candidates[match_index]["type"], []).append(page_boxes[i]["text"])
                        page_boxes.pop(i)
                        continue
                    page_boxes[i]["layoutno"] = f"{layout_type}-{match_index}"
                    page_boxes[i]["layout_type"] = candidates[match_index]["type"] if candidates[match_index]["type"] != "equation" else "figure"
                    i += 1

            for layout_type in ["footer", "header", "reference", "figure caption", "table caption", "title", "table", "text", "figure", "equation"]:
                find_layout(layout_type)

            for index, layout in enumerate([lt for lt in normalized_layouts if lt["type"] in ["figure", "equation", "table"]]):
                if layout.get("visited"):
                    continue
                region_box = deepcopy(layout)
                layout_type = region_box.pop("type")
                region_box["text"] = ""
                region_box["layout_type"] = "figure" if layout_type in {"figure", "equation"} else "table"
                region_box["layoutno"] = f"{region_box['layout_type']}-{index}"
                page_boxes.append(region_box)

            boxes.extend(page_boxes)

        garbage_set = set()
        for key in garbages.keys():
            counter = Counter(garbages[key])
            for garbage_text, count in counter.items():
                if count > 1:
                    garbage_set.add(garbage_text)

        boxes = [box for box in boxes if box["text"].strip() not in garbage_set]
        return boxes, page_layout

    def __call__(self, image_list, ocr_res, scale_factor=3, thr=0.2, batch_size=16, drop=True, layouts=None):
        if layouts is None:
            layouts = self.forward(image_list, thr=thr, batch_size=batch_size)
        return self.apply_layouts(image_list, ocr_res, layouts, scale_factor=scale_factor, drop=drop)

    def decode_outputs(self, outputs, metas: list[dict[str, Any]], thr: float = 0.2):
        if not outputs:
            return [[] for _ in metas]
        batch_output = outputs[0]
        decoded: list[list[dict[str, Any]]] = []
        for batch_index, meta in enumerate(metas):
            predictions = batch_output[batch_index] if isinstance(batch_output, np.ndarray) and batch_output.ndim >= 3 else batch_output
            page_layouts = []
            for row in predictions:
                values = np.asarray(row).reshape(-1)
                if values.size < 6:
                    continue
                x0, y0, x1, y1, score, class_id = values[:6]
                if float(score) < thr:
                    continue
                bbox = self.scale_bbox_to_original([float(x0), float(y0), float(x1), float(y1)], meta)
                page_layouts.append(
                    {
                        "type": self.labels[int(class_id)] if int(class_id) < len(self.labels) else str(int(class_id)),
                        "score": float(score),
                        "bbox": bbox,
                    }
                )
            decoded.append(page_layouts)
        return decoded


class LayoutRecognizer4YOLOv10(LayoutRecognizer):
    labels = [
        "title",
        "Text",
        "Reference",
        "Figure",
        "Figure caption",
        "Table",
        "Table caption",
        "Table caption",
        "Equation",
        "Figure caption",
    ]

    def __init__(self, domain="layout", *, autoload: bool = False):
        super().__init__(domain="layout", autoload=autoload)
        self.auto = False
        self.scaleFill = False
        self.scaleup = True
        self.stride = 32
        self.center = True

    @staticmethod
    def _import_cv2():
        import cv2

        return cv2

    @staticmethod
    def _import_nms():
        from src.shared.integrations.deepdoc.vision.operators import nms

        return nms

    def preprocess(self, image_list):
        self.ensure_loaded()
        cv2 = self._import_cv2()
        inputs = []
        new_shape = self.input_shape
        for image in image_list:
            img = np.array(image) if not isinstance(image, np.ndarray) else image
            shape = img.shape[:2]
            ratio = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
            new_unpad = int(round(shape[1] * ratio)), int(round(shape[0] * ratio))
            dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]
            dw /= 2
            dh /= 2
            ww, hh = new_unpad
            img = np.array(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).astype(np.float32)
            img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
            top, bottom = (int(round(dh - 0.1)), int(round(dh + 0.1))) if self.center else (0, 0)
            left, right = (int(round(dw - 0.1)), int(round(dw + 0.1))) if self.center else (0, 0)
            img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
            img /= 255.0
            img = img.transpose(2, 0, 1)
            img = img[np.newaxis, :, :, :].astype(np.float32)
            inputs.append({self.input_names[0]: img, "scale_factor": [shape[1] / ww, shape[0] / hh, dw, dh]})
        return inputs

    def postprocess(self, boxes, inputs, thr):
        thr = 0.08
        boxes = np.squeeze(boxes)
        scores = boxes[:, 4]
        boxes = boxes[scores > thr, :]
        scores = scores[scores > thr]
        if len(boxes) == 0:
            return []

        class_ids = boxes[:, -1].astype(int)
        boxes = boxes[:, :4]
        boxes[:, 0] -= inputs["scale_factor"][2]
        boxes[:, 2] -= inputs["scale_factor"][2]
        boxes[:, 1] -= inputs["scale_factor"][3]
        boxes[:, 3] -= inputs["scale_factor"][3]
        input_shape = np.array([inputs["scale_factor"][0], inputs["scale_factor"][1], inputs["scale_factor"][0], inputs["scale_factor"][1]])
        boxes = np.multiply(boxes, input_shape, dtype=np.float32)

        unique_class_ids = np.unique(class_ids)
        nms = self._import_nms()
        indices = []
        for class_id in unique_class_ids:
            class_indices = np.where(class_ids == class_id)[0]
            class_boxes = boxes[class_indices, :]
            class_scores = scores[class_indices]
            class_keep_boxes = nms(class_boxes, class_scores, 0.45)
            indices.extend(class_indices[class_keep_boxes])

        return [{"type": self.label_list[class_ids[index]].lower(), "bbox": [float(value) for value in boxes[index].tolist()], "score": float(scores[index])} for index in indices]


class AscendLayoutRecognizer(LayoutRecognizer):
    pass
