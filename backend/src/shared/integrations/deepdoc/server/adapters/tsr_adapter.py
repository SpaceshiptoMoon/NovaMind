from __future__ import annotations

import io
import logging
from typing import List

from PIL import Image

logger = logging.getLogger(__name__)

TSR_CLASS_MAP = {
    "table": 0,
    "table column": 1,
    "table row": 2,
    "table column header": 3,
    "table projected row header": 4,
    "table spanning cell": 5,
}


class TSRAdapter:
    """Wrap TableStructureRecognizer and convert output to an upstream-like wire format."""

    def __init__(self, model_dir: str | None = None, thr: float = 0.2):
        self.model_dir = model_dir
        self.thr = thr
        self._tsr: TableStructureRecognizer | None = None

    def load(self):
        from src.shared.integrations.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

        self._tsr = TableStructureRecognizer(autoload=True)

    def close(self):
        self._tsr = None

    def __call__(self, image_data: bytes) -> List[List[float]]:
        if self._tsr is None:
            raise RuntimeError("TSRAdapter.load() must be called before inference")

        img = Image.open(io.BytesIO(image_data)).convert("RGB")
        width, height = img.size
        tables = self._tsr([img], thr=self.thr)

        result: List[List[float]] = []
        for table in tables:
            for elem in table:
                label = elem["label"]
                class_id = TSR_CLASS_MAP.get(label)
                if class_id is None:
                    logger.warning("TSR: unknown label '%s', skipping", label)
                    continue
                result.append(
                    [
                        max(0.0, min(float(elem["x0"]), width)),
                        max(0.0, min(float(elem["top"]), height)),
                        max(0.0, min(float(elem["x1"]), width)),
                        max(0.0, min(float(elem["bottom"]), height)),
                        float(elem["score"]),
                        float(class_id),
                    ]
                )
        return result
