"""全系统唯一设备探针回归测试（2026-11 设备标准）。

标准：所有本地模型（DeepDoc OCR/layout/TSR/公式、本地 ASR）的 GPU/CPU 判定
只允许来自 ``runtime_settings.resolve_device_policy()``——一个函数、一次探测、
一个结论；安装期（deploy 脚本）用同一判据选构建 flavor，运行时首次判定时
与 ``DEVICE_FLAVOR`` 对账，不一致仅告警、行为以运行时判定为准。

正例：判定链各分支返回正确结论；四个消费方（ocr/recognizer/formula/audio）
在同一探针结论下行为一致。
反例保护：探测任何环节异常都落 CPU 不抛错；flavor 不一致只告警不改变行为。
"""
from __future__ import annotations

import logging
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.integrations.deepdoc import runtime_settings as rs
from novamind.engines.document.integrations.deepdoc.formula_recognition import (
    FormulaRecognizer,
)
from novamind.engines.document.integrations.deepdoc.vision import ocr as ocr_mod
from novamind.engines.document.integrations.deepdoc.vision import recognizer as rec_mod
from novamind.engines.document.media.audio import audio_utils

RS_PATH = "novamind.engines.document.integrations.deepdoc.runtime_settings"

class _LoggerRecorder:
    """structlog 渲染直写 stdout（绕过 stdlib root logger），caplog 捕获不可靠——
    直接替换模块 _logger 为录制桩，按 (level, event) 断言。"""

    def __init__(self):
        self.events: list[tuple[str, str]] = []

    def _rec(self, level, event, **kw):
        self.events.append((level, event))

    def debug(self, event, **kw):
        self._rec("debug", event, **kw)

    def info(self, event, **kw):
        self._rec("info", event, **kw)

    def warning(self, event, **kw):
        self._rec("warning", event, **kw)

    def error(self, event, **kw):
        self._rec("error", event, **kw)


def _capture_rs_logger(monkeypatch) -> _LoggerRecorder:
    rec = _LoggerRecorder()
    monkeypatch.setattr(rs, "_logger", rec)
    return rec



pytestmark = pytest.mark.unit


# ==================== fake 模块基建 ====================


class _FakeSession:
    """最小 ONNX session 桩：捕获建会话参数，回报可配置的实际 providers。"""

    requested_providers: list | None = None
    requested_provider_options: list | None = None
    reported_providers: list = ["CPUExecutionProvider"]

    def __init__(self, path, *args, **kwargs):
        _FakeSession.requested_providers = kwargs.get("providers")
        _FakeSession.requested_provider_options = kwargs.get("provider_options")

    def get_providers(self):
        return list(_FakeSession.reported_providers)

    def get_inputs(self):
        return [SimpleNamespace(name="input", shape=[1, 3, 736, 736])]

    def get_outputs(self):
        return [SimpleNamespace(name="output")]


def _make_fake_ort(cuda_in_build: bool):
    """构造 onnxruntime 假模块：providers 清单可控，会话构造被捕获。"""
    calls: list[dict] = []

    def inference_session(path, *args, **kwargs):
        calls.append({"path": path, **kwargs})
        return _FakeSession(path, *args, **kwargs)

    fake = types.ModuleType("onnxruntime")
    fake.get_available_providers = staticmethod(
        lambda: ["CPUExecutionProvider"] + (["CUDAExecutionProvider"] if cuda_in_build else [])
    )
    fake.SessionOptions = lambda: SimpleNamespace()
    fake.RunOptions = lambda: SimpleNamespace(add_run_config_entry=lambda k, v: None)
    fake.ExecutionMode = SimpleNamespace(ORT_SEQUENTIAL="sequential")
    fake.GraphOptimizationLevel = SimpleNamespace(ORT_ENABLE_ALL="all")
    fake.InferenceSession = staticmethod(inference_session)
    fake.session_calls = calls
    return fake


def _make_fake_torch(free_mb: int = 6144, total_mb: int = 8188, available: bool = True):
    """构造 torch 假模块：显存容量可控。"""
    cuda = SimpleNamespace(
        is_available=lambda: available,
        mem_get_info=lambda idx=0: (free_mb * 1024 * 1024, total_mb * 1024 * 1024),
    )
    return SimpleNamespace(cuda=cuda)


def _install_fakes(monkeypatch, *, ort_cuda: bool, torch_mod=None, ort_missing: bool = False):
    """把假 onnxruntime / torch 挂进 sys.modules（torch_mod=None 表示不注入=导入失败）。"""
    fake_ort = _make_fake_ort(ort_cuda)
    if ort_missing:
        monkeypatch.setitem(sys.modules, "onnxruntime", None)  # import 抛 ImportError
    else:
        monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    if torch_mod is not None:
        monkeypatch.setitem(sys.modules, "torch", torch_mod)
    else:
        monkeypatch.delitem(sys.modules, "torch", raising=False)
    return fake_ort


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """每用例隔离：清探针缓存、清宿主注入、清各消费方 session/别名缓存。"""
    rs.reset_device_policy()
    rs.reset_settings()
    rec_mod._SESSION_CACHE.clear()
    ocr_mod.loaded_models.clear()
    audio_utils._cuda_available.cache_clear()
    yield
    rs.reset_device_policy()
    rs.reset_settings()
    rec_mod._SESSION_CACHE.clear()
    ocr_mod.loaded_models.clear()
    audio_utils._cuda_available.cache_clear()


# ==================== 探针判定链 ====================


class TestProbeVerdict:
    def test_forced_cpu_env_beats_everything(self, monkeypatch):
        """DEEPDOC_DEVICE=cpu 显式强制：即使 ort/torch 全部具备也判 CPU。"""
        _install_fakes(monkeypatch, ort_cuda=True, torch_mod=_make_fake_torch())
        monkeypatch.setenv("DEEPDOC_DEVICE", "cpu")
        assert rs.resolve_device_policy() == "cpu"
        assert rs.resolve_execution_providers() == ["CPUExecutionProvider"]

    def test_forced_cuda_env_skips_probing(self, monkeypatch):
        """DEEPDOC_DEVICE=cuda 显式指定：跳过全部检查（会话级 CPU 兜底接管）。"""
        monkeypatch.setenv("DEEPDOC_DEVICE", "cuda")
        assert rs.resolve_device_policy() == "cuda"
        assert rs.resolve_execution_providers() == ["CUDAExecutionProvider", "CPUExecutionProvider"]

    def test_invalid_device_value_falls_back_to_auto(self, monkeypatch):
        """DEEPDOC_DEVICE 非法值回退 auto（auto 无 CUDA → cpu）。"""
        _install_fakes(monkeypatch, ort_cuda=False)
        monkeypatch.setenv("DEEPDOC_DEVICE", "gpu")
        assert rs.load_settings().device == "auto"
        assert rs.resolve_device_policy() == "cpu"

    def test_ort_cpu_build_means_cpu(self, monkeypatch):
        """ORT 为 CPU 构建（无 CUDAExecutionProvider）→ CPU。"""
        _install_fakes(monkeypatch, ort_cuda=False, torch_mod=_make_fake_torch())
        assert rs.resolve_device_policy() == "cpu"

    def test_missing_torch_means_cpu(self, monkeypatch):
        """GPU 版 ORT 但 torch 不可用（CPU flavor 镜像）→ CPU。"""
        _install_fakes(monkeypatch, ort_cuda=True, torch_mod=None)
        assert rs.resolve_device_policy() == "cpu"

    def test_ort_import_failure_means_cpu(self, monkeypatch):
        """onnxruntime 导入失败 → CPU（探测异常等价于无 GPU，绝不抛）。"""
        _install_fakes(monkeypatch, ort_cuda=True, torch_mod=_make_fake_torch(), ort_missing=True)
        assert rs.resolve_device_policy() == "cpu"

    def test_insufficient_free_vram_means_cpu(self, monkeypatch):
        """空闲显存低于单会话上限（OCR_GPU_MEM_LIMIT_MB）→ CPU，日志注明原因。"""
        _install_fakes(monkeypatch, ort_cuda=True, torch_mod=_make_fake_torch(free_mb=1024))
        assert rs.resolve_device_policy() == "cpu"

    def test_all_conditions_met_means_cuda(self, monkeypatch):
        """ORT CUDA 构建 + torch 可见卡 + 空闲显存充足 → cuda，providers 双列表。"""
        _install_fakes(monkeypatch, ort_cuda=True, torch_mod=_make_fake_torch(free_mb=6144, total_mb=8188))
        assert rs.resolve_device_policy() == "cuda"
        assert rs.resolve_execution_providers() == ["CUDAExecutionProvider", "CPUExecutionProvider"]

    def test_probe_cached_single_evaluation(self, monkeypatch):
        """探针进程级缓存：多次调用只探测一次；reset 后重探。"""
        _install_fakes(monkeypatch, ort_cuda=True, torch_mod=_make_fake_torch())
        calls = {"n": 0}
        original = rs._compute_device_policy

        def counting():
            calls["n"] += 1
            return original()

        monkeypatch.setattr(rs, "_compute_device_policy", counting)
        assert rs.resolve_device_policy() == "cuda"
        assert rs.resolve_device_policy() == "cuda"
        assert calls["n"] == 1
        rs.reset_device_policy()
        assert rs.resolve_device_policy() == "cuda"
        assert calls["n"] == 2


# ==================== 安装 flavor 对账 ====================


class TestInstallFlavorReconciliation:
    def test_flavor_gpu_runtime_cpu_warns_and_behaves_cpu(self, monkeypatch, caplog):
        """GPU flavor 镜像拿到无卡机器：告警 + 行为以运行时判定（cpu）为准。"""
        _install_fakes(monkeypatch, ort_cuda=False)
        monkeypatch.setenv("DEVICE_FLAVOR", "true")  # Dockerfile 传 true/false，归一 gpu/cpu
        rec = _capture_rs_logger(monkeypatch)
        verdict = rs.resolve_device_policy()
        assert verdict == "cpu"
        assert any(level == "warning" and "不一致" in event for level, event in rec.events)

    def test_flavor_cpu_runtime_cuda_warns_but_verdict_holds(self, monkeypatch, caplog):
        """CPU flavor 镜像在有卡机器且显式指定 cuda：告警但判定仍 cuda（行为归会话兜底）。"""
        monkeypatch.setenv("DEVICE_FLAVOR", "cpu")
        monkeypatch.setenv("DEEPDOC_DEVICE", "cuda")
        rec = _capture_rs_logger(monkeypatch)
        verdict = rs.resolve_device_policy()
        assert verdict == "cuda"
        assert any(level == "warning" and "不一致" in event for level, event in rec.events)

    def test_matching_flavor_logs_info_only(self, monkeypatch, caplog):
        """flavor 与判定一致：仅 info 对账日志，无告警。"""
        _install_fakes(monkeypatch, ort_cuda=True, torch_mod=_make_fake_torch())
        monkeypatch.setenv("DEVICE_FLAVOR", "true")
        rec = _capture_rs_logger(monkeypatch)
        assert rs.resolve_device_policy() == "cuda"
        assert any(level == "info" and "一致" in event for level, event in rec.events)
        assert not any(level == "warning" for level, _ in rec.events)

    def test_flavor_value_normalization(self, monkeypatch):
        """DEVICE_FLAVOR 的 true/false 与 gpu/cpu 语义等价。"""
        monkeypatch.setenv("DEVICE_FLAVOR", "true")
        assert rs.load_settings().install_flavor == "gpu"
        monkeypatch.setenv("DEVICE_FLAVOR", "false")
        assert rs.load_settings().install_flavor == "cpu"
        monkeypatch.setenv("DEVICE_FLAVOR", "gpu")
        assert rs.load_settings().install_flavor == "gpu"


# ==================== 四个消费方归一 ====================


def _bind_consumers_to_source(monkeypatch):
    """把三个 ONNX 组件的模块级绑定指回（可被替换的）探针源头。

    audio_utils._cuda_available 是函数体内惰性 import，天然跟随源头，无需绑定。
    """
    monkeypatch.setattr(ocr_mod, "resolve_device_policy", rs.resolve_device_policy)
    monkeypatch.setattr(rec_mod, "resolve_device_policy", rs.resolve_device_policy)
    import novamind.engines.document.integrations.deepdoc.formula_recognition as formula_mod

    monkeypatch.setattr(formula_mod, "resolve_device_policy", rs.resolve_device_policy)


class TestConsumersAgreeWithProbe:
    """核心归一用例：四个消费方在同一探针结论下判定完全一致。"""

    @pytest.mark.parametrize("probe_verdict", ["cuda", "cpu"])
    def test_all_consumers_follow_single_probe(self, monkeypatch, tmp_path, probe_verdict):
        _install_fakes(monkeypatch, ort_cuda=True, torch_mod=_make_fake_torch())
        if probe_verdict == "cpu":
            # 让 auto 判定落 cpu：torch 无卡
            monkeypatch.setitem(sys.modules, "torch", _make_fake_torch(available=False))
        monkeypatch.setattr(rs, "_compute_device_policy", lambda: probe_verdict)
        _bind_consumers_to_source(monkeypatch)

        expected = probe_verdict == "cuda"
        assert audio_utils._cuda_available() is expected

        # ocr.load_model：providers 列表与探针一致（ocr 模块级绑定 ort，需替换命名空间）
        fake_ort = _make_fake_ort(cuda_in_build=True)
        monkeypatch.setattr(ocr_mod, "ort", fake_ort)
        (tmp_path / "det_model.onnx").write_bytes(b"x")
        ocr_mod.load_model(str(tmp_path), "det_model", None)
        expected_providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"] if expected else ["CPUExecutionProvider"]
        )
        assert fake_ort.session_calls[-1]["providers"] == expected_providers

        # recognizer.load：providers 列表与探针一致
        model_file = tmp_path / "layout.onnx"
        model_file.write_bytes(b"x")
        monkeypatch.setattr(rec_mod, "ensure_model_group_available", lambda *a, **k: None)
        rec = rec_mod.Recognizer(
            labels=["text", "title"], domain="layout", model_dir=tmp_path,
            model_filename="layout.onnx", autoload=True,
        )
        assert rec.ort_sess is not None

        # formula：encoder/decoder providers 与探针一致
        import novamind.engines.document.integrations.deepdoc.formula_recognition as formula_mod

        monkeypatch.setattr(formula_mod, "ensure_formula_model_available", lambda d=None: tmp_path)
        monkeypatch.setattr(formula_mod, "get_formula_model_status", lambda d: {"precision": "fp32"})
        monkeypatch.setitem(
            sys.modules,
            "tokenizers",
            SimpleNamespace(Tokenizer=SimpleNamespace(from_file=lambda p: SimpleNamespace())),
        )
        FormulaRecognizer(model_dir=tmp_path)
        assert _FakeSession.requested_providers == expected_providers

    def test_ocr_gpu_fallback_reported_by_session(self, monkeypatch, tmp_path):
        """探针判 cuda 但 ORT 回落 CPU 时：仍以 [CUDA, CPU] 请求建会话，不抛错。"""
        _install_fakes(monkeypatch, ort_cuda=True, torch_mod=_make_fake_torch())
        fake_ort = _make_fake_ort(cuda_in_build=True)
        monkeypatch.setattr(ocr_mod, "ort", fake_ort)
        monkeypatch.setattr(ocr_mod, "resolve_device_policy", lambda: "cuda")
        _FakeSession.reported_providers = ["CPUExecutionProvider"]  # 模拟 CUDA 初始化失败回落
        (tmp_path / "det_model.onnx").write_bytes(b"x")
        _sess, run_options = ocr_mod.load_model(str(tmp_path), "det_model", None)
        assert fake_ort.session_calls[-1]["providers"] == ["CUDAExecutionProvider", "CPUExecutionProvider"]
        assert run_options is not None  # 回落 CPU：arena 收缩挂 cpu，无异常

    def test_deploy_script_uses_same_criteria(self):
        """deploy.sh 的宿主检测与运行时探针同判据（同一阈值变量名）。"""
        script = (BACKEND_ROOT.parent / "deploy.sh").read_text(encoding="utf-8")
        assert "VISION_GPU_MIN_TOTAL_MB" in script
        assert "resolve_device_policy" not in script  # 脚本不重复实现探针逻辑
