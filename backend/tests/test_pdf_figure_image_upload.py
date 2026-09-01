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

BACKEND_ROOT = Path(__file__).resolve().parents[1]
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
