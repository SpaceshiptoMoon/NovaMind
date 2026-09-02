"""DeepDoc 通用识别器（Recognizer）鲁棒性回归测试。

本文件故意不依赖 pandas，避免 `test_deepdoc_runtime.py` 因 docx_parser 的 pandas
依赖导致整模块被跳过。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.integrations.deepdoc.vision_runtime import (
    get_vision_runtime_status,
)


def _skip_if_vision_runtime_unavailable():
    status = get_vision_runtime_status()
    if not status["available"]:
        pytest.skip(f"DeepDoc vision runtime unavailable: missing {', '.join(status['missing_required'])}")


def test_recognizer_call_handles_empty_model_output(monkeypatch):
    """Recognizer.__call__ 在 _run_model_batch 返回空列表时不应 IndexError。"""
    _skip_if_vision_runtime_unavailable()
    from novamind.engines.document.integrations.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

    recognizer = TableStructureRecognizer()
    recognizer.loaded = True
    recognizer.session = object()
    recognizer.ort_sess = object()
    recognizer.input_name = "images"
    recognizer.input_names = ["images"]
    recognizer.input_shape = (640, 640)
    monkeypatch.setattr(recognizer, "_run_model_batch", lambda batch: [])

    predictions = recognizer.forward([np.zeros((80, 160, 3), dtype=np.uint8)], thr=0.2, batch_size=1)

    assert predictions == [[]]

