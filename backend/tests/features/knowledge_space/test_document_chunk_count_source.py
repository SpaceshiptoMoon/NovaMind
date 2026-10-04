"""文档列表响应 chunk_count 取数口径回归。

历史 bug：DocumentResponse.chunk_count 从 doc_metadata 读，但 doc_metadata
从未被任何写入方填充，列表永远显示 0 分块，与 KB 统计（从任务 pipeline_result
聚合）自相矛盾。修复后改从最新任务 pipeline_result 读取。
"""

from datetime import datetime
from types import SimpleNamespace

from novamind.features.knowledge_space.schemas.document_schema import DocumentResponse


def _doc_with_task(pipeline_result: dict | None, task_status: int = 2) -> SimpleNamespace:
    """构造带最新任务的文档 ORM 替身。

    Args:
        pipeline_result: 最新任务的 pipeline_result 字典。
        task_status: 最新任务状态（默认 2=COMPLETED）。

    Returns:
        可被 DocumentResponse.model_validate 的属性对象。
    """
    task = SimpleNamespace(
        status=task_status,
        pipeline_result=pipeline_result,
        retry_count=0,
        error_message=None,
    )
    return SimpleNamespace(
        id=1,
        space_id=2,
        kb_id=4,
        uploader_id=1,
        filename="sample.pdf",
        file_type="pdf",
        file_size=1024,
        file_hash="x" * 64,
        doc_metadata=None,
        created_at=datetime(2026, 10, 1),
        updated_at=None,
        task=task,
    )


def test_chunk_count_read_from_latest_task_pipeline_result():
    """正向：已完成任务的 pipeline_result.chunk_count 透出到文档响应。"""
    doc = _doc_with_task({"chunk_count": 143, "indexed_at": "2026-10-01T00:00:00"})
    resp = DocumentResponse.model_validate(doc)
    assert resp.chunk_count == 143


def test_chunk_count_zero_when_no_task_or_missing_key():
    """反向：无任务 / pipeline_result 缺键 / 值为 None 时回 0，不误伤其它字段。"""
    # 无任务（未入队文档）
    doc = _doc_with_task(None)
    doc.task = None
    assert DocumentResponse.model_validate(doc).chunk_count == 0

    # 有任务但 pipeline_result 为 None
    assert DocumentResponse.model_validate(_doc_with_task(None)).chunk_count == 0

    # pipeline_result 存在但缺 chunk_count 键
    assert DocumentResponse.model_validate(_doc_with_task({"indexed_at": "x"})).chunk_count == 0

    # chunk_count 值为 None（脏数据）不崩、回 0
    assert DocumentResponse.model_validate(_doc_with_task({"chunk_count": None})).chunk_count == 0
