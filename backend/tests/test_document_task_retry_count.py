from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.models.document_task import DocumentTask


def test_document_task_retry_count_defaults_to_zero():
    task = DocumentTask(
        batch_id=1,
        document_id=1,
        kb_id=1,
        space_id=1,
        retry_count=0,
    )

    assert task.retry_count == 0
    task.retry_count = 2
    assert task.retry_count == 2
