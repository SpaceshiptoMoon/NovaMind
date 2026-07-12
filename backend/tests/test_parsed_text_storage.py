from pathlib import Path
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.models.document import Document
from novamind.core.database.base import Base


def test_parsed_text_object_persists_when_storage_is_reassigned():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
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
