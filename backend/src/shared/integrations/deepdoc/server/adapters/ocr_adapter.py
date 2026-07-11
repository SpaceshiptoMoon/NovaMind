from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np

logger = logging.getLogger(__name__)

_CONFIDENCE_FILL = 1.0


class OCRAdapter:
    """Wrap OCR.detect() and OCR.recognize_batch() into upstream-like responses."""

    def __init__(self, model_dir: str | None = None):
        self.model_dir = model_dir
        self._ocr: OCR | None = None

    def load(self):
        from src.shared.integrations.deepdoc.vision.ocr import OCR

        self._ocr = OCR(model_dir=self.model_dir, autoload=True)

    def close(self):
        self._ocr = None

    def detect(self, image_data: bytes) -> Dict[str, Any]:
        if self._ocr is None:
            raise RuntimeError("OCRAdapter.load() must be called before inference")
        img = self._decode_bgr(image_data)
        det_result = self._ocr.detect(img)
        quads = []
        for quad_ndarray, _ in det_result or []:
            quad = quad_ndarray.tolist()
            quads.append([[float(point[0]), float(point[1])] for point in quad])
        return {"output": [[quads]]}

    def recognize(self, image_data: bytes) -> Dict[str, Any]:
        if self._ocr is None:
            raise RuntimeError("OCRAdapter.load() must be called before inference")
        img = self._decode_bgr(image_data)
        texts = self._ocr.recognize_batch([img])
        items = [[text, _CONFIDENCE_FILL] for text in texts]
        return {"output": [[items]]}

    @staticmethod
    def _decode_bgr(data: bytes) -> np.ndarray:
        import cv2

        arr = np.frombuffer(data, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Failed to decode image")
        return img
