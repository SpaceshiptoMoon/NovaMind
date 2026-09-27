"""DeepDoc 通用识别器：统一 OCR / 版面 / 表格识别的调用接口。"""
from __future__ import annotations

# Adapted toward RAGFlow deepdoc/vision/recognizer.py
import gc
import logging
import math
from collections.abc import Sequence
from functools import cmp_to_key
from pathlib import Path
from typing import Any

import numpy as np
from novamind.engines.document.integrations.deepdoc.vision.model_manager import (
    ensure_model_group_available,
)
from novamind.shared.logging import get_logger

_logger = get_logger(__name__)

# 模块级 onnx session 缓存（对齐 ocr.load_model 的 loaded_models 口径）：
# key = 模型文件绝对路径。arq max_jobs 并发下每个解析任务各自 new Recognizer
# 实例，无缓存时 layout/tsr session 每任务各一份、内存线性翻倍；session 线程
# 安全可共享，共享同一份即可。包装实例状态（labels/input_shape 等）仍是
# per-instance 的，只有底层 session 复用。
_SESSION_CACHE: dict[str, tuple[Any, Any]] = {}  # path -> (InferenceSession, RunOptions)


class Recognizer:
    """ONNX 检测模型基类：封装 preprocess → 批量推理 → postprocess 主链与几何工具箱。

    版面识别（layout）与表格结构识别（tsr）继承本类；检测输出统一为
    [{"type", "bbox", "score"}]，bbox 为 [x0, top, x1, bottom] 原图像素坐标。
    推理 session 按模型文件路径做模块级缓存，跨实例共享（session 线程安全）；
    labels/input_shape 等包装状态仍为各实例独立。
    """
    @staticmethod
    def _import_cv2():
        """惰性导入 cv2（重依赖延迟到真实推理时才加载）。"""
        import cv2

        return cv2

    @staticmethod
    def _import_onnxruntime():
        """惰性导入 onnxruntime。"""
        import onnxruntime as ort

        return ort

    def __init__(
        self,
        labels: Sequence[str] | None = None,
        domain: str | None = None,
        model_dir: str | Path | None = None,
        *,
        model_filename: str | None = None,
        autoload: bool = False,
    ):
        """初始化识别器元数据，默认不加载模型文件。

        Args:
            labels: 类别标签表，索引与模型输出类别 id 对应。
            domain: 模型域标识（layout/tsr 等），用于日志与模型文件名默认值。
            model_dir: ONNX 模型文件所在目录；None 表示仅在显式配置时加载。
            model_filename: 模型文件名，默认 ``<domain>.onnx``。
            autoload: 是否立即调用 load() 加载模型。
        """
        self.labels = list(labels or [])
        self.domain = domain or "recognizer"
        self.model_dir = Path(model_dir) if model_dir is not None else None
        self.model_filename = model_filename or (f"{self.domain}.onnx" if self.domain else None)
        self.session: Any = None
        self.ort_sess: Any = None
        self.run_options: Any = None
        self.input_name: str | None = None
        self.input_names: list[str] = []
        self.output_names: list[str] = []
        self.loaded = False
        self.input_shape = (640, 640)
        self.label_list = self.labels
        if autoload:
            self.load()

    def load(self):
        """加载 ONNX session（按模型路径模块级缓存，重复加载直接复用）。

        layout / tsr 域先做模型文件完整性检查，缺文件直接抛错（此处不触发联网下载）。

        Returns:
            self，支持链式调用。

        Raises:
            FileNotFoundError: 模型文件不存在。
        """
        _logger.info("DeepDoc 识别器模型开始加载", domain=self.domain, model_filename=self.model_filename)
        ort = self._import_onnxruntime()
        if self.domain in {"layout", "tsr"}:
            ensure_model_group_available(self.domain, self.model_dir)
        model_path = self._resolve_model_path()
        if model_path is None or not model_path.exists():
            raise FileNotFoundError(f"DeepDoc recognizer model not found for domain '{self.domain}': {model_path}")

        providers = ["CPUExecutionProvider"]
        cache_key = str(model_path.resolve())
        cached = _SESSION_CACHE.get(cache_key)
        if cached is not None:
            self.ort_sess, self.run_options = cached
            _logger.info("DeepDoc 识别器模型复用已加载 session", domain=self.domain, model_path=str(model_path))
        else:
            options = ort.SessionOptions()
            options.enable_cpu_mem_arena = False
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            self.ort_sess = ort.InferenceSession(str(model_path), sess_options=options, providers=providers)
            self.run_options = ort.RunOptions()
            _SESSION_CACHE[cache_key] = (self.ort_sess, self.run_options)
        self.session = self.ort_sess
        self.input_name = self.ort_sess.get_inputs()[0].name
        self.input_names = [node.name for node in self.ort_sess.get_inputs()]
        self.output_names = [node.name for node in self.ort_sess.get_outputs()]
        input_shape = self.ort_sess.get_inputs()[0].shape[2:4]
        if len(input_shape) == 2 and all(isinstance(v, int) and v > 0 for v in input_shape):
            self.input_shape = tuple(input_shape)
        self.loaded = True
        _logger.info(
            "DeepDoc 识别器模型加载完成",
            domain=self.domain,
            model_path=str(model_path),
            input_shape=self.input_shape,
            input_names=self.input_names,
            output_names=self.output_names,
            providers=providers,
        )
        return self

    def ensure_loaded(self):
        """断言模型已加载，否则抛出 RuntimeError 并提示期望的模型路径。"""
        if not self.loaded or self.ort_sess is None or self.input_name is None:
            raise RuntimeError(f"DeepDoc recognizer '{self.domain}' is not loaded. Expected model file '{self.model_filename}' under '{self.model_dir}'.")

    def _resolve_model_path(self) -> Path | None:
        """拼接 model_dir 与 model_filename 得到模型文件路径（配置不全时为 None）。"""
        if self.model_dir is None or self.model_filename is None:
            return None
        return self.model_dir / self.model_filename

    def create_inputs(self, imgs, im_info):
        """组装 PaddleDetection 风格的模型输入 feed。

        单图直接走 (1, C, H, W) 通道；多图按批内最大高宽零填充成批，
        im_shape / scale_factor 记录各图缩放后形状与缩放比，供 postprocess 把
        检测框映射回原图像素坐标。
        """
        inputs: dict[str, Any] = {}
        if len(imgs) == 1:
            inputs["image"] = np.array((imgs[0],)).astype("float32")
            inputs["im_shape"] = np.array((im_info[0]["im_shape"],)).astype("float32")
            inputs["scale_factor"] = np.array((im_info[0]["scale_factor"],)).astype("float32")
            return inputs

        im_shape = np.array([info["im_shape"] for info in im_info], dtype="float32")
        scale_factor = np.array([info["scale_factor"] for info in im_info], dtype="float32")
        inputs["im_shape"] = np.concatenate(im_shape, axis=0)
        inputs["scale_factor"] = np.concatenate(scale_factor, axis=0)

        imgs_shape = [[image.shape[1], image.shape[2]] for image in imgs]
        max_shape_h = max(shape[0] for shape in imgs_shape)
        max_shape_w = max(shape[1] for shape in imgs_shape)
        padding_imgs = []
        for img in imgs:
            im_c, im_h, im_w = img.shape[:]
            padding_im = np.zeros((im_c, max_shape_h, max_shape_w), dtype=np.float32)
            padding_im[:, :im_h, :im_w] = img
            padding_imgs.append(padding_im)
        inputs["image"] = np.stack(padding_imgs, axis=0)
        return inputs

    def preprocess(self, image_list):
        """批量图像预处理，按模型接口族产出输入张量。

        两条分支：
        - PaddleDetection 风格（模型输入含 scale_factor）：LinearResize → 标准化 →
          CHW → PadStride(32)，逐图经 create_inputs 组装；
        - 固定输入（input_shape 如 640×640）：灰度扩三通道、RGBA 丢 alpha、
          BGR→RGB、resize 到 input_shape、/255、CHW；scale_factor 记录
          原图尺寸/模型输入尺寸，供 postprocess 映射回原图坐标。

        Args:
            image_list: 本批图像列表（HWC ndarray 或可转 ndarray 的对象）。
        """
        self.ensure_loaded()
        inputs = []
        if "scale_factor" in self.input_names:
            from novamind.engines.document.integrations.deepdoc.vision import operators
            from novamind.engines.document.integrations.deepdoc.vision.operators import preprocess

            preprocess_ops = []
            for op_info in [
                {"interp": 2, "keep_ratio": False, "target_size": [800, 608], "type": "LinearResize"},
                {"is_scale": True, "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225], "type": "StandardizeImag"},
                {"type": "Permute"},
                {"stride": 32, "type": "PadStride"},
            ]:
                operator_info = op_info.copy()
                op_type = operator_info.pop("type")
                preprocess_ops.append(getattr(operators, op_type)(**operator_info))

            for image in image_list:
                normalized = np.array(image) if not isinstance(image, np.ndarray) else image
                im, im_info = preprocess(normalized, preprocess_ops)
                inputs.append(self.create_inputs([im], [im_info]))
            return inputs

        hh, ww = self.input_shape
        cv2 = self._import_cv2()
        for image in image_list:
            img = np.array(image) if not isinstance(image, np.ndarray) else image
            if img.ndim == 2:
                img = np.stack([img, img, img], axis=-1)
            if img.shape[2] == 4:
                img = img[:, :, :3]
            h, w = img.shape[:2]
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img = cv2.resize(np.array(img).astype("float32"), (ww, hh))
            img /= 255.0
            img = img.transpose(2, 0, 1)
            img = img[np.newaxis, :, :, :].astype(np.float32)
            inputs.append({self.input_names[0]: img, "scale_factor": [w / ww, h / hh]})
        return inputs

    def _run_model_batch(self, batch_inputs):
        """以模型输入名为 feed dict 跑一次推理（支持 ndarray 与输入 dict 两种形态）。"""
        self.ensure_loaded()
        assert self.ort_sess is not None
        if isinstance(batch_inputs, np.ndarray):
            feed_dict = {self.input_name: batch_inputs}
        else:
            feed_dict = {key: value for key, value in batch_inputs.items() if key in self.input_names}
        return self.ort_sess.run(None, feed_dict, self.run_options)

    def postprocess(self, boxes, inputs, thr):
        """把模型原始输出解析为检测框。

        两条分支：
        - PaddleDetection 风格：输出为 N×6 [类别id, 置信度, x0, top, x1, bottom]，
          坐标已是原图像素（模型图内部用 scale_factor 映射回），按阈值过滤后回填标签；
        - 固定输入风格（YOLO 系导出）：输出为 [cx, cy, w, h, 各类得分...]，先按
          得分过滤，再解码 xywh→xyxy 并经 scale_factor 映射回原图像素，最后按类别
          做贪心 NMS（IoU>0.2 抑制）。

        Args:
            boxes: 模型原始输出张量。
            inputs: preprocess 产出的输入 dict（取 scale_factor 做坐标映射回）。
            thr: 置信度阈值，低于该值的框丢弃。

        Returns:
            [{"type": 小写类别名, "bbox": [x0, top, x1, bottom]（原图像素）, "score": 置信度}]。
        """
        if "scale_factor" in self.input_names:
            result = []
            for box in boxes:
                clsid, bbox, score = int(box[0]), box[2:], box[1]
                if score < thr or clsid >= len(self.label_list):
                    continue
                result.append({"type": self.label_list[clsid].lower(), "bbox": [float(value) for value in bbox.tolist()], "score": float(score)})
            return result

        def xywh2xyxy(values):
            transformed = np.copy(values)
            transformed[:, 0] = values[:, 0] - values[:, 2] / 2
            transformed[:, 1] = values[:, 1] - values[:, 3] / 2
            transformed[:, 2] = values[:, 0] + values[:, 2] / 2
            transformed[:, 3] = values[:, 1] + values[:, 3] / 2
            return transformed

        def compute_iou(box, other_boxes):
            xmin = np.maximum(box[0], other_boxes[:, 0])
            ymin = np.maximum(box[1], other_boxes[:, 1])
            xmax = np.minimum(box[2], other_boxes[:, 2])
            ymax = np.minimum(box[3], other_boxes[:, 3])
            intersection_area = np.maximum(0, xmax - xmin) * np.maximum(0, ymax - ymin)
            box_area = (box[2] - box[0]) * (box[3] - box[1])
            boxes_area = (other_boxes[:, 2] - other_boxes[:, 0]) * (other_boxes[:, 3] - other_boxes[:, 1])
            union_area = box_area + boxes_area - intersection_area
            return intersection_area / union_area

        def iou_filter(candidate_boxes, scores, iou_threshold):
            sorted_indices = np.argsort(scores)[::-1]
            keep_boxes = []
            while sorted_indices.size > 0:
                box_id = sorted_indices[0]
                keep_boxes.append(box_id)
                ious = compute_iou(candidate_boxes[box_id, :], candidate_boxes[sorted_indices[1:], :])
                keep_indices = np.where(ious < iou_threshold)[0]
                sorted_indices = sorted_indices[keep_indices + 1]
            return keep_boxes

        boxes = np.squeeze(boxes).T
        scores = np.max(boxes[:, 4:], axis=1)
        boxes = boxes[scores > thr, :]
        scores = scores[scores > thr]
        if len(boxes) == 0:
            return []

        class_ids = np.argmax(boxes[:, 4:], axis=1)
        boxes = boxes[:, :4]
        input_shape = np.array([inputs["scale_factor"][0], inputs["scale_factor"][1], inputs["scale_factor"][0], inputs["scale_factor"][1]])
        boxes = np.multiply(boxes, input_shape, dtype=np.float32)
        boxes = xywh2xyxy(boxes)

        unique_class_ids = np.unique(class_ids)
        indices = []
        for class_id in unique_class_ids:
            class_indices = np.where(class_ids == class_id)[0]
            class_boxes = boxes[class_indices, :]
            class_scores = scores[class_indices]
            class_keep_boxes = iou_filter(class_boxes, class_scores, 0.2)
            indices.extend(class_indices[class_keep_boxes])

        return [{"type": self.label_list[class_ids[index]].lower(), "bbox": [float(value) for value in boxes[index].tolist()], "score": float(scores[index])} for index in indices]

    @staticmethod
    def sort_Y_firstly(arr, threshold):
        """按 top 升序为主排序，top 差小于阈值时改比 x0（同行内横排）。"""
        def cmp(c1, c2):
            diff = c1["top"] - c2["top"]
            if abs(diff) < threshold:
                diff = c1["x0"] - c2["x0"]
            return diff

        return sorted(arr, key=cmp_to_key(cmp))

    @staticmethod
    def sort_X_firstly(arr, threshold):
        """按 x0 升序为主排序，差小于阈值时改比 top（同列内纵排）。"""
        def cmp(c1, c2):
            diff = c1["x0"] - c2["x0"]
            if abs(diff) < threshold:
                diff = c1["top"] - c2["top"]
            return diff

        return sorted(arr, key=cmp_to_key(cmp))

    @staticmethod
    def sort_C_firstly(arr, thr=0):
        """先按 X 排序，再按 C（列号）属性冒泡整理：列号升序、同列按 top（列优先阅读序）。"""
        arr = Recognizer.sort_X_firstly(arr, thr)
        for i in range(len(arr) - 1):
            for j in range(i, -1, -1):
                if "C" not in arr[j] or "C" not in arr[j + 1]:
                    continue
                if arr[j + 1]["C"] < arr[j]["C"] or (arr[j + 1]["C"] == arr[j]["C"] and arr[j + 1]["top"] < arr[j]["top"]):
                    arr[j], arr[j + 1] = arr[j + 1], arr[j]
        return arr

    @staticmethod
    def sort_R_firstly(arr, thr=0):
        """先按 Y 排序，再按 R（行号）属性冒泡整理：行号升序、同行按 x0（行优先阅读序）。"""
        arr = Recognizer.sort_Y_firstly(arr, thr)
        for i in range(len(arr) - 1):
            for j in range(i, -1, -1):
                if "R" not in arr[j] or "R" not in arr[j + 1]:
                    continue
                if arr[j + 1]["R"] < arr[j]["R"] or (arr[j + 1]["R"] == arr[j]["R"] and arr[j + 1]["x0"] < arr[j]["x0"]):
                    arr[j], arr[j + 1] = arr[j + 1], arr[j]
        return arr

    @staticmethod
    def overlapped_area(a, b, ratio=True):
        """计算 a 与 b 的交集面积。

        ratio=True 时返回交集占 a 自身面积的比例（0~1）；ratio=False 时返回像素面积。
        x 或 y 投影不相交时返回 0。
        """
        top, bottom, x0, x1 = a["top"], a["bottom"], a["x0"], a["x1"]
        if b["x0"] > x1 or b["x1"] < x0:
            return 0
        if b["bottom"] < top or b["top"] > bottom:
            return 0
        x0_ = max(b["x0"], x0)
        x1_ = min(b["x1"], x1)
        top_ = max(b["top"], top)
        bottom_ = min(b["bottom"], bottom)
        area = (bottom_ - top_) * (x1_ - x0_) if x1 - x0 != 0 and bottom - top != 0 else 0
        if area > 0 and ratio:
            area /= (x1 - x0) * (bottom - top)
        return area

    @staticmethod
    def layouts_cleanup(boxes, layouts, far=2, thr=0.7):
        """去重同类且相互重叠的版面区域。

        索引相邻（距离 < far）的同类型区域，任一方向被对方覆盖比例 ≥ thr 即判为
        重复检出：双方都有 score 时弃分低者；否则统计区域内 OCR 框覆盖面积，弃
        覆盖小者。layouts 原地修改并返回。

        Args:
            boxes: 该页 OCR 框列表（无 score 兜底时用于估算区域内容覆盖）。
            layouts: 待去重的版面区域列表。
            far: 配对的最大索引距离。
            thr: 覆盖比例阈值。
        """
        def not_overlapped(a, b):
            return any([a["x1"] < b["x0"], a["x0"] > b["x1"], a["bottom"] < b["top"], a["top"] > b["bottom"]])

        i = 0
        while i + 1 < len(layouts):
            j = i + 1
            while j < min(i + far, len(layouts)) and (layouts[i].get("type", "") != layouts[j].get("type", "") or not_overlapped(layouts[i], layouts[j])):
                j += 1
            if j >= min(i + far, len(layouts)):
                i += 1
                continue
            if Recognizer.overlapped_area(layouts[i], layouts[j]) < thr and Recognizer.overlapped_area(layouts[j], layouts[i]) < thr:
                i += 1
                continue

            if layouts[i].get("score") and layouts[j].get("score"):
                if layouts[i]["score"] > layouts[j]["score"]:
                    layouts.pop(j)
                else:
                    layouts.pop(i)
                continue

            area_i, area_j = 0, 0
            for box in boxes:
                if not not_overlapped(box, layouts[i]):
                    area_i += Recognizer.overlapped_area(box, layouts[i], False)
                if not not_overlapped(box, layouts[j]):
                    area_j += Recognizer.overlapped_area(box, layouts[j], False)

            if area_i > area_j:
                layouts.pop(j)
            else:
                layouts.pop(i)
        return layouts

    @staticmethod
    def find_overlapped(box, boxes_sorted_by_y, naive=False):
        """在按 top 升序排列的候选框中找被 box 覆盖比例最大者。

        默认先按 y 投影二分收窄窗口再线性扫描；naive=True 时跳过二分直接全扫。

        Args:
            box: 目标框。
            boxes_sorted_by_y: 已按 top 升序排列的候选框。
            naive: 是否跳过二分收窄。

        Returns:
            覆盖比例最大候选的下标；候选列表为空或无任何重叠时返回 None。
        """
        if not boxes_sorted_by_y:
            return None
        boxes = boxes_sorted_by_y
        start, end, mid = 0, len(boxes), 0
        while start < end and not naive:
            mid = (end + start) // 2
            pivot = boxes[mid]
            if box["bottom"] < pivot["top"]:
                end = mid
                continue
            if box["top"] > pivot["bottom"]:
                start = mid + 1
                continue
            break
        while start < mid:
            if box["top"] > boxes[start]["bottom"]:
                start += 1
            break
        while end - 1 > mid:
            if box["bottom"] < boxes[end - 1]["top"]:
                end -= 1
            break

        max_overlapped_i, max_overlapped = None, 0
        for index in range(start, end):
            overlapped = Recognizer.overlapped_area(boxes[index], box)
            if overlapped <= max_overlapped:
                continue
            max_overlapped_i = index
            max_overlapped = overlapped
        return max_overlapped_i

    @staticmethod
    def find_horizontally_tightest_fit(box, boxes):
        """找与 box 同 layoutno 且水平方向最贴合的候选（x0 左缘差、x1 右缘差、中线
        偏移三者最小）。

        Returns:
            最优候选下标；候选列表为空或无同 layoutno 候选时返回 None。
        """
        if not boxes:
            return None
        min_distance, min_index = 1000000, None
        for index, candidate in enumerate(boxes):
            if box.get("layoutno", "0") != candidate.get("layoutno", "0"):
                continue
            distance = min(
                abs(box["x0"] - candidate["x0"]),
                abs(box["x1"] - candidate["x1"]),
                abs(box["x0"] + box["x1"] - candidate["x1"] - candidate["x0"]) / 2,
            )
            if distance < min_distance:
                min_index = index
                min_distance = distance
        return min_index

    @staticmethod
    def find_overlapped_with_threshold(box, boxes: Sequence[dict], thr=0.3):
        """找与 box 覆盖比例首个达到 thr 的候选（同为正向覆盖时取反向覆盖更大者）。

        比较语义为 (正向覆盖, 反向覆盖) 元组字典序；候选列表为空或无达标者返回 None。
        """
        if not boxes:
            return None
        max_overlapped_i, max_overlapped, reverse_overlapped = None, thr, 0
        for index, candidate in enumerate(boxes):
            overlapped = Recognizer.overlapped_area(box, candidate)
            reverse = Recognizer.overlapped_area(candidate, box)
            if (overlapped, reverse) < (max_overlapped, reverse_overlapped):
                continue
            max_overlapped_i = index
            max_overlapped = overlapped
            reverse_overlapped = reverse
        return max_overlapped_i

    def forward(self, image_list, thr: float = 0.2, batch_size: int = 16):
        # Detection-only path. Delegate to the BASE __call__ explicitly so
        # subclasses that override __call__ with a fuller pipeline signature
        # (e.g. LayoutRecognizer.__call__ needs ocr_res) do not dispatch here.
        # Mirrors upstream RAGFlow's LayoutRecognizer.forward = super().__call__.
        """纯检测主链（preprocess → 批量推理 → postprocess）。

        显式委托基类 __call__：子类若以更全的管线签名覆写 __call__
        （如 LayoutRecognizer.__call__ 需要接收 ocr_res），不会误派发到子类实现。
        """
        return Recognizer.__call__(self, image_list, thr=thr, batch_size=batch_size)

    def close(self):
        """丢弃本实例的 session 引用并触发 GC；session 为模块缓存共享时，最后一个引用释放后才真正回收内存。"""
        logging.info("Close recognizer.")
        if hasattr(self, "ort_sess"):
            del self.ort_sess
        if hasattr(self, "session"):
            self.session = None
        gc.collect()

    def __call__(self, image_list, thr=0.7, batch_size=16):
        """批量主链：按 batch_size 切批 → preprocess → 推理 → postprocess。

        Args:
            image_list: 页面图像列表（HWC ndarray）。
            thr: 置信度阈值，透传给 postprocess。
            batch_size: 每批图像数；切批只控制单次推理内存峰值，结果按原顺序拼接。

        Returns:
            每页一个检测框列表（顺序与输入一致）；模型空输出时该页为 []。
        """
        self.ensure_loaded()
        results = []
        images = []
        for image in image_list:
            images.append(np.array(image) if not isinstance(image, np.ndarray) else image)

        batch_loop_count = math.ceil(float(len(images)) / batch_size) if images else 0
        for index in range(batch_loop_count):
            start_index = index * batch_size
            end_index = min((index + 1) * batch_size, len(images))
            batch_image_list = images[start_index:end_index]
            batch_inputs = self.preprocess(batch_image_list)
            logging.debug("recognizer preprocess complete for %s batch %s", self.domain, index)
            for inputs in batch_inputs:
                outputs = self._run_model_batch(inputs)
                if not outputs:
                    _logger.warning(
                        "DeepDoc 识别器模型返回空输出",
                        domain=self.domain,
                        batch_index=index,
                    )
                    results.append([])
                    continue
                results.append(self.postprocess(outputs[0], inputs, thr))
        return results

    def __del__(self):
        """析构时触发 close() 释放资源。"""
        self.close()
