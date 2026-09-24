"""DeepDoc 版面识别器：检测页面中的文本块 / 标题 / 表格 / 图像区域。"""
from __future__ import annotations

# Adapted from RAGFlow deepdoc/vision/layout_recognizer.py
import os
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path

import numpy as np
from novamind.engines.document.integrations.deepdoc.vision.recognizer import Recognizer


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
        self.input_shape = (640, 640)
        if autoload:
            self.load()

    @staticmethod
    def _region_consumed_by_visited(layout: dict, consumed_regions: list[dict], threshold: float = 0.6) -> bool:
        """未访问 figure/equation 区域与某已访问区域**互相**覆盖 ≥ threshold 时视为重复检出。

        布局模型偶尔对「表+图混合页」输出一个罩住全部内容的巨型 figure 区域
        （实测 p12：整页 figure 与表区域双向覆盖 94%）。它是同一内容的重复
        检出，合成占位框会造出幻影 figure 组——抢走邻近题注、把整页 crop 成
        重复图。判据必须**双向**：单向覆盖会把表格内部嵌套的真图区域也吞掉
        （真图被表 bbox 单向覆盖 100%，但表被真图仅覆盖 <10%——内容不同，
        不是重复检出）。"""

        def overlap_area(a: dict, b: dict) -> float:
            w = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
            h = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
            return (w * h) if (w > 0 and h > 0) else 0.0

        def area(box: dict) -> float:
            return max(0.0, box["x1"] - box["x0"]) * max(0.0, box["bottom"] - box["top"])

        region_area = area(layout)
        if region_area <= 0:
            return False
        page = layout.get("page_number")
        for candidate in consumed_regions:
            if candidate is layout or candidate.get("page_number") != page:
                continue
            inter = overlap_area(layout, candidate)
            if inter <= 0:
                continue
            candidate_area = area(candidate)
            if inter / region_area >= threshold and inter / max(candidate_area, 1e-6) >= threshold:
                return True
        return False

    def apply_layouts(self, image_list, ocr_res, layouts, scale_factor=3, drop=True):
        def is_garbage(box):
            patterns = [r"\(cid\s*:\s*\d+\s*\)"]
            return any(re.search(pattern, box.get("text", "")) for pattern in patterns)

        assert len(image_list) == len(ocr_res)
        boxes = []
        page_layout = []
        garbages: dict[str, list[str]] = {}
        assert len(image_list) == len(layouts)

        scale_factors = scale_factor if isinstance(scale_factor, (list, tuple)) else [scale_factor] * len(image_list)
        if len(scale_factors) != len(image_list):
            scale_factors = [scale_factors[0] if scale_factors else 3] * len(image_list)

        for page_number, raw_layouts in enumerate(layouts):
            page_scale = scale_factors[page_number]
            page_boxes = [dict(box) for box in ocr_res[page_number]]
            normalized_layouts = [
                {
                    "type": item["type"],
                    "score": float(item["score"]),
                    "x0": item["bbox"][0] / page_scale,
                    "x1": item["bbox"][2] / page_scale,
                    "top": item["bbox"][1] / page_scale,
                    "bottom": item["bbox"][-1] / page_scale,
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
                        candidates[match_index]["type"] == "footer" and page_boxes[i]["bottom"] < image_height * 0.9 / page_scale,
                        candidates[match_index]["type"] == "header" and page_boxes[i]["top"] > image_height * 0.1 / page_scale,
                    ]
                    if drop and candidates[match_index]["type"] in self.garbage_layouts and not any(keep_features):
                        garbages.setdefault(candidates[match_index]["type"], []).append(page_boxes[i]["text"])
                        page_boxes.pop(i)
                        continue
                    page_boxes[i]["layoutno"] = f"{layout_type}-{match_index}"
                    page_boxes[i]["layout_type"] = candidates[match_index]["type"] if candidates[match_index]["type"] != "equation" else "figure"
                    i += 1

            for layout_type in ["footer", "reference", "figure caption", "table caption", "title", "table", "text", "figure", "equation"]:
                find_layout(layout_type)

            # 上游只给未访问的 figure/equation 区域合成占位框（layout_type="figure"）；
            # table 区域不合成——空 table 框会造出上游不存在的幻影表组，凭空生成
            # table_regions 并把整页正文卷进组 bbox。
            # figure 合成同样收口：未访问区域若与同页已访问 table/figure/equation
            # 区域**互相**覆盖 ≥ 阈值，是同一内容的重复检出（实测：整页 figure 区域
            # 与表区域双向覆盖 94%），合成占位框会造出幻影 figure 组——抢走邻近
            # 题注、把整页 crop 成一张重复图。双向判据不伤表格内部嵌套的真图区域
            # （真图被表 bbox 单向覆盖 100% 但反向 <10%，内容不同不算重复）。
            consumed_regions = [lt for lt in normalized_layouts if lt.get("visited") and lt["type"] in ["table", "figure", "equation"]]
            for index, layout in enumerate([lt for lt in normalized_layouts if lt["type"] in ["figure", "equation"]]):
                if layout.get("visited"):
                    continue
                if self._region_consumed_by_visited(layout, consumed_regions):
                    continue
                region_box = deepcopy(layout)
                region_box.pop("type")
                region_box["text"] = ""
                region_box["layout_type"] = "figure"
                region_box["layoutno"] = f"figure-{index}"
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
        self.center = True

    @staticmethod
    def _import_cv2():
        import cv2

        return cv2

    @staticmethod
    def _import_nms():
        from novamind.engines.document.integrations.deepdoc.vision.operators import nms

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
