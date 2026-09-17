"""PDF figure 图片 MinIO 上传与 ES chunk 链接保存的回归测试。"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser
from novamind.features.knowledge_space.services.document_pipeline import (
    _build_es_chunks,
    _replace_figure_placeholders,
    _upload_figure_images_to_minio,
)


def _make_png_bytes(width: int = 64, height: int = 64) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=(100, 150, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_build_figure_regions_metadata_carries_image_blobs():
    """_build_figure_regions_metadata 应把 LazyImage 的 blobs 透传到 region。"""
    parser = RAGFlowPdfParser.__new__(RAGFlowPdfParser)
    artifacts = {
        "figures": [
            {
                "artifact_id": "1:page:0:10",
                "pages": [1],
                "bbox": {"x0": 10.0, "x1": 100.0, "top": 20.0, "bottom": 80.0},
                "caption": "示例图",
                "text": "",
                "members": [],
                "image": SimpleNamespace(blobs=[_make_png_bytes()]),
                "has_image": True,
            }
        ],
        "tables": [],
    }

    regions = RAGFlowPdfParser._build_figure_regions_metadata(artifacts)

    assert len(regions) == 1
    region = regions[0]
    assert region["artifact_id"] == "1:page:0:10"
    assert region["caption"] == "示例图"
    assert region["has_image"] is True
    assert len(region["image_blobs"]) == 1
    assert len(region["image_blobs"][0]) > 0


def test_reading_order_figure_entry_has_image_placeholder():
    """figure entry 应携带 image_placeholder，且文本渲染为 markdown 占位符。"""
    figure_regions = [
        {
            "artifact_id": "1:page:0:10",
            "pages": [1],
            "page_start": 1,
            "bbox": {"x0": 10.0, "x1": 100.0, "top": 20.0, "bottom": 80.0},
            "caption": "示例图",
            "text": "",
        }
    ]

    reading_order = RAGFlowPdfParser._build_reading_order_metadata([], [], figure_regions)

    figure_entry = [e for e in reading_order if e["kind"] == "figure"][0]
    assert figure_entry["source_id"] == "1:page:0:10"
    assert figure_entry["image_placeholder"] == "__FIGURE_URL__1:page:0:10__"
    rendered = RAGFlowPdfParser._reading_order_entry_text(figure_entry)
    assert rendered == "![示例图](__FIGURE_URL__1:page:0:10__)"


def test_replace_figure_placeholders_replaces_multiple():
    """_replace_figure_placeholders 应替换多个占位符。"""
    text = "A\n\n![图1](__FIGURE_URL__id1__)\n\nB\n\n![图2](__FIGURE_URL__id2__)"
    url_map = {"id1": "https://minio.example.com/fig1.png", "id2": "https://minio.example.com/fig2.png"}
    result = _replace_figure_placeholders(text, url_map)
    assert "https://minio.example.com/fig1.png" in result
    assert "https://minio.example.com/fig2.png" in result
    assert "__FIGURE_URL__" not in result


def test_replace_figure_placeholders_preserves_unknown():
    """未上传成功的占位符应保留，便于排查。"""
    text = "![图](__FIGURE_URL__missing__)"
    result = _replace_figure_placeholders(text, {})
    assert result == text


@pytest.mark.asyncio
async def test_upload_figure_images_to_minio_success():
    """上传成功时返回 {artifact_id: image_url} 并在 region 中写入字段。"""
    document = SimpleNamespace(
        id=42,
        storage={"minio_object_name": "spaces/1/kbs/2/documents/42/abc.pdf"},
    )
    png = _make_png_bytes()
    figure_regions = [
        {
            "artifact_id": "1:page:0:10",
            "page_start": 1,
            "caption": "示例图",
            "image_blobs": [png],
        }
    ]

    minio_client = AsyncMock()
    minio_client.default_bucket = "knowledge-base"
    minio_client.upload_file = AsyncMock(return_value="spaces/1/kbs/2/documents/42/abc.pdf_figures/figure_1_page_0_10_1.png")
    minio_client.get_file_url = AsyncMock(return_value="https://minio.example.com/fig.png")

    _warning_messages = []
    logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: (_warning_messages.append((args, kwargs)) or None),
    )
    url_map = await _upload_figure_images_to_minio(
        document, figure_regions, logger=logger,
        minio_client=minio_client,
    )

    assert not _warning_messages, f"unexpected warnings: {_warning_messages}"
    assert url_map == {"1:page:0:10": "https://minio.example.com/fig.png"}
    assert figure_regions[0]["minio_object_name"] == "spaces/1/kbs/2/documents/42/abc.pdf_figures/figure_1_page_0_10_1.png"
    assert figure_regions[0]["image_url"] == "https://minio.example.com/fig.png"
    assert "image_blobs" not in figure_regions[0], "上传成功后应清除原始 bytes"
    minio_client.upload_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_figure_images_filters_small_and_invalid():
    """过小或格式损坏的图片应被过滤，不上传。"""
    document = SimpleNamespace(
        id=42,
        storage={"minio_object_name": "spaces/1/kbs/2/documents/42/abc.pdf"},
    )
    figure_regions = [
        {"artifact_id": "tiny", "page_start": 1, "caption": "", "image_blobs": [b"x" * 50]},
        {"artifact_id": "bad", "page_start": 2, "caption": "", "image_blobs": [b"not a png"]},
    ]

    minio_client = AsyncMock()
    minio_client.default_bucket = "knowledge-base"

    logger = SimpleNamespace(info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None)
    url_map = await _upload_figure_images_to_minio(
        document, figure_regions, logger=logger,
        minio_client=minio_client,
    )

    assert url_map == {}
    minio_client.upload_file.assert_not_awaited()


def test_build_es_chunks_figure_image_links_per_chunk_carries_all():
    """每个文本 chunk 的 metadata.figure_image_links 都应包含文档全部图片链接。"""
    document = SimpleNamespace(
        id=1,
        space_id=1,
        kb_id=1,
        filename="test.pdf",
        file_type="pdf",
        file_hash="hash",
        storage={"minio_object_name": "spaces/1/kbs/1/documents/1/x.pdf"},
    )
    parse_metadata = {
        "parser": "deepdoc",
        "file_type": "pdf",
        "table_region_count": 0,
        "figure_region_count": 2,
        "reading_order_count": 2,
        "figure_regions": [
            {
                "artifact_id": "fig1",
                "page_start": 1,
                "caption": "图1",
                "minio_object_name": "spaces/1/kbs/1/documents/1/x.pdf_figures/figure_fig1_1.png",
                "image_url": "https://minio.example.com/fig1.png",
            },
            {
                "artifact_id": "fig2",
                "page_start": 2,
                "caption": "图2",
                "minio_object_name": "spaces/1/kbs/1/documents/1/x.pdf_figures/figure_fig2_2.png",
                "image_url": "https://minio.example.com/fig2.png",
            },
        ],
    }
    chunk_items = [
        ("文本段落", {"entry_kinds": ["text"], "entry_source_ids": ["p1"], "pages": [1], "entry_count": 1}),
        (
            "![图1](https://minio.example.com/fig1.png)",
            {"entry_kinds": ["figure"], "entry_source_ids": ["fig1"], "pages": [1], "entry_count": 1},
        ),
    ]

    from novamind.features.knowledge_space.schemas.enums import ChunkType

    es_chunks = _build_es_chunks(document, chunk_items, ChunkType.TEXT, parse_metadata=parse_metadata)

    assert len(es_chunks) == 2
    expected_links = [
        {
            "artifact_id": "fig1",
            "minio_object_name": "spaces/1/kbs/1/documents/1/x.pdf_figures/figure_fig1_1.png",
            "image_url": "https://minio.example.com/fig1.png",
            "page": 1,
            "caption": "图1",
        },
        {
            "artifact_id": "fig2",
            "minio_object_name": "spaces/1/kbs/1/documents/1/x.pdf_figures/figure_fig2_2.png",
            "image_url": "https://minio.example.com/fig2.png",
            "page": 2,
            "caption": "图2",
        },
    ]
    assert es_chunks[0]["metadata"]["figure_image_links"] == expected_links
    assert es_chunks[0]["metadata"]["figure_image_count"] == 2
    assert es_chunks[1]["metadata"]["figure_image_links"] == expected_links
    assert es_chunks[1]["metadata"]["figure_image_count"] == 2


# ===== 占位符 id 去坐标标记 + 表格去重/HTML 内联 回归 =====


def test_group_key_contains_no_position_tag():
    """_group_key 产出的 artifact_id 不得含 @@...## 坐标标记。

    曾用 {page}:{position_tag} 做 id，strip_position_tags 会把正文里的占位符
    腐蚀成 __FIGURE_URL__N:__，pipeline 替换 key 永远 miss。
    """
    from novamind.engines.document.integrations.deepdoc.pdf_artifacts import PdfArtifactExtractor

    box = SimpleNamespace(page=3, top=150.4, x0=72.6, position_tag="@@3\t72.6\t540.0\t150.4\t300.0##", text="x")
    key = PdfArtifactExtractor._group_key(box)
    assert "@@" not in key and "##" not in key
    assert key == "3:150:72"


def test_placeholder_survives_strip_and_replacement():
    """端到端：占位符经 strip_position_tags 清洗后仍能被 pipeline 替换命中。"""
    from novamind.engines.document.integrations.deepdoc.core.models import strip_position_tags

    artifact_id = "3:150:72"
    text = f"正文段落\n\n![示例图](__FIGURE_URL__{artifact_id}__)\n\n尾段"
    stripped = strip_position_tags(text)
    result = _replace_figure_placeholders(stripped, {artifact_id: "https://minio.example.com/fig.png"})
    assert "https://minio.example.com/fig.png" in result
    assert "__FIGURE_URL__" not in result
    # strip 对干净 id 无副作用
    assert "正文段落" in result


def test_table_boxes_deduped_from_text_stream():
    """table region（无 member_bboxes 的旧口径）bbox 覆盖的文本框不再重复出现在
    正文流（IoMin > 0.6 剔除）。"""
    table_region = {
        "artifact_id": "1:100:70",
        "pages": [1],
        "page_start": 1,
        "bbox": {"x0": 60.0, "x1": 550.0, "top": 90.0, "bottom": 200.0},
        "caption": "表1",
        "text": "表格内容",
    }
    covered = RAGFlowPdfParser._line_tag  # noqa: F841  仅确认 parser 类可用
    boxes = [
        # 完全落在表格 bbox 内 → 应剔除
        SimpleNamespace(page=1, x0=70.0, x1=200.0, top=100.0, bottom=120.0, text="cell", col_id=0, position_tag="", layout_type="table", layoutno="", positions=None),
        # 页面外区域 → 保留
        SimpleNamespace(page=1, x0=70.0, x1=200.0, top=400.0, bottom=420.0, text="正文", col_id=0, position_tag="", layout_type="text", layoutno="", positions=None),
    ]
    kept = RAGFlowPdfParser._drop_boxes_consumed_by_tables(boxes, [table_region])
    assert len(kept) == 1
    assert kept[0].text == "正文"


def test_table_member_bboxes_do_not_swallow_other_pages_prose():
    """成员制剔除回归：region pages 被误标题注撑爆（pages=[2..6,13]）时，
    只有成员框所在页的成员覆盖区被剔除，其它页正文必须存活——
    此前按联合 bbox 应用到 pages 全部页，18 页论文 §1-§3 整章被删。"""
    poisoned_region = {
        "artifact_id": "13:table-0",
        # 误检时代的 pages 联合（历史现场：题注成员把 p2-6 卷进表组）
        "pages": [2, 3, 4, 5, 6, 13],
        "page_start": 13,
        "bbox": {"x0": 76.0, "x1": 526.0, "top": 114.0, "bottom": 763.0},
        "caption": "",
        "text": "",
        # 成员框只在 p13（真实表格格框）
        "member_bboxes": [
            {"page": 13, "x0": 100.0, "x1": 480.0, "top": 300.0, "bottom": 400.0},
        ],
    }
    boxes = [
        # p13 表格成员覆盖区内 → 剔除
        SimpleNamespace(page=13, x0=110.0, x1=470.0, top=310.0, bottom=390.0, text="表格内容", col_id=0, position_tag="", layout_type="table", layoutno="", positions=None),
        # p2 正文——坐标完全落在被污染的联合 bbox 内 → 必须保留
        SimpleNamespace(page=2, x0=80.0, x1=520.0, top=200.0, bottom=700.0, text="§1 引言正文", col_id=0, position_tag="", layout_type="text", layoutno="", positions=None),
        # p5 正文 → 保留
        SimpleNamespace(page=5, x0=100.0, x1=500.0, top=150.0, bottom=650.0, text="§3 收敛性证明", col_id=0, position_tag="", layout_type="text", layoutno="", positions=None),
        # p13 表格外正文 → 保留
        SimpleNamespace(page=13, x0=80.0, x1=500.0, top=100.0, bottom=160.0, text="页眉段落", col_id=0, position_tag="", layout_type="text", layoutno="", positions=None),
    ]
    kept = RAGFlowPdfParser._drop_boxes_consumed_by_tables(boxes, [poisoned_region])
    kept_texts = [box.text for box in kept]
    assert kept_texts == ["§1 引言正文", "§3 收敛性证明", "页眉段落"]


def test_reading_order_table_entry_prefers_html():
    """有 TSR HTML 时 table entry 内联 HTML；无 HTML 回退 [TABLE] 前缀旧行为。"""
    entry_with_html = {
        "kind": "table",
        "caption": "表1:比较",
        "html": "<table><tr><td>a</td></tr></table>",
        "text": "散落数字流",
    }
    rendered = RAGFlowPdfParser._reading_order_entry_text(entry_with_html)
    assert "<table>" in rendered
    assert "[TABLE]" not in rendered
    assert "表1:比较" in rendered

    entry_without_html = {
        "kind": "table",
        "caption": "表1:比较",
        "html": "",
        "text": "散落数字流",
    }
    rendered = RAGFlowPdfParser._reading_order_entry_text(entry_without_html)
    assert rendered.startswith("[TABLE]")
    assert "表1:比较" in rendered
