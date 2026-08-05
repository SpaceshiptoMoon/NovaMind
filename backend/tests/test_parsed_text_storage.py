import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.media.audio.audio_utils import upload_parsed_text_to_minio
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
