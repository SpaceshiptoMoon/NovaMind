"""VLM 文档转写线回归测试（pdf/ppt/图片三入口，2026-11-25）。

覆盖：schema 直通（pdf_vlm_model / ppt_vlm_model）、validator 残留清理、
三入口 happy path（页序保持 + 页标记剥离 + 页图 MinIO 对象名）、
模型未选 → Permanent、单页失败 → 可重试、soffice 缺失 → Permanent 带指引、
MinIO 锚点缺失 → 告警跳过不阻断（正反两用例）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    PdfParsingConfig,
    PptParsingConfig,
    build_runtime_parsing_config,
)
from novamind.features.knowledge_space.services import document_pipeline
from novamind.core.middleware.structured_logging import get_logger

pytestmark = pytest.mark.unit

_TEST_LOGGER = get_logger("test.vlm_transcribe")


async def _async_client_factory(uid, model):
    return _FakeVlmClient()


# ==================== schema 直通 ====================


class TestRuntimePassthrough:
    def test_pdf_vlm_model_passthrough(self):
        """pdf×vlm + vlm_model → strategy=vlm + pdf_vlm_model 直通。"""
        rc = build_runtime_parsing_config(
            {"text": {"pdf": {"strategy": "vlm", "vlm_model": "qwen3-vl"}}}, "pdf"
        )
        assert rc["strategy"] == "vlm"
        assert rc["pdf_vlm_model"] == "qwen3-vl"

    def test_pdf_vlm_without_model_drops_key(self):
        """pdf×vlm 未选模型：strategy 保留，模型键不落（pipeline 报「未选择」）。"""
        rc = build_runtime_parsing_config({"text": {"pdf": {"strategy": "vlm"}}}, "pdf")
        assert rc["strategy"] == "vlm"
        assert "pdf_vlm_model" not in rc

    def test_non_vlm_pdf_drops_vlm_model(self):
        """非 vlm 策略残留 vlm_model：键不落（防脏值）。"""
        rc = build_runtime_parsing_config(
            {"text": {"pdf": {"strategy": "deepdoc", "vlm_model": "qwen3-vl"}}}, "pdf"
        )
        assert "pdf_vlm_model" not in rc

    def test_ppt_vlm_model_passthrough(self):
        """ppt×vlm + vlm_model → strategy=vlm + ppt_vlm_model 直通。"""
        rc = build_runtime_parsing_config(
            {"text": {"ppt": {"strategy": "vlm", "vlm_model": "qwen3-vl"}}}, "pptx"
        )
        assert rc["strategy"] == "vlm"
        assert rc["ppt_vlm_model"] == "qwen3-vl"

    def test_pptx_normalizes_to_ppt_config(self):
        """pptx 归一到 ppt 配置面；deepdoc 策略仍带 deepdoc_parser_id=ppt。"""
        rc = build_runtime_parsing_config(
            {"text": {"ppt": {"strategy": "deepdoc"}}}, "pptx"
        )
        assert rc["strategy"] == "deepdoc"
        assert rc["deepdoc_parser_id"] == "ppt"


class TestSchemaAcceptance:
    def test_pdf_schema_accepts_vlm(self):
        cfg = PdfParsingConfig(strategy="vlm", vlm_model="qwen3-vl")
        assert cfg.strategy == "vlm"
        assert cfg.vlm_model == "qwen3-vl"
        assert cfg.parser is None, "非 deepdoc 策略残留 parser 自动清空"

    def test_ppt_schema_accepts_vlm(self):
        cfg = PptParsingConfig(strategy="vlm", vlm_model="qwen3-vl")
        assert cfg.strategy == "vlm"
        assert cfg.vlm_model == "qwen3-vl"

    def test_ppt_schema_default_deepdoc(self):
        assert PptParsingConfig().strategy == "deepdoc"


# ==================== 三入口行为（mock 渲染/客户端/MinIO） ====================


class _FakeVlmClient:
    """按调用次序返回递增页的转写文本；fail_calls 中的第 N 次调用抛错。"""

    def __init__(self, fail_calls: set[int] | None = None):
        self.fail_calls = fail_calls or set()
        self.call_count = 0

    async def generate_text(self, prompt, **kwargs):
        self.call_count += 1
        page = self.call_count
        if page in self.fail_calls:
            raise RuntimeError("vlm backend down")
        return f"# 页 {page}\n\n转写内容 {page}"


@pytest.fixture()
def pipeline_env(monkeypatch):
    """隔离环境：假渲染/假客户端/假 MinIO/假 PromptManager。"""
    captured: dict[str, Any] = {"uploads": [], "render_called": 0}

    def fake_render(content, dpi=300):
        captured["render_called"] += 1
        return [(b"jpg-page-1", 0), (b"jpg-page-2", 1)]

    from novamind.engines.document.media.ocr import qwen as qwen_mod

    monkeypatch.setattr(qwen_mod, "render_pdf_page_images", fake_render)
    monkeypatch.setattr(
        qwen_mod, "extract_pdf_page_texts", lambda content: ["第一页真值", "第二页真值"]
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.document_pipeline.render_pdf_page_images",
        fake_render,
        raising=False,
    )

    class _FakeMinio:
        async def upload_file(self, object_name, data, content_type):
            captured["uploads"].append(object_name)
            return object_name

    async def fake_get_minio_client():
        return _FakeMinio()

    from novamind.shared.storage import client_factory as cf_mod

    monkeypatch.setattr(cf_mod.ClientFactory, "get_minio_client", staticmethod(fake_get_minio_client))

    # PromptManager：模板注册表取不到时回退常量——直接 monkeypatch get_template
    from novamind.shared.prompts import prompt_manager as pm_mod

    monkeypatch.setattr(pm_mod.PromptManager, "get_template", staticmethod(lambda key: "transcribe-prompt"))

    # 降采样直通
    monkeypatch.setattr(
        document_pipeline,
        "_downscale_image_for_vlm",
        lambda data: (data, "image/jpeg"),
    )

    # ppt→pdf 转换直通
    import novamind.engines.document.converters.ppt_converter as ppt_conv

    async def fake_convert(content, filename):
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(ppt_conv, "convert_ppt_to_pdf", fake_convert)

    return captured


def _doc(file_type: str = "pdf") -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        file_type=file_type,
        filename="sample." + file_type,
        uploader_id=1,
        storage={"minio_object_name": "spaces/1/kbs/2/documents/42/abc.pdf"},
    )


def _processor(text: str):
    class _P:
        async def split_text_items(self, full_text, **kwargs):
            return [(full_text, {})]

    return _P()


class TestPdfVlmEntry:
    @pytest.mark.asyncio
    async def test_happy_path(self, pipeline_env, monkeypatch):
        """pdf×vlm：页序保持、页图对象名正确、页标记剥离、模型与页数入 metadata。"""
        doc = _doc("pdf")
        mcs = SimpleNamespace(
            get_vlm_client_by_model=_async_client_factory
        )
        result = await document_pipeline._parse_pdf_with_vlm_static(
            document=doc,
            file_content=b"%PDF-1.4 fake",
            file_path=None,
            parse_config={"pdf_vlm_model": "qwen3-vl"},
            splitting_config={"chunk_size": 1000},
            processor=_processor("x"),
            model_config_port=mcs,
            _logger=_TEST_LOGGER,
        )
        assert result.metadata["parser"] == "vlm"
        assert result.metadata["vlm_page_count"] == 2
        assert result.metadata["vlm_model"] == "qwen3-vl"
        # 页标记已剥离
        assert "<!-- page" not in result.full_text
        # 页序保持：页 1 内容在页 2 之前
        assert result.full_text.index("转写内容 1") < result.full_text.index("转写内容 2")
        # 页图对象名：{base}_pages/page_000N.jpg
        assert pipeline_env["uploads"] == [
            "spaces/1/kbs/2/documents/42/abc.pdf_pages/page_0001.jpg",
            "spaces/1/kbs/2/documents/42/abc.pdf_pages/page_0002.jpg",
        ]
        # storage 记录 pages_object_dir + 逐页地址清单（MySQL 可直接按页定位）
        assert doc.storage["pages_object_dir"] == "spaces/1/kbs/2/documents/42/abc.pdf_pages"
        assert doc.storage["pages"] == [
            {"page": 1, "object_name": "spaces/1/kbs/2/documents/42/abc.pdf_pages/page_0001.jpg"},
            {"page": 2, "object_name": "spaces/1/kbs/2/documents/42/abc.pdf_pages/page_0002.jpg"},
        ]

    @pytest.mark.asyncio
    async def test_model_missing_permanent(self, pipeline_env):
        """模型未选：终态失败（不可重试），文案指路配置。"""
        from novamind.features.knowledge_space.exceptions import PermanentProcessingError

        with pytest.raises(PermanentProcessingError, match="未选择模型"):
            await document_pipeline._parse_pdf_with_vlm_static(
                document=_doc("pdf"),
                file_content=b"%PDF-1.4",
                file_path=None,
                parse_config={},
                splitting_config={},
                processor=_processor("x"),
                model_config_port=SimpleNamespace(),
                _logger=_TEST_LOGGER,
            )

    @pytest.mark.asyncio
    async def test_page_failure_retryable(self, pipeline_env, monkeypatch):
        """单页失败/空产出 → 可重试 DocumentProcessingError，带页码。"""
        from novamind.features.knowledge_space.exceptions import DocumentProcessingError

        class _FailingMcs:
            async def get_vlm_client_by_model(self, uid, model):
                return _FakeVlmClient(fail_calls={2})

        monkeypatch.setattr(
            document_pipeline, "_downscale_image_for_vlm", lambda data: (data, "image/jpeg")
        )
        with pytest.raises(DocumentProcessingError, match="第 2 页 VLM 调用失败"):
            await document_pipeline._parse_pdf_with_vlm_static(
                document=_doc("pdf"),
                file_content=b"%PDF-1.4",
                file_path=None,
                parse_config={"pdf_vlm_model": "qwen3-vl"},
                splitting_config={},
                processor=_processor("x"),
                model_config_port=_FailingMcs(),
                _logger=_TEST_LOGGER,
            )


class TestPptVlmEntry:
    @pytest.mark.asyncio
    async def test_ppt_converts_then_transcribes(self, pipeline_env):
        """ppt×vlm：先 soffice 转 PDF（mock 直通）再走同一核心。"""
        doc = _doc("pptx")
        mcs = SimpleNamespace(get_vlm_client_by_model=_async_client_factory)
        result = await document_pipeline._parse_pdf_with_vlm_static(
            document=doc,
            file_content=b"PK fake pptx",
            file_path=None,
            parse_config={"ppt_vlm_model": "qwen3-vl"},
            splitting_config={},
            processor=_processor("x"),
            model_config_port=mcs,
            _logger=_TEST_LOGGER,
        )
        assert result.metadata["vlm_page_count"] == 2
        assert pipeline_env["render_called"] == 1

    @pytest.mark.asyncio
    async def test_soffice_missing_permanent_with_hint(self, monkeypatch):
        """soffice 缺失 → 终态失败，文案带安装指引。"""
        from novamind.features.knowledge_space.exceptions import PermanentProcessingError

        import novamind.engines.document.converters.doc_converter as dc

        monkeypatch.setattr(dc, "find_soffice", lambda: None)

        with pytest.raises(PermanentProcessingError, match="OFFICE_CONVERT"):
            await document_pipeline._parse_pdf_with_vlm_static(
                document=_doc("pptx"),
                file_content=b"PK fake",
                file_path=None,
                parse_config={"ppt_vlm_model": "qwen3-vl"},
                splitting_config={},
                processor=_processor("x"),
                model_config_port=SimpleNamespace(
                    get_vlm_client_by_model=_async_client_factory
                ),
                _logger=_TEST_LOGGER,
            )




class _ScriptedVlmClient:
    """按调用次序返回脚本化文本（用于覆盖率重试路径）。"""

    def __init__(self, scripts: list[str]):
        self.scripts = scripts
        self.calls = 0

    async def generate_text(self, prompt, **kwargs):
        text = self.scripts[min(self.calls, len(self.scripts) - 1)]
        self.calls += 1
        return text


class TestCoverageSelfCheck:
    """覆盖率自检：不达标自动重试取优；无真值哨兵；重试后仍低仅标记不失败。"""

    @pytest.mark.asyncio
    async def test_low_coverage_triggers_retry_and_picks_better(self, monkeypatch):
        """首轮覆盖率低 → 自动重试一次 → 取覆盖率高者；覆盖率入 metadata。"""
        truth_full = "这是第一页的完整真值内容，包含足够多的细节与信息量用于滑窗覆盖比对。" * 3
        calls = {"n": 0}

        class _Scripted:
            async def generate_text(self, prompt, **kwargs):
                calls["n"] += 1
                return "缺内容" if calls["n"] == 1 else truth_full

        import novamind.engines.document.media.vlm.vlm_utils as vutils
        real_cov = vutils.transcription_coverage
        monkeypatch.setattr(
            document_pipeline, "_vlm_cov_fn",
            lambda output, truth: real_cov(output, truth) if truth else None,
        )

        doc = _doc("pdf")
        result = await document_pipeline._vlm_transcribe_pages(
            document=doc,
            pages=[(b"jpg", 1)],
            vlm_client=_Scripted(),
            vlm_model_name="qwen3-vl",
            splitting_config={},
            processor=None,
            _logger=_TEST_LOGGER,
            split=False,
            truth_texts=[truth_full],
        )
        assert calls["n"] == 2, "低覆盖应触发恰好一次重试"
        assert truth_full in result.full_text, "应取高覆盖的重试产出"
        assert result.metadata["vlm_page_coverages"] and result.metadata["vlm_page_coverages"][0] >= 0.95

    @pytest.mark.asyncio
    async def test_no_truth_pages_get_none_coverage(self, monkeypatch):
        """无真值（truth_texts=None）：覆盖率记 None，不触发重试。"""
        calls = {"n": 0}

        class _Counting:
            async def generate_text(self, prompt, **kwargs):
                calls["n"] += 1
                return "无真值页转写"

        result = await document_pipeline._vlm_transcribe_pages(
            document=_doc("pdf"),
            pages=[(b"jpg", 1)],
            vlm_client=_Counting(),
            vlm_model_name="qwen3-vl",
            splitting_config={},
            processor=None,
            _logger=_TEST_LOGGER,
            split=False,
            truth_texts=None,
        )
        assert calls["n"] == 1, "无真值不应重试"
        assert result.metadata["vlm_page_coverages"] == [None]

    @pytest.mark.asyncio
    async def test_persistent_low_coverage_marked_not_failed(self, monkeypatch):
        """重试后仍不达标：不失败，元数据记录低覆盖（失败方向安全）。"""
        monkeypatch.setattr(document_pipeline, "_vlm_cov_fn", lambda out, truth: 0.4 if truth else None)
        calls = {"n": 0}

        class _Always:
            async def generate_text(self, prompt, **kwargs):
                calls["n"] += 1
                return "稀疏输出"

        doc = _doc("pdf")
        result = await document_pipeline._vlm_transcribe_pages(
            document=doc,
            pages=[(b"jpg", 1), (b"jpg2", 2)],
            vlm_client=_Always(),
            vlm_model_name="qwen3-vl",
            splitting_config={},
            processor=None,
            _logger=_TEST_LOGGER,
            split=False,
            truth_texts=["第一页真值" * 30, "第二页真值" * 30],
        )
        covs = result.metadata["vlm_page_coverages"]
        assert len(covs) == 2 and all(c is not None and c < 0.95 for c in covs)
        assert calls["n"] == 4, "每页低覆盖触发一次重试（2×2）"
        assert result.full_text, "低覆盖不失败，产出仍入库"


class TestScanOcrProxyTruth:
    """纯扫描件（文字层全空）→ DeepDoc OCR 代理真值：检出+重试+标记兜底。"""

    @pytest.mark.asyncio
    async def test_scan_uses_ocr_proxy_and_retries_below_wide_pass(self, monkeypatch):
        """文字层全空 + OCR 代理有内容 → ocr_proxy 源 + 低覆盖重试（宽线 0.70）。"""
        import novamind.engines.document.media.ocr.qwen as qwen_mod
        import novamind.engines.document.media.vlm.vlm_utils as vutils
        import novamind.engines.document.converters.doc_converter as dc

        monkeypatch.setattr(
            qwen_mod, "extract_pdf_page_texts", lambda content: ["", ""]
        )  # 纯扫描件：文字层全空
        monkeypatch.setattr(qwen_mod, "render_pdf_page_images", lambda content, dpi=144: [(b"jpg1", 0), (b"jpg2", 1)])

        proxy_calls = {"n": 0}
        monkeypatch.setattr(
            vutils, "ocr_page_text_proxy",
            lambda png: (proxy_calls.__setitem__("n", proxy_calls["n"] + 1) or "OCR代理读取的页面文本 " * 8),
        )

        calls = {"n": 0}

        class _Scripted:
            async def generate_text(self, prompt, **kwargs):
                calls["n"] += 1
                # 首轮两页都缺内容（低覆盖），第二轮补全
                return ("第一页缺" if calls["n"] <= 2 else
                        "OCR代理读取的页面文本 " * 6) if calls["n"] <= 3 else "OCR代理读取的页面文本 " * 6

        import novamind.engines.document.media.vlm.vlm_utils as _vu
        real_cov = _vu.transcription_coverage

        doc = _doc("pdf")
        doc.storage = {}

        async def run():
            class _Mcs:
                async def get_vlm_client_by_model(self, uid, model):
                    return _Scripted()

            return await document_pipeline._parse_pdf_with_vlm_static(
                document=doc,
                file_content=b"%PDF-1.4 fake-scan",
                file_path=None,
                parse_config={"pdf_vlm_model": "qwen3-vl"},
                splitting_config={},
                processor=_processor("x"),
                model_config_port=_Mcs(),
                _logger=_TEST_LOGGER,
            )

        result = await run()
        assert result.metadata["vlm_coverage_source"] == "ocr_proxy"
        assert result.metadata["vlm_coverage_pass"] == 0.70
        covs = result.metadata["vlm_page_coverages"]
        assert all(c is not None for c in covs), "代理真值页面应有覆盖率数值"
        assert calls["n"] >= 3, "低覆盖页应触发重试"

    @pytest.mark.asyncio
    async def test_ocr_proxy_failure_falls_back_to_sentinel(self, monkeypatch):
        """OCR 代理不可用：退回哨兵模式（覆盖率 None，不失败）。"""
        import novamind.engines.document.media.ocr.qwen as qwen_mod
        import novamind.engines.document.media.vlm.vlm_utils as vutils

        monkeypatch.setattr(qwen_mod, "extract_pdf_page_texts", lambda content: [""])
        def _boom(png):
            raise RuntimeError("ocr down")
        monkeypatch.setattr(vutils, "ocr_page_text_proxy", _boom)

        calls = {"n": 0}

        class _Counting:
            async def generate_text(self, prompt, **kwargs):
                calls["n"] += 1
                return "扫描件 VLM 转写"

        monkeypatch.setattr(qwen_mod, "render_pdf_page_images", lambda content, dpi=144: [(b"jpg1", 0)])

        from types import SimpleNamespace as SN

        class _Mcs:
            async def get_vlm_client_by_model(self, uid, model):
                return _Counting()

        doc2 = _doc("pdf")
        doc2.storage = {}

        result = await document_pipeline._parse_pdf_with_vlm_static(
            document=doc2,
            file_content=b"%PDF-1.4 fake-scan",
            file_path=None,
            parse_config={"pdf_vlm_model": "qwen3-vl"},
            splitting_config={},
            processor=_processor("x"),
            model_config_port=_Mcs(),
            _logger=_TEST_LOGGER,
        )
        assert result.metadata["vlm_coverage_source"] == "none"
        assert result.metadata["vlm_page_coverages"] == [None]
        assert calls["n"] == 1, "哨兵模式不应重试"


class TestPageImageUpload:
    @pytest.mark.asyncio
    async def test_anchor_missing_warns_and_continues(self, monkeypatch):
        """MinIO 锚点缺失：告警跳过页图持久化，解析主链不阻断（反例保护）。"""
        doc = _doc("pdf")
        doc.storage = {}
        uploads: list[str] = []

        class _FakeMinio:
            async def upload_file(self, object_name, data, content_type):
                uploads.append(object_name)
                return object_name

        from novamind.shared.storage import client_factory as cf_mod

        monkeypatch.setattr(
            cf_mod.ClientFactory, "get_minio_client", staticmethod(lambda: _FakeMinio())
        )
        await document_pipeline._upload_vlm_page_images(
            doc, [(b"jpg", 1)], _TEST_LOGGER
        )
        assert uploads == [], "锚点缺失不应尝试上传"
        assert "pages_object_dir" not in doc.storage
        assert "pages" not in doc.storage
