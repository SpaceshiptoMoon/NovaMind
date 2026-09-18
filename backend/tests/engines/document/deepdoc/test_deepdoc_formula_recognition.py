"""公式识别（pix2text-mfr）接入回归。

覆盖四层：
1. 模型管理层：status/ensure（缺目录、缺文件）
2. 推理器生成循环：fake ONNX session 走 encoder→decoder 贪心自回归（不依赖真实模型）
3. 流水线接线：equation 区域收集/去重、行内块级分类、OCR 碎片剔除、box 合成、
   artifact 流隔离、模型缺失软降级（回退必须可见）
4. 真模型冒烟（marked slow，模型未下载时 skip）
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from novamind.engines.document.integrations.deepdoc.formula_recognition import (
    FORMULA_EOS_TOKEN_ID,
    FormulaRecognizer,
    ensure_formula_model_available,
    formula_model_endpoint,
    get_formula_model_status,
)
from novamind.engines.document.integrations.deepdoc.vision import model_manager
from novamind.engines.document.integrations.deepdoc.parsers.pdf import (
    DeepDocPdfBox,
    RAGFlowPdfParser,
)

PDF_PARSER_MODULE = "novamind.engines.document.integrations.deepdoc.parsers.pdf"


def _box(page=1, x0=0, x1=100, top=0, bottom=20, text="t", layout_type="", layoutno="", col_id=0):
    return DeepDocPdfBox(
        page=page, x0=float(x0), x1=float(x1), top=float(top), bottom=float(bottom),
        text=text, col_id=col_id, layout_type=layout_type, layoutno=layoutno,
    )


def _region(page=1, x0=40, x1=360, top=100, bottom=140, score=0.9):
    return {
        "page": page, "x0": float(x0), "x1": float(x1),
        "top": float(top), "bottom": float(bottom), "score": score,
    }


# ----------------------------------------------------------------------
# 1. 模型管理层
# ----------------------------------------------------------------------

@pytest.mark.unit
def test_formula_model_endpoint_defaults_to_domestic_mirror(monkeypatch):
    """直链下载源默认国内镜像 hf-mirror.com；HF_ENDPOINT 可覆盖。"""
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    assert formula_model_endpoint() == "https://hf-mirror.com"
    monkeypatch.setenv("HF_ENDPOINT", "https://huggingface.co/")
    assert formula_model_endpoint() == "https://huggingface.co"


@pytest.mark.unit
def test_formula_model_status_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPDOC_FORMULA_MODEL_DIR", str(tmp_path / "pix2text_mfr"))
    status = get_formula_model_status()
    assert status["available"] is False
    assert set(status["missing"]) == {"encoder_model.onnx", "decoder_model.onnx", "tokenizer.json"}
    with pytest.raises(FileNotFoundError):
        ensure_formula_model_available()


@pytest.mark.unit
def test_formula_model_status_available_and_precision(tmp_path, monkeypatch):
    model_dir = tmp_path / "mfr"
    model_dir.mkdir()
    for name in ("encoder_model.onnx", "decoder_model.onnx", "tokenizer.json"):
        (model_dir / name).write_bytes(b"x")
    monkeypatch.setenv("DEEPDOC_FORMULA_MODEL_DIR", str(model_dir))
    status = get_formula_model_status()
    assert status["available"] is True
    assert status["quantized"] is False
    assert status["precision"] == "fp32"
    (model_dir / "encoder_model_int8.onnx").write_bytes(b"x")
    (model_dir / "decoder_model_int8.onnx").write_bytes(b"x")
    assert get_formula_model_status()["precision"] == "int8"


# ----------------------------------------------------------------------
# 2. 推理器生成循环（fake ONNX session，仿 test_deepdoc_runtime 的 mock 模式）
# ----------------------------------------------------------------------

class _FakeEncoder:
    def run(self, _, feeds):
        assert feeds["pixel_values"].shape == (1, 3, 384, 384)
        return [np.zeros((1, 578, 384), dtype=np.float32)]


class _FakeDecoder:
    """先输出 token 5，再输出 EOS 结束——验证贪心循环的启停语义。"""

    def __init__(self):
        self.calls = 0

    def run(self, _, feeds):
        self.calls += 1
        logits = np.zeros((1, feeds["input_ids"].shape[1], 1200), dtype=np.float32)
        next_id = 5 if self.calls == 1 else FORMULA_EOS_TOKEN_ID
        logits[0, -1, next_id] = 42.0
        return [logits]


class _FakeTokenizer:
    def __init__(self):
        self.decoded: list[int] | None = None

    def decode(self, ids, skip_special_tokens=True):
        self.decoded = list(ids)
        return "x _ { 2 }"


@pytest.mark.unit
def test_recognize_generation_loop_with_fake_sessions():
    recognizer = FormulaRecognizer.__new__(FormulaRecognizer)
    recognizer.encoder = _FakeEncoder()
    recognizer.decoder = _FakeDecoder()
    recognizer.tokenizer = _FakeTokenizer()
    recognizer.precision = "int8"
    recognizer.model_dir = "<fake>"
    crop = np.full((60, 200, 3), 255, dtype=np.uint8)
    latex = recognizer.recognize(crop)
    # decoder_start_token 不进解码结果；遇 EOS 停
    assert latex == "x _ { 2 }"
    assert recognizer.tokenizer.decoded == [5]
    assert recognizer.decoder.calls == 2


# ----------------------------------------------------------------------
# 2b. 下载链路（vision 与 formula 共用的镜像直链下载）
# ----------------------------------------------------------------------

@pytest.mark.unit
def test_download_model_group_mirror_uses_direct_download(tmp_path, monkeypatch):
    """默认镜像源必须走直链下载（hub 1.x 元数据校验拒绝镜像，snapshot 必败）。"""
    calls = []
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.setattr(
        model_manager, "direct_download_files",
        lambda base_dir, repo_id, files: calls.append((repo_id, list(files))),
    )
    model_manager.download_model_group("layout", model_dir=tmp_path)
    assert calls == [(model_manager.MODEL_REPO_ID, ["layout.onnx"])]


@pytest.mark.unit
def test_download_model_group_official_snapshot_falls_back_to_direct(tmp_path, monkeypatch):
    """显式官方源先走 snapshot；失败（被墙/瞬时故障）回退直链，不抛错。"""
    monkeypatch.setenv("HF_ENDPOINT", "https://huggingface.co")

    import huggingface_hub

    monkeypatch.setattr(
        huggingface_hub, "snapshot_download",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )
    fallback = []
    monkeypatch.setattr(
        model_manager, "direct_download_files",
        lambda base_dir, repo_id, files: fallback.append(list(files)),
    )
    model_manager.download_model_group(None, model_dir=tmp_path)
    assert fallback and "det.onnx" in fallback[0] and "tsr.onnx" in fallback[0]


@pytest.mark.unit
def test_direct_download_files_skip_existing_and_atomic_write(tmp_path, monkeypatch):
    """已存在的非空文件跳过（幂等）；新文件经 .part 原子落盘。"""
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    (tmp_path / "det.onnx").write_bytes(b"already-here")

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"rec"

    urls = []

    def fake_get(url, stream, timeout):
        urls.append(url)
        return _FakeResp()

    monkeypatch.setattr("requests.get", fake_get)
    model_manager.direct_download_files(tmp_path, "some/repo", ["det.onnx", "rec.onnx"])
    assert urls == ["https://hf-mirror.com/some/repo/resolve/main/rec.onnx"]
    assert (tmp_path / "rec.onnx").read_bytes() == b"rec"
    assert not (tmp_path / "rec.onnx.part").exists()


@pytest.mark.unit
def test_download_text_concat_model_mirror_uses_direct_download(tmp_path, monkeypatch):
    """text-concat 模型镜像源同样必须走直链下载（部署容器内 HF_ENDPOINT 指镜像）。

    下载实现已收敛到 model_manager.download_hf_files（单一事实源），
    故 patch 点在 model_manager。
    """
    from novamind.engines.document.integrations.deepdoc import text_concat_model

    calls = []
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.setattr(
        model_manager, "direct_download_files",
        lambda base_dir, repo_id, files: calls.append((repo_id, list(files))),
    )
    path = text_concat_model.download_text_concat_model(model_dir=tmp_path)
    assert calls == [
        (text_concat_model.TEXT_CONCAT_MODEL_REPO_ID, [text_concat_model.TEXT_CONCAT_MODEL_FILENAME])
    ]
    assert path.name == text_concat_model.TEXT_CONCAT_MODEL_FILENAME


# ----------------------------------------------------------------------
# 3. 流水线接线
# ----------------------------------------------------------------------

@pytest.mark.unit
def test_collect_equation_regions_dedupe_and_threshold():
    block = _region(x0=40, x1=360, top=100, bottom=200)
    line_inside = _region(x0=50, x1=350, top=100, bottom=140)
    low_score = _region(x0=0, x1=100, top=300, bottom=320, score=0.1)
    page_layout = [[
        {**block, "type": "equation"},
        {**line_inside, "type": "equation"},
        {**low_score, "type": "equation"},
        {"type": "Text", "score": 0.9, "x0": 0, "x1": 400, "top": 0, "bottom": 90},
    ]]
    regions = RAGFlowPdfParser._collect_equation_regions(page_layout)
    # 整块保留、嵌套逐行碎框去重、低置信度丢弃、非 equation 忽略
    assert len(regions) == 1
    assert regions[0]["bottom"] == 200.0


@pytest.mark.unit
def test_collect_equation_regions_type_case_insensitive():
    page_layout = [[{**_region(), "type": "Equation"}]]
    assert len(RAGFlowPdfParser._collect_equation_regions(page_layout)) == 1


@pytest.mark.unit
def test_collect_equation_regions_skips_caption_overlaps():
    """表题行常被 layout 误检成 equation（表题满是斜体数学符号）——与 caption
    版面区域 ≥70% 重叠的 equation 区域不得进识别，否则表题变乱 LaTeX。"""
    caption = {**_region(x0=40, x1=360, top=100, bottom=140), "type": "table caption"}
    eq_inside_caption = {**_region(x0=45, x1=355, top=102, bottom=138), "type": "equation"}
    eq_outside = {**_region(x0=40, x1=360, top=200, bottom=260), "type": "equation"}
    regions = RAGFlowPdfParser._collect_equation_regions([[caption, eq_inside_caption, eq_outside]])
    assert len(regions) == 1
    assert regions[0]["top"] == 200.0


@pytest.mark.unit
def test_region_contain_ratio_cross_page_is_zero():
    a, b = _region(page=1), _region(page=2)
    assert RAGFlowPdfParser._region_contain_ratio(a, b) == 0.0


@pytest.mark.unit
def test_recognize_equation_regions_model_missing_soft_degrade(monkeypatch):
    """模型缺失必须 WARNING 可见 + 软降级，不抛错（与 layout/text_concat 回退口径一致）。"""
    monkeypatch.setattr(
        f"{PDF_PARSER_MODULE}.get_formula_model_status",
        lambda: {
            "available": False, "model_dir": "<missing>", "missing": ["encoder_model.onnx"],
        },
    )
    parser = RAGFlowPdfParser()
    page_layout = [[{**_region(), "type": "equation"}]]
    results, meta = parser._recognize_equation_regions("unused", page_layout, enabled=None)
    assert results == []
    assert meta["source"] == "skipped_model_unavailable"
    assert meta["equation_regions"] == 1


@pytest.mark.unit
def test_recognize_equation_regions_disabled_and_no_regions():
    parser = RAGFlowPdfParser()
    results, meta = parser._recognize_equation_regions("unused", [[]], enabled=False)
    assert results == [] and meta["source"] == "disabled"
    results, meta = parser._recognize_equation_regions("unused", [[]], enabled=None)
    assert results == [] and meta["source"] == "none"


class _FakeFormulaRecognizer:
    precision = "int8"

    def __init__(self):
        self.crops: list[np.ndarray] = []

    def recognize(self, crop):
        self.crops.append(np.asarray(crop))
        return "x _ { t } + 1"


@pytest.mark.unit
def test_recognize_equation_regions_with_fake_model(monkeypatch):
    monkeypatch.setattr(
        f"{PDF_PARSER_MODULE}.get_formula_model_status",
        lambda: {"available": True, "model_dir": "<fake>", "missing": []},
    )
    fake = _FakeFormulaRecognizer()
    monkeypatch.setattr(f"{PDF_PARSER_MODULE}.load_formula_recognizer", lambda: fake)

    parser = RAGFlowPdfParser()
    # 宽区域（>30% 页宽）→ 块级 $$..$$；页面渲染为 600x400 白图，zoom=2 → 页宽 300pt
    monkeypatch.setattr(
        parser,
        "_render_pages",
        lambda filename, pages, zoom_map=None: {1: Image.fromarray(np.full((400, 600, 3), 255, dtype=np.uint8))},
    )
    wide = _region(x0=30, x1=270, top=50, bottom=90)
    narrow = _region(x0=30, x1=90, top=150, bottom=180)
    page_layout = [[{**wide, "type": "equation"}, {**narrow, "type": "equation"}]]
    results, meta = parser._recognize_equation_regions(
        "unused", page_layout, zoom_map={1: 2}, enabled=None
    )
    assert meta["source"] == "pix2text_mfr"
    assert meta["precision"] == "int8"
    assert meta["recognized"] == 2 and meta["failed"] == 0
    assert len(fake.crops) == 2
    texts = {r["text"] for r in results}
    assert "$$\nx _ { t } + 1\n$$" in texts  # 宽 → 块级
    assert "$x _ { t } + 1$" in texts  # 窄 → 行内


@pytest.mark.unit
def test_apply_formula_boxes_removes_fragments_and_synthesizes():
    parser = RAGFlowPdfParser()
    fragment_a = _box(x0=50, x1=120, top=110, bottom=130, text="x2", layout_type="figure", layoutno="equation-0", col_id=1)
    fragment_b = _box(x0=150, x1=300, top=110, bottom=130, text="+1", layout_type="figure", layoutno="equation-0", col_id=1)
    outside_text = _box(x0=0, x1=380, top=300, bottom=320, text="正文段落。", layout_type="text")
    table_box = _box(x0=40, x1=360, top=100, bottom=140, text="[TABLE]", layout_type="table", layoutno="table-0")
    # 回归：公式编号行区域与表题高度重叠时，表题框不得被当公式碎片剔除
    caption_box = _box(x0=45, x1=355, top=105, bottom=135, text="表1: 算法性能比较", layout_type="table caption", layoutno="table caption-0")
    region = {**_region(x0=40, x1=360, top=100, bottom=140), "latex": "x _ { 2 } + 1", "inline": False, "text": "$$\nx _ { 2 } + 1\n$$"}
    kept, replaced = parser._apply_formula_boxes(
        [fragment_a, fragment_b, outside_text, table_box, caption_box], [region]
    )
    assert replaced == 2
    texts = {box.text for box in kept}
    assert region["text"] in texts
    assert "正文段落。" in texts  # 区域外正文保留
    assert "[TABLE]" in texts  # 表格框即使几何重叠也不被当公式碎片剔除
    assert "表1: 算法性能比较" in texts  # 表题框不剔（公式编号区域重叠的误伤回归）
    assert "x2" not in texts and "+1" not in texts  # OCR 碎片被 LaTeX box 取代
    synth = [box for box in kept if box.layoutno == "equation-synth-0"]
    assert len(synth) == 1
    assert synth[0].layout_type == "figure"
    assert synth[0].col_id == 1  # 继承碎片框多数列号（双栏阅读顺序）
    assert synth[0].position_tag.startswith("@@1\t")


@pytest.mark.unit
def test_apply_formula_boxes_cross_page_region_does_not_remove_boxes():
    """回归：页坐标是页内局部系，无页码守卫时 p5 的巨型误检 equation 区域
    会以高覆盖率吞掉 p1 摘要框（实测 0.82 ≥ 0.7），p1 只剩 title/caption。"""
    parser = RAGFlowPdfParser()
    abstract = _box(page=1, x0=141, x1=525, top=310, bottom=368, text="摘要：本文研究……", layout_type="text")
    body_p1 = _box(page=1, x0=69, x1=526, top=571, bottom=767, text="引言正文段落。", layout_type="text")
    # p5 误检的巨型 equation 区域，坐标与 p1 摘要/正文在局部坐标系下高度重叠
    region = {
        **_region(page=5, x0=85, x1=491, top=316, bottom=386),
        "latex": "X", "inline": False, "text": "$$\nX\n$$",
    }
    kept, replaced = parser._apply_formula_boxes([abstract, body_p1], [region])
    assert replaced == 0
    texts = {box.text for box in kept}
    assert "摘要：本文研究……" in texts
    assert "引言正文段落。" in texts
    assert region["text"] in texts  # 公式合成 box 仍在
    assert len(kept) == 3


@pytest.mark.unit
def test_collect_artifact_boxes_excludes_equation_prefix():
    eq_fragment = _box(text="x2", layout_type="figure", layoutno="equation-0")
    eq_synth = _box(text="$$x$$", layout_type="figure", layoutno="equation-synth-0")
    real_figure = _box(text="", layout_type="figure", layoutno="figure-0")
    table_box = _box(text="", layout_type="table", layoutno="table-0")
    kept = RAGFlowPdfParser._collect_artifact_boxes([eq_fragment, eq_synth, real_figure, table_box], [])
    kept_nos = {box.layoutno for box in kept}
    assert kept_nos == {"figure-0", "table-0"}


@pytest.mark.unit
def test_runtime_formula_flag_passthrough(tmp_path, monkeypatch):
    """runtime parsing_config 的 deepdoc_formula_recognition 必须透传到解析器。"""
    captured = {}

    class _FakePdfParser:
        def __call__(self, filename, *, pdf_mode, chunk_size, formula_recognition=None):
            captured["formula_recognition"] = formula_recognition
            from novamind.engines.document.integrations.deepdoc.core.models import DeepDocParseResult
            return DeepDocParseResult(full_text="", chunks=[], metadata={})

    from novamind.engines.document.integrations.deepdoc.core.runtime_parser import DeepDocParser

    parser = DeepDocParser()
    parser._pdf_parser = _FakePdfParser()  # cached_property 可被实例属性覆盖
    monkeypatch.setattr(
        DeepDocParser, "supported_pdf_modes",
        staticmethod(lambda: {"full": {"available": True, "missing": []}}),
    )
    parser._parse_pdf_sync(
        tmp_path / "x.pdf",
        {"deepdoc_pdf_mode": "full", "deepdoc_formula_recognition": False},
        {"chunk_size": 1000},
    )
    assert captured["formula_recognition"] is False
    parser._parse_pdf_sync(
        tmp_path / "x.pdf", {"deepdoc_pdf_mode": "full"}, {"chunk_size": 1000},
    )
    assert captured["formula_recognition"] is None  # 未配置 → 默认开启


# ----------------------------------------------------------------------
# 4. 真模型冒烟（slow，模型未下载时 skip）
# ----------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.unit
def test_formula_recognizer_real_model_smoke():
    status = get_formula_model_status()
    if not status["available"]:
        pytest.skip("formula model not downloaded")
    recognizer = FormulaRecognizer()
    assert recognizer.precision in {"fp32", "int8"}
    # 纯白小图也应正常返回字符串（无 $ 包裹、不抛错）
    crop = np.full((60, 200, 3), 255, dtype=np.uint8)
    latex = recognizer.recognize(crop)
    assert isinstance(latex, str)