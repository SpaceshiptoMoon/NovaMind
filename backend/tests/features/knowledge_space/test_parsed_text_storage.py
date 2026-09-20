import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.engines.document.media.audio.audio_utils import upload_parsed_text_to_minio
from novamind.features.knowledge_space.models.document import Document

pytestmark = pytest.mark.unit
def test_parsed_text_object_persists_when_storage_is_reassigned():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE knowledge_spaces (id BIGINT PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE knowledge_bases (id BIGINT PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE users (id BIGINT PRIMARY KEY)"))
    Document.__table__.create(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    doc = Document(
        id=1,
        space_id=1,
        kb_id=1,
        uploader_id=1,
        filename="a.txt",
        file_type="txt",
        file_size=1,
        file_hash="x" * 64,
        storage={"minio_object_name": "spaces/1/kbs/1/documents/1/a.txt"},
    )
    session.add(doc)
    session.commit()

    doc.storage = {
        **(doc.storage or {}),
        "parsed_text_object": "spaces/1/kbs/1/documents/1/a.txt_parsed/full_text.md",
    }
    assert session.is_modified(doc)
    session.commit()

    loaded = session.execute(select(Document)).scalar_one()
    assert loaded.storage["parsed_text_object"].endswith("full_text.md")


def test_upload_parsed_text_to_minio_writes_utf8_sig():
    captured = {}

    class FakeMinioClient:
        async def upload_file(self, object_name, data, content_type):
            captured["object_name"] = object_name
            captured["data"] = data
            captured["content_type"] = content_type

    document = SimpleNamespace(
        id=1,
        storage={"minio_object_name": "spaces/1/kbs/1/documents/1/demo.pdf"},
    )

    logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )

    # 批次 6a-5：minio_client 改为直接注入（引擎函数不再惰性 import ClientFactory）
    object_name = asyncio.run(
        upload_parsed_text_to_minio(document, "你好", logger, minio_client=FakeMinioClient())
    )

    assert object_name.endswith("full_text.md")
    assert captured["data"].startswith(b"\xef\xbb\xbf")


# ===== 解析全文下载端点（GET .../parsed-text/download）=====


def _make_parsed_text_client(parsed_text):
    """构造挂载 knowledge_space 文档路由的 TestClient，注入假 service。

    返回 (client, calls)：calls 记录 get_parsed_text 调用供断言。
    """
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from novamind.core.database.database import get_db
    from novamind.features.knowledge_space.api import document_routes
    from novamind.features.knowledge_space.api.dependencies import (
        get_document_query_service,
        validate_space_member,
    )

    calls = {"get_parsed_text": 0, "get_document": 0}

    class FakeQueryService:
        async def get_document(self, document_id):
            calls["get_document"] += 1
            return SimpleNamespace(
                id=document_id,
                kb_id=1,
                filename="加速黎曼共轭梯度法.pdf",
            )

        async def get_parsed_text(self, document_id):
            calls["get_parsed_text"] += 1
            return parsed_text

    async def fake_member(space_id: int):
        return SimpleNamespace(user_id=1, space_id=space_id)

    async def fake_db():
        return None

    class FakeKbRepo:
        async def get_by_id(self, kb_id):
            return SimpleNamespace(id=kb_id, space_id=1, status="active")

    app = FastAPI()
    # 真实 app 由 setup_global_exception_handlers 兜底把带 code 的业务异常按
    # 后缀映射状态码（DOCUMENT_NOT_FOUND → _NOT_FOUND → 404），测试 app 同样挂载
    from novamind.core.middleware.base_exception_handler import setup_global_exception_handlers

    setup_global_exception_handlers(app)
    # space_id 由 router 挂载前缀提供（router_manager: /api/v1/spaces/{space_id}/knowledge-bases），
    # 测试挂载用等价简化前缀还原同样的路径参数结构
    app.include_router(
        document_routes.router,
        prefix="/spaces/{space_id}/knowledge-bases",
    )
    app.dependency_overrides[get_document_query_service] = lambda: FakeQueryService()
    app.dependency_overrides[validate_space_member] = fake_member
    app.dependency_overrides[get_db] = fake_db
    # validate_kb_access 在路由体内被直接调用（非 Depends），dependency_overrides 拦不住；
    # 直接替换路由模块导入的符号
    async def fake_kb_access(kb_id: int, space_id: int, db):
        return SimpleNamespace(id=kb_id, space_id=space_id)

    document_routes.validate_kb_access = fake_kb_access
    return TestClient(app, raise_server_exceptions=False), calls


def test_download_parsed_text_strips_bom_and_sets_attachment():
    """BOM bytes 进 → 干净 UTF-8 出，Content-Disposition 为 attachment 且带 RFC 5987 文件名。"""
    client, calls = _make_parsed_text_client("你好世界".encode("utf-8-sig"))

    # 直接挂载裸 router（router_manager 的 spaces/knowledge-bases 前缀在真实 app 里拼接），
    # 这里路径即 /{kb_id}/documents/{document_id}/parsed-text/download
    resp = client.get("/spaces/1/knowledge-bases/1/documents/42/parsed-text/download")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    # RFC 5987 中文文件名：原文件名去扩展名 + .md
    from urllib.parse import unquote

    disposition = resp.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    md_name = unquote(disposition.split("filename*=UTF-8''")[-1])
    assert md_name == "加速黎曼共轭梯度法.md"
    # BOM 已剥离
    assert not resp.content.startswith(b"\xef\xbb\xbf")
    assert resp.content.decode("utf-8") == "你好世界"
    assert calls["get_parsed_text"] == 1


def test_download_parsed_text_missing_returns_404():
    """未解析（get_parsed_text 返回 None）→ 404，不产生 attachment 响应。"""
    client, _ = _make_parsed_text_client(None)

    # 直接挂载裸 router（router_manager 的 spaces/knowledge-bases 前缀在真实 app 里拼接），
    # 这里路径即 /{kb_id}/documents/{document_id}/parsed-text/download
    resp = client.get("/spaces/1/knowledge-bases/1/documents/42/parsed-text/download")

    assert resp.status_code == 404
