"""figure 短文件名 → 完整 object name 还原 + 读取时预签名替换的测试。

存储侧（MD 全文 / ES chunk content）始终保持短路径（figure_xxx.png，
不可变无时效）；已鉴权的读取端点（parsed-text 视图 / chunks 列表）在
返回前经 ``presign_figure_links`` 把短文件名替换为即时预签名 URL。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.services.document_query_service import (
    DocumentQueryService,
    resolve_figure_object_name,
)

pytestmark = pytest.mark.unit

_STORAGE = {"figures_object_dir": "spaces/1/kbs/2/documents/42/abc.pdf_figures"}


def test_resolves_short_file_to_full_object_name():
    assert resolve_figure_object_name(_STORAGE, "figure_1_page_0_10_1.png") == (
        "spaces/1/kbs/2/documents/42/abc.pdf_figures/figure_1_page_0_10_1.png"
    )


def test_rejects_path_traversal_and_nested_paths():
    """白名单拒绝 ../、子目录、反斜杠——拼接后必须仍在 figures 目录内。"""
    for bad in (
        "../spaces/other/doc.pdf",
        "figures/figure_x_1.png",
        "..\\windows\\evil.png",
        "figure_x_1.png/../../etc/passwd",
    ):
        assert resolve_figure_object_name(_STORAGE, bad) is None, bad


def test_rejects_non_figure_prefix_and_wrong_extension():
    for bad in ("secret.pdf", "figure_x_1.jpg", "figure_x_1.png.exe", "figures_x.png"):
        assert resolve_figure_object_name(_STORAGE, bad) is None, bad


def test_missing_anchor_returns_none():
    """旧文档（未重解析）无 figures_object_dir 锚点 → None（链接保持短路径）。"""
    assert resolve_figure_object_name({"minio_object_name": "x.pdf"}, "figure_a_1.png") is None
    assert resolve_figure_object_name({}, "figure_a_1.png") is None
    assert resolve_figure_object_name(None, "figure_a_1.png") is None


def test_empty_inputs_return_none():
    assert resolve_figure_object_name(_STORAGE, "") is None


# ==================== presign_figure_links（读取时签名） ====================


class _FakeDoc:
    """presign_figure_links 只需要 document.get_storage_info()/id。"""

    id = 42

    def get_storage_info(self):
        return dict(_STORAGE)


def _make_service(get_file_url=None):
    # mock 必须在函数体内新建：默认参数只求值一次，跨测试共享实例会串 await 计数
    if get_file_url is None:
        get_file_url = AsyncMock(return_value="http://minio/presigned.png")
    svc = DocumentQueryService.__new__(DocumentQueryService)
    svc.minio_client = type("M", (), {"default_bucket": "novamind-dev"})()
    svc.minio_client.get_file_url = get_file_url
    from novamind.core.middleware.structured_logging import get_logger

    svc.logger = get_logger(__name__)
    return svc


@pytest.mark.asyncio
async def test_presign_replaces_short_file_with_presigned_url():
    svc = _make_service()
    content = "前文\n![Figure 1:fig-1](figure_1_fig-1_1.png)\n后文 ![Fig2](figure_2_fig-2_3.png)"
    out = await svc.presign_figure_links(_FakeDoc(), content)
    assert "](figure_" not in out
    assert out.count("http://minio/presigned.png") == 2
    # 同一文件多次出现只签一次（去重）
    assert svc.minio_client.get_file_url.await_count == 2


@pytest.mark.asyncio
async def test_presign_keeps_content_without_figures_untouched():
    svc = _make_service()
    content = "普通文本，无图片链接"
    assert await svc.presign_figure_links(_FakeDoc(), content) == content
    assert await svc.presign_figure_links(_FakeDoc(), "") == ""
    svc.minio_client.get_file_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_presign_missing_anchor_keeps_short_path():
    """旧文档无锚点：链接原样保留（渲染层按裂图处理），不签也不崩。"""

    class _OldDoc:
        id = 42

        def get_storage_info(self):
            return {"minio_object_name": "x.pdf"}

    svc = _make_service()
    content = "![Figure 1](figure_a_1.png)"
    assert await svc.presign_figure_links(_OldDoc(), content) == content
    svc.minio_client.get_file_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_presign_single_failure_keeps_that_link_short():
    """单个签名失败只影响该链接（保持短路径），其余正常替换。"""

    async def flaky(bucket, object_name, expires):
        if "fig-2" in object_name:
            raise RuntimeError("sign error")
        return f"http://minio/ok/{object_name.rsplit('/', 1)[-1]}"

    svc = _make_service(AsyncMock(side_effect=flaky))
    content = "![A](figure_1_fig-1_1.png) ![B](figure_2_fig-2_3.png)"
    out = await svc.presign_figure_links(_FakeDoc(), content)
    assert "http://minio/ok/figure_1_fig-1_1.png" in out
    assert "](figure_2_fig-2_3.png)" in out
