"""PDF 解析配置 validator 测试。

回归（KB 配置 update 接口 500）：PdfParsingConfig.validate_parser_usage 旧版在
strategy=default 且 parser 非空时 raise ValueError。深度合并会产生该组合——
用户从 deepdoc 切回 default，parser 旧值残留；update_knowledge_base_config
返回 KnowledgeBaseConfigResponse 时反序列化触发 validator 抛错 → 接口 500。
运行时 build_runtime_parsing_config 在 strategy=default 时本就忽略 parser
（仅 deepdoc 时取用），validator 禁止一个运行时不用的字段组合属过严。
修复：strategy=default 时自动清 parser（不报错），parser 原值保留在 DB
供切回 deepdoc 时恢复。
"""

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    KnowledgeBaseConfig,
    PdfParsingConfig,
)

pytestmark = pytest.mark.unit


# ---- PdfParsingConfig validator 放宽 ----

def test_pdf_default_strategy_accepted_with_residual_parser_cleared():
    """default 策略恢复合法（2026-11-25 双策略）：残留 parser 自动清空不抛错。"""
    cfg = PdfParsingConfig(strategy="default", parser="full")
    assert cfg.strategy == "default"
    assert cfg.parser is None, "default 不消费 parser，残留值应自动清空"


def test_pdf_vlm_strategy_auto_clears_residual_parser():
    """strategy=vlm + 残留 parser → 自动清 parser（非 deepdoc 同款语义）。"""
    cfg = PdfParsingConfig(strategy="vlm", parser="full", vlm_model="qwen3-vl")
    assert cfg.strategy == "vlm"
    assert cfg.parser is None
    assert cfg.vlm_model == "qwen3-vl"


def test_pdf_schema_default_is_deepdoc():
    """零配置（不传 strategy）落 deepdoc：扫描件开箱即用。"""
    cfg = PdfParsingConfig()
    assert cfg.strategy == "deepdoc"


def test_pdf_external_strategy_auto_clears_residual_parser():
    """strategy=external_ocr + 残留 parser → 自动清 parser=None，不抛错。"""
    cfg = PdfParsingConfig(strategy="external_ocr", parser="full")
    assert cfg.parser is None, "非 deepdoc 策略应自动清 parser"
    assert cfg.strategy == "external_ocr"


def test_pdf_deepdoc_strategy_retains_parser():
    """strategy=deepdoc + parser → 保留 parser（deepdoc 模式取用 parser）。"""
    cfg = PdfParsingConfig(strategy="deepdoc", parser="full")
    assert cfg.parser == "full"
    assert cfg.strategy == "deepdoc"


def test_pdf_deepdoc_strategy_without_parser_allowed():
    """strategy=deepdoc + 无 parser → 允许（parser Optional）。"""
    cfg = PdfParsingConfig(strategy="deepdoc")
    assert cfg.parser is None
    assert cfg.strategy == "deepdoc"


# ---- update 500 回归（route 层 KnowledgeBaseConfigResponse 反序列化）----

def test_kb_config_tolerates_default_with_residual_parser():
    """库里残留 strategy=default + parser=full 的旧配置时，KnowledgeBaseConfig
    反序列化不抛错：default 重新合法，原样保留策略；parser 由 validator 自动清。"""
    # 模拟旧库配置：default+full 残留；ocr_enabled 为已删字段的旧值，应被忽略而非报错
    merged = {
        "space_type": ["text"],
        "parsing": {
            "text": {
                "pdf": {"strategy": "default", "parser": "full", "ocr_enabled": True},
                "docx": {"strategy": "default"},
                "excel": {"strategy": "default"},
                "ppt": {"strategy": "default"},
                "epub": {"strategy": "default"},
                "markdown": {"strategy": "default"},
                "html": {"strategy": "default"},
                "txt": {"strategy": "default"},
                "json": {"strategy": "default"},
            }
        },
        "question_generation": {"enabled": False},
    }
    cfg = KnowledgeBaseConfig.model_validate(merged)  # 旧版在此抛错
    assert cfg.parsing.text.pdf.strategy == "default", "双策略恢复后 default 原样保留"
    assert cfg.parsing.text.pdf.parser is None, "default 不消费 parser，validator 自动清空"