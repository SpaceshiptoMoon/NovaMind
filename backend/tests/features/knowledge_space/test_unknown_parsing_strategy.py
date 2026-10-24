"""未知解析策略显式拒绝的回归测试（批次 1.4）。

历史缺陷：解析策略分发两级 if/elif 无白名单校验——脏配置（如手改 DB 写入
"cloud_ocr"）会静默落 default 分支按内置 reader 解析，扫描件抽出 0 字符才
暴露，且错误信息误导用户去切 full 模式。修复后两级分发对未知策略显式拒绝。

正例：合法值（default/deepdoc/external_ocr）与缺失/None 归一。
反例：未知字符串在两级分发点均显式报错、不再静默落 default。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.pipeline.document_loader import DocumentProcessor
from novamind.features.knowledge_space.exceptions import PermanentProcessingError
from novamind.features.knowledge_space.services.document_pipeline import (
    resolve_text_parsing_strategy,
)

pytestmark = pytest.mark.unit


class TestResolveTextParsingStrategy:
    @pytest.mark.parametrize("raw,expected", [
        ({}, "default"),
        ({"strategy": None}, "default"),
        ({"strategy": "default"}, "default"),
        ({"strategy": "deepdoc"}, "deepdoc"),
        ({"strategy": "external_ocr"}, "external_ocr"),
    ])
    def test_legal_values_pass_through(self, raw, expected):
        assert resolve_text_parsing_strategy(raw, document_id=1) == expected

    @pytest.mark.parametrize("bad", ["cloud_ocr", "DEFAULT", "", "DeepDoc"])
    def test_unknown_strategy_rejected(self, bad):
        """未知/大小写不符/空串（非缺失）一律拒绝——不静默落 default。"""
        with pytest.raises(PermanentProcessingError, match="未知解析策略"):
            resolve_text_parsing_strategy({"strategy": bad}, document_id=1)

    def test_error_mentions_legal_values(self):
        with pytest.raises(PermanentProcessingError) as exc_info:
            resolve_text_parsing_strategy({"strategy": "cloud_ocr"}, document_id=7)
        assert "default" in str(exc_info.value.error_message)
        assert "cloud_ocr" in str(exc_info.value.error_message)


class TestParseDocumentResultGateway:
    def test_unknown_strategy_raises_not_silent_default(self, tmp_path):
        doc = tmp_path / "doc.txt"
        doc.write_text("正文内容。", encoding="utf-8")
        processor = DocumentProcessor(embedding_client=None)
        with pytest.raises(ValueError, match="Unknown parsing strategy: cloud_ocr"):
            asyncio.run(
                processor.parse_document_result(doc, parsing_config={"strategy": "cloud_ocr"})
            )

    def test_missing_strategy_uses_default_reader(self, tmp_path):
        """缺失/None 归一 default，真实走通 reader 链路（正例不误伤）。"""
        doc = tmp_path / "doc.txt"
        doc.write_text("第一段正文。\n\n第二段正文。", encoding="utf-8")
        processor = DocumentProcessor(embedding_client=None)
        result = asyncio.run(processor.parse_document_result(doc, parsing_config={}))
        assert "第一段正文" in result.full_text
        assert result.metadata["parser"] == "default"
