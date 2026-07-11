from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image

from src.shared.integrations.deepdoc.compat import LazyImage
from src.shared.integrations.deepdoc.parsers.upstream.figure_parser import VisionFigureParser
from src.shared.integrations.deepdoc.vision.ocr import OCR
from src.shared.integrations.deepdoc.vision.model_manager import get_model_status


class RAGFlowFigureParser(VisionFigureParser):
    """Adapted image parser inspired by RAGFlow's figure parser path."""

    SUPPORTED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}

    def __init__(self, vision_model=None, figures_data=None, *args, **kwargs):
        self.standalone_vision_model = vision_model
        if figures_data is not None:
            super().__init__(
                vision_model=vision_model,
                figures_data=figures_data,
                *args,
                **kwargs,
            )

    def parse(self, file_path: str | Path) -> tuple[str, list[str], dict[str, Any]]:
        path = Path(file_path)
        return self.parse_bytes(path.read_bytes(), path.suffix.lower().lstrip("."))

    def parse_bytes(self, file_bytes: bytes, file_type: str) -> tuple[str, list[str], dict[str, Any]]:
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
        try:
            ocr = OCR(autoload=True)
        except Exception:
            return [], []

        detections = list(ocr.detect(image) or [])
        if not detections:
            return [], []

        lines: list[str] = []
        boxes: list[dict[str, Any]] = []
        for quad, _ in detections:
            text = ocr.recognize(image, quad)
            points = quad.tolist() if hasattr(quad, "tolist") else quad
            cleaned_points = [[float(p[0]), float(p[1])] for p in points]
            boxes.append({"quad": cleaned_points, "text": text})
            if text:
                lines.append(text)
        return lines, boxes
