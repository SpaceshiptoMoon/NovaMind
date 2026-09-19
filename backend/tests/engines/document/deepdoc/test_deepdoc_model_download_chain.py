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


# ── 配置驱动的降级换源（2026-09-19；地址全部来自部署配置，代码零硬编码）──


@pytest.mark.unit
def test_hf_failure_falls_back_to_configured_mirrors(monkeypatch, tmp_path):
    """HF 镜像直链整体失败 → 按 DEEPDOC_MIRRORS 配置逐源补齐。"""
    ms_calls = []

    def fake_direct(base_dir, repo_id, files):
        raise RuntimeError("hf-mirror unreachable")

    def fake_ms(base_dir, repo_id, files):
        ms_calls.append((repo_id, list(files)))
        for name in files:
            (base_dir / name).write_bytes(b"ms")
        return base_dir

    monkeypatch.setattr(model_manager, "hf_model_endpoint", lambda: "https://hf-mirror.com")
    monkeypatch.setattr(model_manager, "direct_download_files", fake_direct)
    monkeypatch.setattr(model_manager, "download_from_mirrors", fake_ms)

    out = model_manager.download_hf_files(tmp_path, "InfiniFlow/deepdoc", ["det.onnx"])

    assert out == tmp_path
    assert ms_calls == [("InfiniFlow/deepdoc", ["det.onnx"])]
    assert (tmp_path / "det.onnx").read_bytes() == b"ms"


@pytest.mark.unit
def test_mirrors_config_parsing(monkeypatch):
    """get_mirror_sources 契约：合法数组通过；非法 JSON/非数组/缺 url 条目
    一律告警降级为空（配置坏了绝不影响主源）。"""
    monkeypatch.delenv(model_manager.MIRRORS_ENV_VAR, raising=False)
    assert model_manager.get_mirror_sources() == []

    monkeypatch.setenv(model_manager.MIRRORS_ENV_VAR, "not-json{")
    assert model_manager.get_mirror_sources() == []

    monkeypatch.setenv(model_manager.MIRRORS_ENV_VAR, '{"url": "x"}')
    assert model_manager.get_mirror_sources() == []

    monkeypatch.setenv(model_manager.MIRRORS_ENV_VAR, '[{"name": "no-url"}]')
    assert model_manager.get_mirror_sources() == []


@pytest.mark.unit
def test_mirror_url_template_substitution(monkeypatch, tmp_path):
    """url 模板 {repo}/{file} 替换 + repo_map 仓库名映射（ModelScope 场景）。
    未登记 repo_map 的仓库按原 HF id 替换（同 id 镜像站无需配置）。"""
    source = {
        "name": "modelscope",
        "url": "https://modelscope.cn/models/{repo}/resolve/master/{file}",
        "repo_map": {"InfiniFlow/deepdoc": "AI-ModelScope/deepdoc"},
    }
    url = model_manager._mirror_url(source, "InfiniFlow/deepdoc", "det.onnx")
    assert url == "https://modelscope.cn/models/AI-ModelScope/deepdoc/resolve/master/det.onnx"

    url = model_manager._mirror_url(source, "InfiniFlow/text_concat_xgb_v1.0", "m.model")
    assert url == (
        "https://modelscope.cn/models/InfiniFlow/text_concat_xgb_v1.0/resolve/master/m.model"
    )


@pytest.mark.unit
def test_mirrors_fallback_only_fetches_missing_files(monkeypatch, tmp_path):
    """降级源逐源补齐：源 A 拿到 det，源 B 只需补 rec；本地已有文件不重复下载。"""
    seen = {"a": [], "b": []}

    def fake_url_download_factory(seen_list, succeed):
        def download(url, target, attempts=3):
            if not succeed:
                raise RuntimeError("mirror down")
            seen_list.append(target.name)
            target.write_bytes(b"x")
        return download

    sources = [{"name": "a", "url": "https://a.example/{repo}/{file}"},
               {"name": "b", "url": "https://b.example/{repo}/{file}"}]
    monkeypatch.setattr(model_manager, "get_mirror_sources", lambda: sources)
    monkeypatch.setattr(
        model_manager, "_direct_download_from_url",
        fake_url_download_factory(seen["a"], succeed=False),
    )
    # 源 a 全失败 → 源 b 补齐：替换掉 a 的失败实现，重新按源分发
    def per_source_download(url, target, attempts=3):
        if url.startswith("https://a.example"):
            raise RuntimeError("mirror a down")
        seen["b"].append(target.name)
        target.write_bytes(b"x")
    monkeypatch.setattr(model_manager, "_direct_download_from_url", per_source_download)

    (tmp_path / "det.onnx").write_bytes(b"already-here")  # 本地已有 → 不下载
    model_manager.download_from_mirrors(tmp_path, "InfiniFlow/deepdoc", ["det.onnx", "rec.onnx"])

    assert seen["b"] == ["rec.onnx"]


@pytest.mark.unit
def test_mirrors_unconfigured_raises_lookuperror(monkeypatch, tmp_path):
    """未配置 DEEPDOC_MIRRORS 时兜底明确报错（不静默假装成功）。"""
    monkeypatch.delenv(model_manager.MIRRORS_ENV_VAR, raising=False)
    with pytest.raises(LookupError):
        model_manager.download_from_mirrors(tmp_path, "InfiniFlow/deepdoc", ["det.onnx"])


@pytest.mark.unit
def test_mirrors_all_exhausted_raises(monkeypatch, tmp_path):
    """全部降级源跑完仍有缺失 → 抛最后错误（而不是返回缺文件的目录）。"""
    sources = [{"name": "a", "url": "https://a.example/{repo}/{file}"}]
    monkeypatch.setattr(model_manager, "get_mirror_sources", lambda: sources)
    monkeypatch.setattr(
        model_manager, "_direct_download_from_url",
        lambda url, target, attempts=3: (_ for _ in ()).throw(RuntimeError("down")),
    )
    with pytest.raises(RuntimeError):
        model_manager.download_from_mirrors(tmp_path, "InfiniFlow/deepdoc", ["det.onnx"])


@pytest.mark.unit
def test_mirrors_disabled_by_env(monkeypatch, tmp_path):
    """DEEPDOC_DISABLE_MIRRORS=1 时 HF 失败直接抛错（禁用降级的逃生门）。"""
    monkeypatch.setattr(model_manager, "hf_model_endpoint", lambda: "https://hf-mirror.com")
    monkeypatch.setattr(
        model_manager, "direct_download_files",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
    )
    monkeypatch.setenv(model_manager.DISABLE_MIRRORS_ENV_VAR, "1")
    monkeypatch.setenv(
        model_manager.MIRRORS_ENV_VAR,
        '[{"name":"m","url":"https://m.example/{repo}/{file}"}]',
    )

    with pytest.raises(RuntimeError):
        model_manager.download_hf_files(tmp_path, "InfiniFlow/deepdoc", ["det.onnx"])
