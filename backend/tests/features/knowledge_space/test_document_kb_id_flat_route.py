"""Regression test: 文档详情裸链接 kbId 反查路由。

回归背景：文档详情页 URL 无 kbId query（外部链接/收藏夹直达）时前端取 kbId=0，
请求打到 /knowledge-bases/0/... 422，页面卡「加载中」。为此在 spaces/{space_id}
前缀下新增扁平路由 GET /documents/{document_id}/kb-id——按空间校验成员权限后
返回文档归属的 kb_id；文档不存在或不属于该空间时 404（防跨空间探测）。

本测试锁定路由处理函数的归属校验语义（不起真实 HTTP，直调 handler）。
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.features.knowledge_space.api.document_routes import get_document_kb_id
from novamind.features.knowledge_space.exceptions import DocumentNotFoundError

pytestmark = pytest.mark.unit


def _service_returning(document):
    svc = SimpleNamespace()
    # get_document 走 DocumentQueryService 实例方法，直接挂在依赖实例上
    svc.get_document = AsyncMock(return_value=document)
    return svc


def test_kb_id_route_returns_document_kb():
    """文档存在且属于该空间：返回 {kb_id, document_id}。"""
    doc = SimpleNamespace(id=576, kb_id=6, space_id=4, deleted_at=None)
    result = asyncio.run(
        get_document_kb_id(
            space_id=4,
            document_id=576,
            member=SimpleNamespace(),
            document_query_service=_service_returning(doc),
        )
    )
    assert result == {"kb_id": 6, "document_id": 576}


def test_kb_id_route_rejects_cross_space_document():
    """文档属于其它空间：404（DocumentNotFoundError），防跨空间探测。"""
    doc = SimpleNamespace(id=576, kb_id=6, space_id=2, deleted_at=None)
    with pytest.raises(DocumentNotFoundError):
        asyncio.run(
            get_document_kb_id(
                space_id=4,
                document_id=576,
                member=SimpleNamespace(),
                document_query_service=_service_returning(doc),
            )
        )


def test_kb_id_route_rejects_deleted_document():
    """软删除文档：404。"""
    doc = SimpleNamespace(id=576, kb_id=6, space_id=4, deleted_at="2026-09-24T00:00:00")
    with pytest.raises(DocumentNotFoundError):
        asyncio.run(
            get_document_kb_id(
                space_id=4,
                document_id=576,
                member=SimpleNamespace(),
                document_query_service=_service_returning(doc),
            )
        )


def test_kb_id_route_rejects_missing_document():
    """文档不存在：404。"""
    with pytest.raises(DocumentNotFoundError):
        asyncio.run(
            get_document_kb_id(
                space_id=4,
                document_id=999999,
                member=SimpleNamespace(),
                document_query_service=_service_returning(None),
            )
        )
