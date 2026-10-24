"""OCR 模型并发首载双检锁回归测试。

历史缺陷：``load_model`` 的模块级缓存 ``loaded_models`` 无并发保护——OCR
推理跑在 to_thread 线程池，多任务并发触发同一模型首载时两个线程各建一份
ONNX session（重复占显存/内存，GPU 场景直接双倍配额）。修复后构造段经
双检锁串行化。

正例：并发首载只构造一次 session，全部调用方拿到同一实例。
反例保护：缓存命中路径不进锁（无谓串行化）。
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.integrations.deepdoc.vision import ocr as ocr_mod

pytestmark = pytest.mark.unit


class _FakeSession:
    """最小 ONNX session 桩（仅作实例身份标识）。"""


@pytest.fixture()
def fake_ort(monkeypatch):
    """mock InferenceSession 构造计数与模型文件存在性，清空模块缓存。"""
    build_count = {"n": 0}

    def fake_inference_session(model_file_path, options=None, providers=None, provider_options=None):
        build_count["n"] += 1
        time.sleep(0.05)  # 放大首载竞态窗口
        return _FakeSession()

    monkeypatch.setattr(ocr_mod.ort, "InferenceSession", fake_inference_session)
    monkeypatch.setattr(ocr_mod.os.path, "exists", lambda p: True)
    monkeypatch.setattr(ocr_mod, "loaded_models", {})
    return build_count


class TestConcurrentFirstLoad:
    def test_session_built_once_under_concurrency(self, fake_ort, tmp_path):
        """8 线程并发首载同一模型：session 只构造一次，全部拿到同一实例。"""
        results: list = []
        errors: list = []

        def load():
            try:
                results.append(ocr_mod.load_model(str(tmp_path), "det_model", None))
            except Exception as exc:  # pragma: no cover — 失败要显式暴露
                errors.append(exc)

        threads = [threading.Thread(target=load) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发加载出现异常: {errors}"
        assert fake_ort["n"] == 1, f"session 被重复构造 {fake_ort['n']} 次（双检锁失效）"
        assert len({id(sess) for sess, _run in results}) == 1

    def test_different_devices_build_separately(self, fake_ort, tmp_path):
        """不同 device_id 是不同缓存键，各自构造（双检不误伤多 GPU 副本）。"""
        ocr_mod.load_model(str(tmp_path), "det_model", 0)
        ocr_mod.load_model(str(tmp_path), "det_model", 1)
        assert fake_ort["n"] == 2

    def test_cache_hit_does_not_rebuild(self, fake_ort, tmp_path):
        ocr_mod.load_model(str(tmp_path), "det_model", None)
        ocr_mod.load_model(str(tmp_path), "det_model", None)
        assert fake_ort["n"] == 1
