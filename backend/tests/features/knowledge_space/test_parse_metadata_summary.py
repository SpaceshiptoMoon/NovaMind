"""extract_parse_metadata_summary 文档结构计数提取回归。

文档类元数据增强：PDF（pages/outlines）与 DOCX（sections/tables/images）
的结构计数从解析元数据透出，供任务 pipeline_result 持久化并上屏。
判据：键缺失或空列表 → None（「无此结构」），不误报 0；0 是真实值须保留。
"""

from novamind.features.knowledge_space.services.pipeline_steps import (
    extract_parse_metadata_summary,
)


def test_pdf_shape_metadata_counts():
    """正向：PDF full 模式 metadata（pages + outlines）产正确计数。"""
    summary = extract_parse_metadata_summary({
        "parser_class": "DeepDocParser",
        "pdf_mode": "full",
        "pages": 10,
        "outlines": [
            {"title": "第一章", "page": 1},
            {"title": "第二章", "page": 5},
            {"title": "附录", "page": 9},
        ],
    })
    assert summary["page_count"] == 10
    assert summary["outline_count"] == 3
    # PDF 不产 DOCX 结构，天然互斥为 None
    assert summary["section_count"] is None
    assert summary["table_count"] is None
    assert summary["image_count"] is None


def test_docx_shape_metadata_counts():
    """正向：DOCX metadata（sections/tables 列表 + images 计数）产正确计数。"""
    summary = extract_parse_metadata_summary({
        "parser_class": "DocxParser",
        "sections": [{"text": "p1"}, {"text": "p2"}, {"text": "p3"}],
        "tables": [["a", "b"], ["c", "d"]],
        "images": 0,  # 无内嵌图片，0 是真实值保留
    })
    assert summary["section_count"] == 3
    assert summary["table_count"] == 2
    assert summary["image_count"] == 0
    # DOCX 不产 PDF 结构
    assert summary["page_count"] is None
    assert summary["outline_count"] is None


def test_missing_or_empty_keys_yield_none_not_zero():
    """反向：空 metadata / 缺键 / 空列表 → None 不误报 0。"""
    # 空 metadata
    summary = extract_parse_metadata_summary({})
    assert summary["page_count"] is None
    assert summary["outline_count"] is None
    assert summary["section_count"] is None
    assert summary["table_count"] is None
    assert summary["image_count"] is None

    # 空列表 → 「无此结构」归 None
    summary = extract_parse_metadata_summary({
        "pages": 3, "outlines": [], "sections": [], "tables": [],
    })
    assert summary["page_count"] == 3
    assert summary["outline_count"] is None
    assert summary["section_count"] is None
    assert summary["table_count"] is None

    # images 缺键 → None；images=0 → 保留 0
    assert extract_parse_metadata_summary({"pages": 1})["image_count"] is None
    assert extract_parse_metadata_summary({"images": 0})["image_count"] == 0
