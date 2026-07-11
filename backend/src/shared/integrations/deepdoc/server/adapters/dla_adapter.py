from __future__ import annotations

import io
import logging
from typing import List

from PIL import Image

logger = logging.getLogger(__name__)

DLA_CLASS_MAP = {
    "title": 0,
    "text": 1,
    "reference": 2,
    "figure": 3,
    "figure caption": 4,
    "table": 5,
    "table caption": 6,
    "equation": 8,
}


class DLAAdapter:
    """Wrap LayoutRecognizer and convert output to an upstream-like wire format."""

    def __init__(self, model_dir: str | None = None, thr: float = 0.2):
        self.model_dir = model_dir
        self.thr = thr
        self._layouter: LayoutRecognizer | None = None

    def load(self):
        from src.shared.integrations.deepdoc.vision.layout_recognizer import LayoutRecognizer

        self._layouter = LayoutRecognizer("layout", autoload=True)

    def close(self):
        self._layouter = None

    def __call__(self, image_data: bytes) -> List[List[float]]:
        if self._layouter is None:
            raise RuntimeError("DLAAdapter.load() must be called before inference")

        img = Image.open(io.BytesIO(image_data)).convert("RGB")
        width, height = img.size
        raw_bboxes = self._layouter.forward([img], thr=self.thr, batch_size=1)[0]

        result: List[List[float]] = []
        for bbox in raw_bboxes:
            label = str(bbox.get("type", "")).lower()
            class_id = DLA_CLASS_MAP.get(label)
            if class_id is None:
                logger.warning("DLA: unknown label '%s', skipping", label)
                continue
            x0, y0, x1, y1 = bbox["bbox"]
            score = float(bbox["score"])
            result.append(
                [
                    max(0.0, min(float(x0), width)),
                    max(0.0, min(float(y0), height)),
                    max(0.0, min(float(x1), width)),
                    max(0.0, min(float(y1), height)),
                    score,
                    float(class_id),
                ]
            )
        return result
