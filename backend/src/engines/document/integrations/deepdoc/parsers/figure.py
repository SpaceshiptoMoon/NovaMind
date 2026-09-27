"""DeepDoc 图表解析器：提取文档中嵌入的图片 / 图表并生成描述。"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
from novamind.engines.document.integrations.deepdoc.compat import LazyImage
from novamind.engines.document.integrations.deepdoc.parsers.upstream.figure_parser import (
    VisionFigureParser,
)
from novamind.engines.document.integrations.deepdoc.vision.model_manager import get_model_status
from novamind.engines.document.integrations.deepdoc.vision.ocr import OCR
from PIL import Image


class RAGFlowFigureParser(VisionFigureParser):
    """Adapted image parser inspired by RAGFlow's figure parser path."""

    SUPPORTED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}

    def __init__(self, vision_model=None, figures_data=None, *args, **kwargs):
        """初始化图片解析器。
        
        Args:
            vision_model: 独立视觉模型名（当前实现留作注入位，未参与 OCR 兜底路径）。
            figures_data: 传入时走上游 VisionFigureParser 初始化（PDF 内嵌图表场景）。
        """
        self.standalone_vision_model = vision_model
        if figures_data is not None:
            super().__init__(
                vision_model=vision_model,
                figures_data=figures_data,
                *args,
                **kwargs,
            )

    def parse(self, file_path: str | Path) -> tuple[str, list[str], dict[str, Any]]:
        """解析本地图片文件为（全文、分块、元数据）三元组。"""
        path = Path(file_path)
        return self.parse_bytes(path.read_bytes(), path.suffix.lower().lstrip("."))

    def parse_bytes(self, file_bytes: bytes, file_type: str) -> tuple[str, list[str], dict[str, Any]]:
        """解析图片字节流为（全文、分块、元数据）三元组。
        
        全文为尺寸摘要 + OCR 文本行；元数据含图片宽高/格式、OCR 行与四边形框、
        OCR 模型状态，preview 为懒加载原图。
        """
        suffix = file_type.lower().lstrip(".")
        if suffix not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported image format for deepdoc figure parser: {suffix}")

        with Image.open(io.BytesIO(file_bytes)) as img:
            image = img.convert("RGB")
            width, height = image.size
            image_format = (img.format or suffix).upper()

        ocr_lines, ocr_boxes = self._extract_text_with_ocr(image)
        summary = f"Image file ({image_format}) {width}x{height}"
        chunks = [summary]
        full_text = summary
        if ocr_lines:
            full_text = summary + "\n\n" + "\n".join(ocr_lines)
            chunks.extend(ocr_lines)

        metadata: dict[str, Any] = {
            "parser": "deepdoc",
            "parser_class": "RAGFlowFigureParser",
            "file_type": suffix,
            "source": "ragflow-adapted",
            "image": {
                "width": width,
                "height": height,
                "format": image_format,
                "preview": LazyImage([file_bytes]),
            },
            "ocr_lines": ocr_lines,
            "ocr_boxes": ocr_boxes,
            "ocr_used": bool(ocr_lines),
            "ocr_model_status": get_model_status().get("groups", {}).get("ocr", {}),
        }
        return full_text.strip(), chunks, metadata

    def _extract_text_with_ocr(self, image: Image.Image) -> tuple[list[str], list[dict[str, Any]]]:
        """OCR 抽取图中文字，返回（文本行，含 quad 坐标的框）二元组。
        
        OCR 不可用或检测失败时静默返回空列表（能力缺失优于报错中断）。
        """
        try:
            ocr = OCR(autoload=True)
        except Exception:
            return [], []

        # OCR.detect/recognize 底层（TextDetector.__call__ 的 ori_im.shape、
        # get_rotate_crop_image 的 cv2.warpPerspective）只接受 numpy ndarray，
        # 直接传 PIL.Image 会 AttributeError。pdf.py 同样用 np.asarray(img) 喂两路。
        img_np = np.asarray(image)

        try:
            detections = list(ocr.detect(img_np) or [])
        except Exception:
            return [], []
        if not detections:
            return [], []

        lines: list[str] = []
        boxes: list[dict[str, Any]] = []
        for quad, _ in detections:
            try:
                text = ocr.recognize(img_np, quad)
            except Exception:
                text = ""
            points = quad.tolist() if hasattr(quad, "tolist") else quad
            cleaned_points = [[float(p[0]), float(p[1])] for p in points]
            boxes.append({"quad": cleaned_points, "text": text})
            if text:
                lines.append(text)
        return lines, boxes
