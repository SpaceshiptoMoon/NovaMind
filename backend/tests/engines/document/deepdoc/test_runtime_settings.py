"""DeepDoc 运行时配置注入点测试（发包模式）。

覆盖三件事：
1. ``load_settings`` 纯函数：env 映射注入解析、非法值回退默认；
2. ``set_settings`` 宿主注入：注入后 env 不再参与（透传语义）、reset 恢复；
3. ``get_settings`` 无注入时按进程环境现读（``monkeypatch.setenv`` 即时生效）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.integrations.deepdoc import runtime_settings as rs

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_override():
    """用例间清理宿主注入（避免跨文件泄漏）。"""
    rs.reset_settings()
    yield
    rs.reset_settings()


class TestLoadSettings:
    def test_defaults_without_env(self):
        s = rs.load_settings({})
        assert s.model_repo_id == "InfiniFlow/deepdoc"
        assert s.model_dir == ""
        assert s.hf_endpoint == "https://huggingface.co"
        assert s.ocr_intra_op_threads == 2
        assert s.page_batch_size == 50

    def test_env_injection(self):
        s = rs.load_settings({
            "DEEPDOC_MODEL_DIR": "/models/deepdoc",
            "DEEPDOC_MODEL_REPO_ID": "custom/repo",
            "OCR_INTRA_OP_NUM_THREADS": "4",
            "DEEPDOC_SKIP_MODEL_CHECKSUM": "1",
            "DEEPDOC_FORMULA_QUANTIZE": "0",
            "TABLE_AUTO_ROTATE": "false",
            "HF_ENDPOINT": "https://hf-mirror.com/",
        })
        assert s.model_dir == "/models/deepdoc"
        assert s.model_repo_id == "custom/repo"
        assert s.ocr_intra_op_threads == 4
        assert s.skip_checksum is True
        assert s.formula_quantize is False
        assert s.table_auto_rotate is False
        assert s.hf_endpoint == "https://hf-mirror.com"  # 尾斜杠归一

    def test_invalid_values_fall_back(self):
        """非法数值/空串回退默认（与原散落实现容错一致）。"""
        s = rs.load_settings({
            "OCR_INTRA_OP_NUM_THREADS": "abc",
            "DEEPDOC_HF_ETAG_TIMEOUT": "",
        })
        assert s.ocr_intra_op_threads == 2
        assert s.hf_etag_timeout == 60


class TestHostInjection:
    def test_override_beats_env(self, monkeypatch):
        """宿主注入后 env 不再参与（透传语义）。"""
        from novamind.engines.document.integrations.deepdoc.runtime_settings import (
            DeepDocSettings,
        )

        monkeypatch.setenv("OCR_GPU_MEM_LIMIT_MB", "9999")
        rs.set_settings(DeepDocSettings(ocr_gpu_mem_limit_mb=4096))
        assert rs.get_settings().ocr_gpu_mem_limit_mb == 4096

    def test_reset_restores_env(self, monkeypatch):
        rs.set_settings(rs.DeepDocSettings(page_batch_size=7))
        rs.reset_settings()
        monkeypatch.setenv("PDF_PARSER_PAGE_BATCH_SIZE", "12")
        assert rs.get_settings().page_batch_size == 12

    def test_with_overrides_derives_copy(self):
        rs.set_settings(rs.DeepDocSettings(page_batch_size=7))
        derived = rs.with_overrides(page_batch_size=9)
        assert derived.page_batch_size == 9
        assert rs.get_settings().page_batch_size == 7  # 原配置不变


class TestEnvLiveRead:
    def test_setenv_takes_effect_immediately(self, monkeypatch):
        """无缓存语义：运行期 env 变更即时生效（存量 setenv 测试依赖）。"""
        monkeypatch.setenv("OCR_INTRA_OP_NUM_THREADS", "8")
        assert rs.get_settings().ocr_intra_op_threads == 8
        monkeypatch.setenv("OCR_INTRA_OP_NUM_THREADS", "3")
        assert rs.get_settings().ocr_intra_op_threads == 3
