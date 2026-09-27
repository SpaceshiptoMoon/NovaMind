#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
"""DeepDoc OCR 运行时：DB 文本检测 + CTC 文本识别两阶段推理，及整合两者的 OCR 门面。"""
import copy
import gc
import logging
import os
import time

from novamind.engines.document.integrations.deepdoc.vision.model_manager import (
    default_model_dir,
    download_model_group,
)
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

def pip_install_torch(*args, **kwargs):
    """探测 torch 是否可用（仅尝试 import，不做任何安装）；结果不外传，GPU 可用性在 load_model 内重新探测。"""
    try:
        import torch  # noqa: F401
    except ImportError:
        return None

class _Settings:
    """进程级环境设置：PARALLEL_DEVICES 控制多 GPU 运行时副本数。"""
    PARALLEL_DEVICES = int(os.environ.get("PARALLEL_DEVICES", "0"))

settings = _Settings()
import math

import cv2
import numpy as np
import onnxruntime as ort

from . import operators
from .postprocess import build_post_process

loaded_models = {}


def transform(data, ops=None):
    """transform"""
    if ops is None:
        ops = []
    for op in ops:
        data = op(data)
        if data is None:
            return None
    return data


def create_operators(op_param_list, global_config=None):
    """
    create operators based on the config

    Args:
        params(list): a dict list, used to create some operators
    """
    assert isinstance(op_param_list, list), "operator config should be a list"
    ops = []
    for operator in op_param_list:
        assert isinstance(operator, dict) and len(operator) == 1, "yaml format error"
        op_name = list(operator)[0]
        param = {} if operator[op_name] is None else operator[op_name]
        if global_config is not None:
            param.update(global_config)
        op = getattr(operators, op_name)(**param)
        ops.append(op)
    return ops


def load_model(model_dir, nm, device_id: int | None = None):
    """加载 ``<model_dir>/<nm>.onnx`` 并按路径做模块级缓存（同模型重复加载直接复用）。

    优先 CUDA（需 torch 可用且目标 device_id 存在），否则 CPU；线程数与显存
    由 OCR_INTRA_OP_NUM_THREADS / OCR_INTER_OP_NUM_THREADS /
    OCR_GPU_MEM_LIMIT_MB 等环境变量注入；CPU 恒开内存 arena 收缩。

    Returns:
        (InferenceSession, RunOptions) 二元组。

    Raises:
        ValueError: 模型文件不存在。
    """
    model_file_path = os.path.join(model_dir, nm + ".onnx")
    model_cached_tag = model_file_path + str(device_id) if device_id is not None else model_file_path

    global loaded_models
    loaded_model = loaded_models.get(model_cached_tag)
    if loaded_model:
        logging.info(f"load_model {model_file_path} reuses cached model")
        return loaded_model

    if not os.path.exists(model_file_path):
        raise ValueError(f"not find model file path {model_file_path}")

    def cuda_is_available():
        # CUDA 可用性探测（懒装 torch；失败/无 GPU 均视为不可用）。
        try:
            pip_install_torch()
            import torch

            target_id = 0 if device_id is None else device_id
            if torch.cuda.is_available() and torch.cuda.device_count() > target_id:
                return True
        except Exception:
            return False
        return False

    options = ort.SessionOptions()
    options.enable_cpu_mem_arena = False
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    # Prevent CPU oversubscription by allowing explicit thread control in multi-worker environments
    options.intra_op_num_threads = int(os.environ.get("OCR_INTRA_OP_NUM_THREADS", "2"))
    options.inter_op_num_threads = int(os.environ.get("OCR_INTER_OP_NUM_THREADS", "2"))

    # https://github.com/microsoft/onnxruntime/issues/9509#issuecomment-951546580
    # Shrink GPU memory after execution
    run_options = ort.RunOptions()
    if cuda_is_available():
        gpu_mem_limit_mb = int(os.environ.get("OCR_GPU_MEM_LIMIT_MB", "2048"))
        arena_strategy = os.environ.get("OCR_ARENA_EXTEND_STRATEGY", "kNextPowerOfTwo")
        provider_device_id = 0 if device_id is None else device_id
        cuda_provider_options = {
            "device_id": provider_device_id,  # Use specific GPU
            "gpu_mem_limit": max(gpu_mem_limit_mb, 0) * 1024 * 1024,
            "arena_extend_strategy": arena_strategy,  # gpu memory allocation strategy
        }
        sess = ort.InferenceSession(model_file_path, options=options, providers=["CUDAExecutionProvider"], provider_options=[cuda_provider_options])
        # Explicit arena shrinkage for GPU to release VRAM back to the system after each run
        if os.environ.get("OCR_GPUMEM_ARENA_SHRINKAGE") == "1":
            run_options.add_run_config_entry("memory.enable_memory_arena_shrinkage", f"gpu:{provider_device_id}")
            logging.info(f"load_model {model_file_path} enabled GPU memory arena shrinkage on device {provider_device_id}")
        logging.info(f"load_model {model_file_path} uses GPU (device {provider_device_id}, gpu_mem_limit={cuda_provider_options['gpu_mem_limit']}, arena_strategy={arena_strategy})")
    else:
        sess = ort.InferenceSession(model_file_path, options=options, providers=["CPUExecutionProvider"])
        run_options.add_run_config_entry("memory.enable_memory_arena_shrinkage", "cpu")
        logging.info(f"load_model {model_file_path} uses CPU")
    loaded_model = (sess, run_options)
    loaded_models[model_cached_tag] = loaded_model
    return loaded_model


class TextRecognizer:
    """CTC 文本识别器：文本行裁剪图送 rec.onnx 推理并解码为 (文本, 置信度)。"""
    def __init__(self, model_dir, device_id: int | None = None):
        """加载识别模型与 CTC 解码器（字典使用 model_dir 下 ocr.res）。"""
        self.rec_image_shape = [int(v) for v in "3, 48, 320".split(",")]
        self.rec_batch_num = 16
        postprocess_params = {"name": "CTCLabelDecode", "character_dict_path": os.path.join(model_dir, "ocr.res"), "use_space_char": True}
        self.postprocess_op = build_post_process(postprocess_params)
        self.predictor, self.run_options = load_model(model_dir, "rec", device_id)
        self.input_tensor = self.predictor.get_inputs()[0]

    def resize_norm_img(self, img, max_wh_ratio):
        """文本行裁剪图缩放到模型输入高度并归一化到 [-1, 1]，右侧零填充到批内宽度。

        批内宽度由 max_wh_ratio（批内最大宽高比）决定，矮行统一补齐，保证整批
        共用一个张量形状。
        """
        imgC, imgH, imgW = self.rec_image_shape

        assert imgC == img.shape[2]
        imgW = int(imgH * max_wh_ratio)
        w = self.input_tensor.shape[3:][0]
        if isinstance(w, str):
            pass
        elif w is not None and w > 0:
            imgW = w
        h, w = img.shape[:2]
        ratio = w / float(h)
        if math.ceil(imgH * ratio) > imgW:
            resized_w = imgW
        else:
            resized_w = int(math.ceil(imgH * ratio))

        resized_image = cv2.resize(img, (resized_w, imgH))
        resized_image = resized_image.astype("float32")
        resized_image = resized_image.transpose((2, 0, 1)) / 255
        resized_image -= 0.5
        resized_image /= 0.5
        padding_im = np.zeros((imgC, imgH, imgW), dtype=np.float32)
        padding_im[:, :, 0:resized_w] = resized_image
        return padding_im

    def close(self):
        # close session and release manually
        """丢弃 session 引用并触发 GC。"""
        logging.info("Close text recognizer.")
        if hasattr(self, "predictor"):
            del self.predictor
        gc.collect()

    def __call__(self, img_list):
        """批量文本识别：文本行按宽高比排序分批（减少填充浪费），批量推理后 CTC 解码。

        推理异常间隔重试，重试耗尽后向上抛出最后异常。

        Returns:
            (识别结果列表 [(文本, 置信度)], 总耗时秒)；结果顺序与输入一致。
        """
        img_num = len(img_list)
        # Calculate the aspect ratio of all text bars
        width_list = []
        for img in img_list:
            width_list.append(img.shape[1] / float(img.shape[0]))
        # Sorting can speed up the recognition process
        indices = np.argsort(np.array(width_list))
        rec_res = [["", 0.0]] * img_num
        batch_num = self.rec_batch_num
        st = time.time()

        for beg_img_no in range(0, img_num, batch_num):
            end_img_no = min(img_num, beg_img_no + batch_num)
            norm_img_batch = []
            imgC, imgH, imgW = self.rec_image_shape[:3]
            max_wh_ratio = imgW / imgH
            # max_wh_ratio = 0
            for ino in range(beg_img_no, end_img_no):
                h, w = img_list[indices[ino]].shape[0:2]
                wh_ratio = w * 1.0 / h
                max_wh_ratio = max(max_wh_ratio, wh_ratio)
            for ino in range(beg_img_no, end_img_no):
                norm_img = self.resize_norm_img(img_list[indices[ino]], max_wh_ratio)
                norm_img = norm_img[np.newaxis, :]
                norm_img_batch.append(norm_img)
            norm_img_batch = np.concatenate(norm_img_batch)
            norm_img_batch = norm_img_batch.copy()

            input_dict = {}
            input_dict[self.input_tensor.name] = norm_img_batch
            for i in range(100000):
                try:
                    outputs = self.predictor.run(None, input_dict, self.run_options)
                    break
                except Exception as e:
                    if i >= 3:
                        raise e
                    time.sleep(5)
            preds = outputs[0]
            rec_result = self.postprocess_op(preds)
            for rno in range(len(rec_result)):
                rec_res[indices[beg_img_no + rno]] = rec_result[rno]

        return rec_res, time.time() - st

    def __del__(self):
        """析构时触发 close() 释放资源。"""
        self.close()


class TextDetector:
    """DB 文本检测器：det.onnx 整页推理，输出四边形文本框（4 角点像素坐标）。"""
    def __init__(self, model_dir, device_id: int | None = None):
        """加载检测模型并构建预处理链；模型输入为固定尺寸时以固定形状替换 DetResizeForTest。"""
        pre_process_list = [
            {
                "DetResizeForTest": {
                    "limit_side_len": 960,
                    "limit_type": "max",
                }
            },
            {"NormalizeImage": {"std": [0.229, 0.224, 0.225], "mean": [0.485, 0.456, 0.406], "scale": "1./255.", "order": "hwc"}},
            {"ToCHWImage": None},
            {"KeepKeys": {"keep_keys": ["image", "shape"]}},
        ]
        postprocess_params = {"name": "DBPostProcess", "thresh": 0.3, "box_thresh": 0.5, "max_candidates": 1000, "unclip_ratio": 1.5, "use_dilation": False, "score_mode": "fast", "box_type": "quad"}

        self.postprocess_op = build_post_process(postprocess_params)
        self.predictor, self.run_options = load_model(model_dir, "det", device_id)
        self.input_tensor = self.predictor.get_inputs()[0]

        img_h, img_w = self.input_tensor.shape[2:]
        if isinstance(img_h, str) or isinstance(img_w, str):
            pass
        elif img_h is not None and img_w is not None and img_h > 0 and img_w > 0:
            pre_process_list[0] = {"DetResizeForTest": {"image_shape": [img_h, img_w]}}
        self.preprocess_op = create_operators(pre_process_list)

    def order_points_clockwise(self, pts):
        """四边形角点重排为左上、右上、右下、左下。"""
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        tmp = np.delete(pts, (np.argmin(s), np.argmax(s)), axis=0)
        diff = np.diff(np.array(tmp), axis=1)
        rect[1] = tmp[np.argmin(diff)]
        rect[3] = tmp[np.argmax(diff)]
        return rect

    def clip_det_res(self, points, img_height, img_width):
        """把框角点钳制回原图像边界内。"""
        for pno in range(points.shape[0]):
            points[pno, 0] = int(min(max(points[pno, 0], 0), img_width - 1))
            points[pno, 1] = int(min(max(points[pno, 1], 0), img_height - 1))
        return points

    def filter_tag_det_res(self, dt_boxes, image_shape):
        """检测框清理：角点排序、边界钳制，丢弃宽或高不超过 3 像素的退化框。"""
        img_height, img_width = image_shape[0:2]
        dt_boxes_new = []
        for box in dt_boxes:
            if isinstance(box, list):
                box = np.array(box)
            box = self.order_points_clockwise(box)
            box = self.clip_det_res(box, img_height, img_width)
            rect_width = int(np.linalg.norm(box[0] - box[1]))
            rect_height = int(np.linalg.norm(box[0] - box[3]))
            if rect_width <= 3 or rect_height <= 3:
                continue
            dt_boxes_new.append(box)
        dt_boxes = np.array(dt_boxes_new)
        return dt_boxes

    def close(self):
        """丢弃 session 引用并触发 GC。"""
        logging.info("Close text detector.")
        if hasattr(self, "predictor"):
            del self.predictor
        gc.collect()

    def __call__(self, img):
        """对单张整页图检测文本框。

        Returns:
            (四边形框数组 [N, 4, 2]（原图像素坐标）, 检测耗时秒)；失败时返回 (None, 0)。
        """
        ori_im = img.copy()
        data = {"image": img}

        st = time.time()
        data = transform(data, self.preprocess_op)
        img, shape_list = data
        if img is None:
            return None, 0
        img = np.expand_dims(img, axis=0)
        shape_list = np.expand_dims(shape_list, axis=0)
        img = img.copy()
        input_dict = {}
        input_dict[self.input_tensor.name] = img
        for i in range(100000):
            try:
                outputs = self.predictor.run(None, input_dict, self.run_options)
                break
            except Exception as e:
                if i >= 3:
                    raise e
                time.sleep(5)

        post_result = self.postprocess_op({"maps": outputs[0]}, shape_list)
        dt_boxes = post_result[0]["points"]
        dt_boxes = self.filter_tag_det_res(dt_boxes, ori_im.shape)

        return dt_boxes, time.time() - st

    def __del__(self):
        """析构时触发 close() 释放资源。"""
        self.close()


class OCR:
    """OCR 门面：检测、透视裁剪、识别整合为统一的文字提取入口。

    常用路径：__call__ 全管线（返回框 + 文本 + 置信度）、detect 仅检测、
    recognize / recognize_batch 对已知框识别；行裁剪由 get_rotate_crop_image
    透视变换完成。模型懒加载：autoload=False 实例化后按需 load()，本地模型
    缺失时运行期兜底下载。
    """
    def __init__(self, model_dir=None, *, autoload: bool = True, parallel_devices: int | None = None):
        """
        If you have trouble downloading HuggingFace models, -_^ this might help!!

        For Linux:
        export HF_ENDPOINT=https://hf-mirror.com

        For Windows:
        Good luck
        ^_-

        """
        self.model_dir = str(model_dir or default_model_dir())
        self.parallel_devices = settings.PARALLEL_DEVICES if parallel_devices is None else max(int(parallel_devices), 0)
        self.text_detector = []
        self.text_recognizer = []
        self.drop_score = 0.5
        self.loaded = False

        if autoload:
            self.load()

    def _build_runtimes(self, model_dir: str):
        """按 parallel_devices 数创建检测/识别运行时（每个 GPU 设备一套）。"""
        if self.parallel_devices > 0:
            self.text_detector = []
            self.text_recognizer = []
            for device_id in range(self.parallel_devices):
                self.text_detector.append(TextDetector(model_dir, device_id))
                self.text_recognizer.append(TextRecognizer(model_dir, device_id))
        else:
            self.text_detector = [TextDetector(model_dir)]
            self.text_recognizer = [TextRecognizer(model_dir)]

    def load(self):
        """加载 OCR 模型；本地文件缺失时先经 download_model_group("ocr") 运行期兜底
        下载再重建运行时。

        Returns:
            self，支持链式调用。
        """
        if self.loaded and self.text_detector and self.text_recognizer:
            return self

        model_dir = self.model_dir
        try:
            self._build_runtimes(model_dir)
        except Exception as exc:
            # 运行期兜底下载：统一走 model_manager.download_model_group("ocr")
            # （镜像直链 + 每文件 3 次重试 + .part 原子替换）。此前这里直接调
            # huggingface_hub.snapshot_download——镜像 endpoint 下元数据校验必败、
            # 官方源直连常不可达，且 Linux bind-mount 下容器内无写权限，三级皆废，
            # 等于没有兜底。下载仍失败则异常向上抛，由调用方软降级。
            logger.warning(
                "DeepDoc OCR 模型本地加载失败，尝试运行期下载（download_model_group）",
                model_dir=str(model_dir),
                error=str(exc),
            )
            download_model_group("ocr")
            self.model_dir = str(default_model_dir())
            self._build_runtimes(self.model_dir)

        self.loaded = True
        return self

    def ensure_loaded(self):
        """确保模型已加载，未加载时按需触发一次。"""
        if not self.loaded or not self.text_detector or not self.text_recognizer:
            self.load()
        return self

    def get_rotate_crop_image(self, img, points, device_id: int | None = None):
        """
        img_height, img_width = img.shape[0:2]
        left = int(np.min(points[:, 0]))
        right = int(np.max(points[:, 0]))
        top = int(np.min(points[:, 1]))
        bottom = int(np.max(points[:, 1]))
        img_crop = img[top:bottom, left:right, :].copy()
        points[:, 0] = points[:, 0] - left
        points[:, 1] = points[:, 1] - top
        """
        if device_id is None:
            device_id = 0
        recognizer = self.text_recognizer[device_id] if self.text_recognizer and device_id < len(self.text_recognizer) else None
        assert len(points) == 4, "shape of points must be 4*2"
        img_crop_width = int(max(np.linalg.norm(points[0] - points[1]), np.linalg.norm(points[2] - points[3])))
        img_crop_height = int(max(np.linalg.norm(points[0] - points[3]), np.linalg.norm(points[1] - points[2])))
        pts_std = np.float32([[0, 0], [img_crop_width, 0], [img_crop_width, img_crop_height], [0, img_crop_height]])
        M = cv2.getPerspectiveTransform(points, pts_std)
        dst_img = cv2.warpPerspective(img, M, (img_crop_width, img_crop_height), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC)
        dst_img_height, dst_img_width = dst_img.shape[0:2]
        if dst_img_height * 1.0 / dst_img_width >= 1.5 and recognizer is not None:
            # Try original orientation
            rec_result = recognizer([dst_img])
            text, score = rec_result[0][0]
            best_score = score
            best_img = dst_img

            # Try clockwise 90° rotation
            rotated_cw = np.rot90(dst_img, k=3)
            rec_result = recognizer([rotated_cw])
            rotated_cw_text, rotated_cw_score = rec_result[0][0]
            if rotated_cw_score > best_score:
                best_score = rotated_cw_score
                best_img = rotated_cw

            # Try counter-clockwise 90° rotation
            rotated_ccw = np.rot90(dst_img, k=1)
            rec_result = recognizer([rotated_ccw])
            rotated_ccw_text, rotated_ccw_score = rec_result[0][0]
            if rotated_ccw_score > best_score:
                best_img = rotated_ccw

            # Use the best image
            dst_img = best_img
        return dst_img

    def sorted_boxes(self, dt_boxes):
        """
        Sort text boxes in order from top to bottom, left to right
        args:
            dt_boxes(array):detected text boxes with shape [4, 2]
        return:
            sorted boxes(array) with shape [4, 2]
        """
        num_boxes = dt_boxes.shape[0]
        sorted_boxes = sorted(dt_boxes, key=lambda x: (x[0][1], x[0][0]))
        _boxes = list(sorted_boxes)

        for i in range(num_boxes - 1):
            for j in range(i, -1, -1):
                if abs(_boxes[j + 1][0][1] - _boxes[j][0][1]) < 10 and (_boxes[j + 1][0][0] < _boxes[j][0][0]):
                    tmp = _boxes[j]
                    _boxes[j] = _boxes[j + 1]
                    _boxes[j + 1] = tmp
                else:
                    break
        return _boxes

    def detect(self, img, device_id: int | None = None):
        """仅文本检测（不识别）。

        Returns:
            (排序后四边形框, 空文本占位) 对的迭代器；图像无效或未检出时为 None。
        """
        self.ensure_loaded()
        if device_id is None:
            device_id = 0

        if img is None:
            return None

        dt_boxes, _ = self.text_detector[device_id](img)

        if dt_boxes is None:
            return None

        return zip(self.sorted_boxes(dt_boxes), [("", 0) for _ in range(len(dt_boxes))])

    def recognize(self, ori_im, box, device_id: int | None = None):
        """识别单个框内文本，置信度低于 drop_score 时返回空串。"""
        self.ensure_loaded()
        if device_id is None:
            device_id = 0

        img_crop = self.get_rotate_crop_image(ori_im, box)

        rec_res, elapse = self.text_recognizer[device_id]([img_crop])
        text, score = rec_res[0]
        if score < self.drop_score:
            return ""
        return text

    def recognize_batch(self, img_list, device_id: int | None = None):
        """批量识别文本行裁剪图，结果按输入顺序返回，置信度低于阈值者为空串。"""
        self.ensure_loaded()
        if device_id is None:
            device_id = 0
        rec_res, elapse = self.text_recognizer[device_id](img_list)
        texts = []
        for i in range(len(rec_res)):
            text, score = rec_res[i]
            if score < self.drop_score:
                text = ""
            texts.append(text)
        return texts

    def __call__(self, img, device_id=0, cls=True):
        """全管线：检测框 → 排序 → 逐框透视裁剪文本行 → 批量识别 → 过滤低置信度结果。

        Returns:
            [(框角点 [[x, y]×4], (文本, 置信度))] 列表；各阶段耗时记录在 time_dict
            （det/rec/all 键）；未检出框时返回 (None, None, time_dict)。
        """
        self.ensure_loaded()
        time_dict = {"det": 0, "rec": 0, "cls": 0, "all": 0}
        if device_id is None:
            device_id = 0

        if img is None:
            return None, None, time_dict

        start = time.time()
        ori_im = img.copy()
        dt_boxes, elapse = self.text_detector[device_id](img)
        time_dict["det"] = elapse

        if dt_boxes is None:
            end = time.time()
            time_dict["all"] = end - start
            return None, None, time_dict

        img_crop_list = []

        dt_boxes = self.sorted_boxes(dt_boxes)

        for bno in range(len(dt_boxes)):
            tmp_box = copy.deepcopy(dt_boxes[bno])
            img_crop = self.get_rotate_crop_image(ori_im, tmp_box)
            img_crop_list.append(img_crop)

        rec_res, elapse = self.text_recognizer[device_id](img_crop_list)

        time_dict["rec"] = elapse

        filter_boxes, filter_rec_res = [], []
        for box, rec_result in zip(dt_boxes, rec_res):
            text, score = rec_result
            if score >= self.drop_score:
                filter_boxes.append(box)
                filter_rec_res.append(rec_result)
        end = time.time()
        time_dict["all"] = end - start

        # for bno in range(len(img_crop_list)):
        #    print(f"{bno}, {rec_res[bno]}")

        return list(zip([a.tolist() for a in filter_boxes], filter_rec_res))
