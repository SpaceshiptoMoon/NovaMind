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


def test_media_metadata_fields_exposed_from_pipeline_result():
    """正向：视频/音频形 pipeline_result 的媒体元信息全量透出。"""
    video_doc = _doc_with_task({
        "chunk_count": 4,
        "chunk_type": "video",
        "frame_count": 12,
        "duration_seconds": 62.35,
        "indexed_at": "2026-10-04T00:00:00",
    })
    resp = DocumentResponse.model_validate(video_doc)
    assert resp.chunk_type == "video"
    assert resp.frame_count == 12
    assert resp.duration_seconds == 62.35
    assert resp.segment_count is None  # 视频文档无分段数，不误报

    audio_doc = _doc_with_task({
        "chunk_count": 9,
        "chunk_type": "audio",
        "segment_count": 33,
        "duration_seconds": 185.1,
    })
    resp = DocumentResponse.model_validate(audio_doc)
    assert resp.chunk_type == "audio"
    assert resp.segment_count == 33
    assert resp.duration_seconds == 185.1
    assert resp.frame_count is None  # 音频文档无帧数，不误报


def test_media_metadata_fields_none_when_absent():
    """反向：文本文档 / 无任务 / 缺键 / 脏数据时媒体字段为 None 不误报。"""
    # 文本文档：pipeline_result 无媒体键
    text_doc = _doc_with_task({"chunk_count": 5, "token_count": 1200})
    resp = DocumentResponse.model_validate(text_doc)
    assert resp.chunk_type is None
    assert resp.duration_seconds is None
    assert resp.frame_count is None
    assert resp.segment_count is None
    assert resp.chunk_count == 5

    # 无任务
    doc = _doc_with_task(None)
    doc.task = None
    resp = DocumentResponse.model_validate(doc)
    assert resp.duration_seconds is None
    assert resp.frame_count is None

    # 值为 None（脏数据）不崩、回 None
    resp = DocumentResponse.model_validate(
        _doc_with_task({"frame_count": None, "duration_seconds": None, "chunk_type": None})
    )
    assert resp.frame_count is None
    assert resp.duration_seconds is None
    assert resp.chunk_type is None


def test_has_active_task_true_for_pending_and_processing():
    """正向：PENDING/PROCESSING 均判活跃——含 arq 自动重试等待期（status 回落 0）。"""
    # arq 重试等待期：任务真实存在、状态 PENDING(0)，可取消
    assert DocumentResponse.model_validate(_doc_with_task(None, task_status=0)).has_active_task is True
    # 处理中 PROCESSING(1)
    assert DocumentResponse.model_validate(_doc_with_task(None, task_status=1)).has_active_task is True


def test_has_active_task_false_for_terminal_or_no_task():
    """反向：终态（完成/失败/取消）与无任务不判活跃——取消按钮应收起。"""
    for terminal in (2, 3, 4):  # COMPLETED / FAILED / CANCELLED
        assert DocumentResponse.model_validate(_doc_with_task(None, task_status=terminal)).has_active_task is False

    doc = _doc_with_task(None)
    doc.task = None
    assert DocumentResponse.model_validate(doc).has_active_task is False
