"""发包模式改造的注入消费与宿主合并回归测试（红队审查修复验证）。

覆盖红队审查暴露的两个结构性盲区：
1. **宿主合并组合场景**（P0-1）：whisper 模型目录的优先级保序——
   ``parsing.dir > parsing.slug > asr.dir > 默认档``；此前 asr 目录被
   合并进 AudioConfig 的第 1 级字段发生反转，「parsing 配档位名 + asr
   配陈旧目录」组合下档位名被静默覆盖。
2. **注入消费端到端**（P1-3）：``set_settings`` 注入后 deepdoc 模块
   真实消费注入值——此前 ``ocr._Settings`` 在 import 期固化
   PARALLEL_DEVICES，注入值被静默忽略且无任何测试覆盖。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.integrations.deepdoc import runtime_settings as rs

pytestmark = pytest.mark.unit


def _fake_parsing(**overrides):
    base = dict(
        local_whisper_model_dir="", local_whisper_model=None,
        local_whisper_cpu_threads=1, local_whisper_device=None,
        local_whisper_compute_type=None, local_whisper_beam_size=None,
        local_whisper_vad_enabled=True, local_whisper_min_speech_dbfs=None,
        local_whisper_empty_result_retry_language=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_config(monkeypatch, parsing, asr_model_dir=""):
    """patch get_config（media_processing 为函数内延迟 import，patch 模块属性即可）。"""
    from novamind.setting import yaml_config as ym

    fake = SimpleNamespace(
        knowledge_base=SimpleNamespace(parsing=parsing),
        asr=SimpleNamespace(
            local_whisper_model_dir=asr_model_dir,
            openai_api_key="", openai_base_url="", dashscope_api_key="",
        ),
    )
    monkeypatch.setattr(ym, "get_config", lambda: fake)


def _build(monkeypatch, parsing, asr_model_dir=""):
    from novamind.features.knowledge_space.services import media_processing as mp

    _patch_config(monkeypatch, parsing, asr_model_dir)
    return mp._build_engine_audio_config()


class TestWhisperDirPriority:
    """whisper 模型目录优先级保序（P0-1 回归）：parsing.dir > parsing.slug > asr.dir。"""

    def test_parsing_dir_wins_over_everything(self, monkeypatch):
        cfg = _build(monkeypatch, _fake_parsing(local_whisper_model_dir="/parsing-dir",
                                                local_whisper_model="small"),
                     asr_model_dir="/asr-dir")
        assert cfg.local_whisper_model_dir == "/parsing-dir"

    def test_slug_beats_asr_dir(self, monkeypatch):
        """组合场景（反转回归哨兵）：parsing 配档位名 + asr 配陈旧目录 →
        档位名语义保留（dir 为 None，引擎按档位推导缓存目录），不被 asr 目录覆盖。"""
        cfg = _build(monkeypatch, _fake_parsing(local_whisper_model="small"),
                     asr_model_dir="/stale-asr-dir")
        assert cfg.local_whisper_model_dir is None
        assert cfg.local_whisper_model == "small"

    def test_asr_dir_fallback_when_parsing_empty(self, monkeypatch):
        """parsing 段全空 → asr 目录兜底（原引擎第 3 级语义）。"""
        cfg = _build(monkeypatch, _fake_parsing(), asr_model_dir="/asr-dir")
        assert cfg.local_whisper_model_dir == "/asr-dir"

    def test_all_empty_falls_to_default_slug(self, monkeypatch):
        """全空 → dir 为 None，引擎按默认档位推导。"""
        cfg = _build(monkeypatch, _fake_parsing(), asr_model_dir="")
        assert cfg.local_whisper_model_dir is None


class TestInjectionConsumption:
    """注入消费端到端：set_settings 后 deepdoc 模块真实消费注入值。"""

    def test_ocr_consumes_injected_parallel_devices(self):
        """P1-3 回归：ocr 构造（不加载模型）消费注入的 parallel_devices——
        原 _Settings 类在 import 期固化，注入被静默忽略。"""
        from novamind.engines.document.integrations.deepdoc.vision.ocr import OCR as PaddleOCR

        rs.set_settings(rs.DeepDocSettings(parallel_devices=5))
        try:
            ocr = PaddleOCR()
            assert ocr.parallel_devices == 5
        finally:
            rs.reset_settings()

    def test_model_manager_consumes_injected_repo_id(self):
        """model_manager 的仓库 ID 经运行时函数消费注入值（兼容常量不再被读）。"""
        from novamind.engines.document.integrations.deepdoc.vision import model_manager

        rs.set_settings(rs.DeepDocSettings(model_repo_id="custom/repo"))
        try:
            assert model_manager._model_repo_id() == "custom/repo"
            # 兼容别名是导入期缺省值，运行时函数才是事实来源
            assert model_manager._model_repo_id() != model_manager.MODEL_REPO_ID
        finally:
            rs.reset_settings()

    def test_no_stray_probe_prints(self):
        """P1-5 回归哨兵：宿主构造函数不得残留调试 print（每次音视频解析都会执行）。"""
        import inspect

        from novamind.features.knowledge_space.services import media_processing as mp

        source = inspect.getsource(mp._build_engine_audio_config)
        assert "print(" not in source, "宿主构造函数残留调试 print"
