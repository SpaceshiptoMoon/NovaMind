"""DeepDoc 模型下载链路回归测试（2026-09-18 收口）。

历史缺陷：OCR.load() 的运行期兜底直接调 huggingface_hub.snapshot_download——
镜像 endpoint 下元数据校验必败、官方源直连常不可达、Linux bind-mount 容器内
无写权限，三级皆废。收口后全部下载统一收敛到 model_manager.download_hf_files
（镜像直链 + 重试 + 原子替换），本文件锁死该契约。
"""
import pytest

from novamind.engines.document.integrations.deepdoc.vision import model_manager
from novamind.engines.document.integrations.deepdoc.vision.ocr import OCR


@pytest.mark.unit
def test_download_hf_files_mirror_endpoint_uses_direct_download(monkeypatch, tmp_path):
    """镜像 endpoint（默认）下应走直链下载且不 import huggingface_hub。"""
    calls = []

    def fake_direct(base_dir, repo_id, files):
        calls.append((base_dir, repo_id, list(files)))
        for name in files:
            (base_dir / name).write_bytes(b"x")
        return base_dir

    monkeypatch.setattr(model_manager, "hf_model_endpoint", lambda: "https://hf-mirror.com")
    monkeypatch.setattr(model_manager, "direct_download_files", fake_direct)

    files = ["a.onnx", "b.res"]
    out = model_manager.download_hf_files(tmp_path, "some/repo", files)

    assert out == tmp_path
    assert len(calls) == 1
    assert calls[0][1] == "some/repo"
    assert calls[0][2] == files


@pytest.mark.unit
def test_download_hf_files_official_endpoint_falls_back_to_direct(monkeypatch, tmp_path):
    """官方 endpoint 下 snapshot_download 失败应回退直链。"""
    calls = []

    def fake_snapshot(**kwargs):
        raise RuntimeError("network down")

    def fake_direct(base_dir, repo_id, files):
        calls.append(repo_id)
        return base_dir

    monkeypatch.setattr(model_manager, "hf_model_endpoint", lambda: "https://huggingface.co")
    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_snapshot)
    monkeypatch.setattr(model_manager, "direct_download_files", fake_direct)

    model_manager.download_hf_files(tmp_path, "some/repo", ["a.onnx"])

    assert calls == ["some/repo"]


@pytest.mark.unit
def test_ocr_load_fallback_uses_download_model_group(monkeypatch, tmp_path):
    """OCR.load() 本地加载失败时的兜底必须走 download_model_group（不再是
    snapshot_download），且失败异常向上传播（不静默吞掉）。"""
    downloads = []

    def fake_download(group, model_dir=None):
        downloads.append(group)
        # 模拟下载后模型仍不可用 → _build_runtimes 二次抛错
        raise FileNotFoundError("download failed: network unreachable")

    monkeypatch.setattr(
        "novamind.engines.document.integrations.deepdoc.vision.ocr.download_model_group",
        fake_download,
    )

    ocr = OCR(autoload=False, model_dir=str(tmp_path / "empty"))
    with pytest.raises(Exception):
        ocr.load()

    assert downloads == ["ocr"], "兜底下载必须指向 ocr 组"


@pytest.mark.unit
def test_formula_and_text_concat_share_download_hf_files(monkeypatch, tmp_path):
    """公式与 text_concat 下载必须复用 model_manager.download_hf_files（单一事实源）。"""
    calls = []

    def fake_download_hf_files(base_dir, repo_id, files):
        calls.append((str(base_dir), repo_id, list(files)))
        return base_dir

    monkeypatch.setattr(
        "novamind.engines.document.integrations.deepdoc.formula_recognition.download_hf_files",
        fake_download_hf_files,
    )
    monkeypatch.setattr(
        "novamind.engines.document.integrations.deepdoc.text_concat_model.download_hf_files",
        fake_download_hf_files,
    )

    from novamind.engines.document.integrations.deepdoc.formula_recognition import (
        FORMULA_MODEL_FILES,
        FORMULA_MODEL_REPO_ID,
        download_formula_model,
    )
    from novamind.engines.document.integrations.deepdoc.text_concat_model import (
        TEXT_CONCAT_MODEL_FILENAME,
        TEXT_CONCAT_MODEL_REPO_ID,
        download_text_concat_model,
    )

    download_formula_model(tmp_path / "formula")
    download_text_concat_model(tmp_path / "tc")

    assert calls[0][1] == FORMULA_MODEL_REPO_ID
    assert calls[0][2] == list(FORMULA_MODEL_FILES)
    assert calls[1][1] == TEXT_CONCAT_MODEL_REPO_ID
    assert calls[1][2] == [TEXT_CONCAT_MODEL_FILENAME]
