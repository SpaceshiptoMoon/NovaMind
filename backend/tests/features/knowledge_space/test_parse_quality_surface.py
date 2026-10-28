"""解析质量面回归：外部策略前置守卫 + quality 元数据透出链。

quality 元数据此前断在快照层（引擎出账、任务结果/API/前端零消费），
本文件锁定完整透出链：metadata["quality"] → extract_parse_metadata_summary
→ _build_completion_result → DocumentResponse.quality。附带 external_ocr/
mineru 分支的 PDF 前置快检（坏文档不再白耗外部算力）。
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from novamind.features.knowledge_space.exceptions import PermanentProcessingError
from novamind.features.knowledge_space.schemas.document_schema import DocumentResponse
from novamind.features.knowledge_space.services.document_pipeline import (
    _build_completion_result,
    _guard_pdf_payload,
)
from novamind.features.knowledge_space.services.pipeline_steps import (
    extract_parse_metadata_summary,
)

pytestmark = pytest.mark.unit


# ---------- external_ocr/mineru 前置载荷快检 ----------

_DOC = SimpleNamespace(id=1)


def _make_pdf_bytes(*, user_pw: str | None = None, owner_pw: str | None = None) -> bytes:
    """fitz 造最小 PDF，可选用户密码（打开密码）与属主密码（权限密码）。"""
    import fitz

    doc = fitz.open()
    doc.new_page()
    encrypt, pw_kwargs = fitz.PDF_ENCRYPT_NONE, {}
    if user_pw or owner_pw:
        encrypt = fitz.PDF_ENCRYPT_AES_256
        if user_pw:
            pw_kwargs["user_pw"] = user_pw
        if owner_pw:
            pw_kwargs["owner_pw"] = owner_pw
    data = doc.tobytes(encryption=encrypt, **pw_kwargs)
    doc.close()
    return data


def test_guard_pdf_rejects_non_pdf():
    """非 PDF 魔数（改名/损坏）→ PermanentProcessingError，不交外部引擎。"""
    with pytest.raises(PermanentProcessingError, match="仅支持 PDF"):
        _guard_pdf_payload(b"<html>fake pdf</html>", document=_DOC, strategy="mineru")


def test_guard_pdf_rejects_user_password():
    """打开密码（needs_pass）PDF → 拒收，重试无益。"""
    payload = _make_pdf_bytes(user_pw="secret")
    with pytest.raises(PermanentProcessingError, match="已加密"):
        _guard_pdf_payload(payload, document=_DOC, strategy="external_ocr")


def test_guard_pdf_allows_owner_password_only():
    """仅权限密码（owner password，空用户密码可开）不拦——文字层可正常抽取。"""
    payload = _make_pdf_bytes(owner_pw="owner")
    _guard_pdf_payload(payload, document=_DOC, strategy="mineru")  # 不抛即通过


def test_guard_pdf_allows_normal_pdf():
    """正常 PDF（含扫描件二值图页）放行。"""
    payload = _make_pdf_bytes()
    _guard_pdf_payload(payload, document=_DOC, strategy="external_ocr")  # 不抛即通过


# ---------- quality 透出链 ----------

_QUALITY = {
    "parser": "deepdoc",
    "warnings": ["WARNING: 版面识别降级", "WARNING: 表格跨页截断"],
    "duration_ms": 1234,
}


def test_summary_quality_passthrough():
    """quality 键随 metadata 透出；缺失/非 dict 归一为 None。"""
    assert extract_parse_metadata_summary({"quality": _QUALITY})["quality"] == _QUALITY
    assert extract_parse_metadata_summary({})["quality"] is None
    assert extract_parse_metadata_summary({"quality": "corrupted"})["quality"] is None


def test_completion_result_carries_quality():
    """completion result 透传 quality（resume 与正常分支共享该构造器）。"""
    ctx = SimpleNamespace(embedding_model_name="text-embedding-v3", embedding_dim=1024)
    summary = extract_parse_metadata_summary({"quality": _QUALITY})
    result = _build_completion_result(
        chunk_count=3,
        total_tokens=30,
        parse_strategy="deepdoc",
        splitting_config={},
        parse_summary=summary,
        reading_order_count=0,
        char_count=100,
        ctx=ctx,
        parse_duration_ms=2000,
    )
    assert result["quality"] == _QUALITY


def test_document_response_quality_computed_field():
    """DocumentResponse.quality 从 task.pipeline_result 派生；无任务为 None。"""
    base = dict(
        id=1, space_id=1, kb_id=1, uploader_id=1,
        filename="a.pdf", file_type="pdf", file_size=10, file_hash="h",
        created_at=datetime.now(),
    )
    with_task = DocumentResponse(
        **base,
        task=SimpleNamespace(pipeline_result={"quality": _QUALITY}),
    )
    assert with_task.quality == _QUALITY
    without_task = DocumentResponse(**base)
    assert without_task.quality is None
