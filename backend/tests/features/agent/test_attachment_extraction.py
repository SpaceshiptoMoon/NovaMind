"""附件文本提取与格式校验回归测试。

背景缺陷：装配点漏传 document_processor，pdf/docx 提取走 None.load_with_strategy
抛 AttributeError 被 except 吞掉，extracted_text 静默落 None——附件「上传成功但
永远读不到内容」且无从补救。修复后的行为面：装配单例 + read_full_text 全文提取 +
提取状态显式化（ok/empty/failed/skipped）+ reextract 补救端点 + markdown 归入
文本类白名单（探测失败分支不再误拒）。
"""
from types import SimpleNamespace

import pytest
from novamind.features.agent.attachments.service import AttachmentService
from novamind.features.agent.exceptions import (
    AttachmentNotFoundError,
    InvalidMessageContentError,
)
from novamind.features.agent.schemas.agent_schema import AgentChatRequest
from novamind.shared.document.validation.file_validator import FileValidator
from novamind.shared.message_attachments import sanitize_attachments_for_client

pytestmark = pytest.mark.unit


class _Recorder:
    """记录调用参数的最小桩容器。"""

    def __init__(self, result=None):
        self.calls = []
        self.result = result

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


def _make_service(*, processor="default", repo_attachment=None, downloaded=b"",
                  created=None, updated=None):
    """组装带桩的 AttachmentService（绕过 __init__ 依赖）。"""
    svc = AttachmentService.__new__(AttachmentService)
    svc.logger = SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None)
    svc.IMAGE_FILE_TYPES = {"jpg", "jpeg", "png", "gif", "webp"}
    svc.MAX_EXTRACTED_TEXT_LENGTH = 50000
    svc.ALLOWED_FILE_TYPES = {
        "pdf", "docx", "txt", "md", "markdown", "jpg", "jpeg", "png", "gif", "webp",
    }
    svc.MAX_FILE_SIZE = 20 * 1024 * 1024
    svc.db = SimpleNamespace()
    svc.minio_client = SimpleNamespace(
        default_bucket="bucket",
        _get_content_type=lambda name: "application/octet-stream",
        upload_file=_Recorder(),
        download_document=_Recorder(result=downloaded),
    )
    svc.attachment_repo = SimpleNamespace(
        create=_Recorder(result=created or SimpleNamespace(id=42)),
        get_by_id=_Recorder(result=repo_attachment),
        update_extracted_text=updated or _Recorder(result=True),
    )
    if processor == "default":
        svc._document_processor = SimpleNamespace(
            read_full_text=_Recorder(result=" extracted body text "),
        )
    else:
        svc._document_processor = processor  # None 或自定义桩
    return svc


def _upload_file(name: str, data: bytes) -> SimpleNamespace:
    return SimpleNamespace(filename=name, read=_Recorder(result=data))


# ==================== 上传：提取状态显式化 ====================


@pytest.mark.asyncio
async def test_upload_pdf_extracts_full_text_ok():
    """正例：pdf 上传经 DocumentProcessor.read_full_text 提取成功（装配断线修复面）"""
    svc = _make_service()
    result = await svc.upload_attachment(user_id=1, file=_upload_file("a.pdf", b"%PDF-1.4 fake"))

    assert result["extraction_status"] == "ok"
    assert "附件上传成功" in result["message"]
    read_args = svc._document_processor.read_full_text.calls
    assert len(read_args) == 1  # read_full_text 恰好一次（不再走切分路径）
    created_kwargs = svc.attachment_repo.create.calls[0][1]
    assert created_kwargs["extracted_text"] == " extracted body text "
    assert created_kwargs["file_type"] == "pdf"


@pytest.mark.asyncio
async def test_upload_pdf_failed_when_processor_missing():
    """反例（历史断线场景）：processor 未装配 → 显式 failed，不再静默成功文案"""
    svc = _make_service(processor=None)
    result = await svc.upload_attachment(user_id=1, file=_upload_file("a.pdf", b"%PDF-1.4 fake"))

    assert result["extraction_status"] == "failed"
    assert "提取失败" in result["message"]
    created_kwargs = svc.attachment_repo.create.calls[0][1]
    assert created_kwargs["extracted_text"] is None


@pytest.mark.asyncio
async def test_upload_pdf_engine_error_marks_failed():
    """反例：解析引擎抛错 → 状态 failed，附件记录仍创建（上传不因提取失败回滚）"""
    svc = _make_service(
        processor=SimpleNamespace(read_full_text=_Recorder())  # 调用即抛
        if False
        else _RaisingProcessor(),
    )
    result = await svc.upload_attachment(user_id=1, file=_upload_file("a.pdf", b"%PDF-1.4 fake"))

    assert result["extraction_status"] == "failed"
    assert svc.attachment_repo.create.calls, "附件仍应落库"


class _RaisingProcessor:
    async def read_full_text(self, _path):
        raise RuntimeError("engine boom")


@pytest.mark.asyncio
async def test_upload_scan_pdf_empty_text_marks_empty():
    """反例：扫描件文字层为空（引擎返回空白）→ empty 而非 ok"""
    svc = _make_service(processor=SimpleNamespace(read_full_text=_Recorder(result="  \n\t ")))
    result = await svc.upload_attachment(user_id=1, file=_upload_file("scan.pdf", b"%PDF-1.4 fake"))

    assert result["extraction_status"] == "empty"


@pytest.mark.asyncio
async def test_upload_image_skips_extraction():
    """图片附件：跳过提取，状态 skipped"""
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    svc = _make_service()
    result = await svc.upload_attachment(user_id=1, file=_upload_file("pic.png", png_bytes))

    assert result["extraction_status"] == "skipped"
    assert svc._document_processor.read_full_text.calls == []


@pytest.mark.asyncio
async def test_upload_txt_decodes_multi_encoding():
    """txt 纯文本直接解码，不经引擎"""
    svc = _make_service(processor=None)
    result = await svc.upload_attachment(user_id=1, file=_upload_file("note.txt", "中文内容".encode()))

    assert result["extraction_status"] == "ok"
    created_kwargs = svc.attachment_repo.create.calls[0][1]
    assert created_kwargs["extracted_text"] == "中文内容"


# ==================== 上传：格式校验加固 ====================


@pytest.mark.asyncio
async def test_upload_markdown_extension_normalized():
    """正例：.markdown 扩展名归一为 md 且校验放行（归一名传 validator）"""
    svc = _make_service(processor=None)
    result = await svc.upload_attachment(
        user_id=1, file=_upload_file("notes.markdown", b"# hello world")
    )

    assert result["extraction_status"] == "ok"
    created_kwargs = svc.attachment_repo.create.calls[0][1]
    assert created_kwargs["file_type"] == "md"


@pytest.mark.asyncio
async def test_markdown_accepted_when_magic_detection_fails():
    """修复验证：libmagic 与签名表都探不出时，.markdown 按文本类放行（修复前误拒）"""
    validator = FileValidator(max_file_size=1024 * 1024)
    validator.detect_mime_by_magic = lambda _c: None
    validator.detect_mime_by_header = lambda _c: None

    info = validator.validate(
        content=b"# plain markdown text", filename="notes.markdown", allowed_extensions=["md", "markdown"]
    )

    assert info.is_valid, info.validation_message


@pytest.mark.asyncio
async def test_disguised_executable_as_pdf_rejected():
    """反例：PE 可执行载荷改名 .pdf → 魔数不匹配拒绝（防伪装攻击）"""
    svc = _make_service()
    mz_payload = b"MZ" + b"\x00" * 128

    with pytest.raises(InvalidMessageContentError):
        await svc.upload_attachment(user_id=1, file=_upload_file("evil.pdf", mz_payload))


@pytest.mark.asyncio
async def test_unsupported_extension_rejected():
    """反例：白名单外扩展名拒绝"""
    svc = _make_service()

    with pytest.raises(InvalidMessageContentError):
        await svc.upload_attachment(user_id=1, file=_upload_file("evil.exe", b"MZ\x00\x00"))


@pytest.mark.asyncio
async def test_oversized_file_rejected(monkeypatch):
    """反例：超大小上限拒绝（monkeypatch 收窄上限避免构造 20MB 载荷）"""
    svc = _make_service()
    monkeypatch.setattr(svc, "MAX_FILE_SIZE", 10)

    with pytest.raises(InvalidMessageContentError):
        await svc.upload_attachment(user_id=1, file=_upload_file("big.txt", b"x" * 128))


# ==================== 重提取补救端点 ====================


@pytest.mark.asyncio
async def test_reextract_rescues_legacy_attachment():
    """正例：历史残废附件（extracted_text=None）重提取救回并回写"""
    legacy = SimpleNamespace(
        id=7, user_id=1, filename="legacy.pdf", file_type="pdf", storage_path="p/7.pdf",
    )
    updated = _Recorder(result=True)
    svc = _make_service(repo_attachment=legacy, downloaded=b"%PDF-1.4 fake", updated=updated)

    result = await svc.reextract_attachment(user_id=1, attachment_id=7)

    assert result["extraction_status"] == "ok"
    assert updated.calls == [((7, " extracted body text "), {})]


@pytest.mark.asyncio
async def test_reextract_engine_missing_marks_failed_and_clears_text():
    """反例：引擎未装配 → failed 且回写 None（与上传链同一显式失败语义）"""
    legacy = SimpleNamespace(
        id=8, user_id=1, filename="doc.docx", file_type="docx", storage_path="p/8.docx",
    )
    updated = _Recorder(result=True)
    svc = _make_service(processor=None, repo_attachment=legacy, downloaded=b"PK", updated=updated)

    result = await svc.reextract_attachment(user_id=1, attachment_id=8)

    assert result["extraction_status"] == "failed"
    assert updated.calls == [((8, None), {})]


@pytest.mark.asyncio
async def test_reextract_image_rejected():
    svc = _make_service(repo_attachment=SimpleNamespace(
        id=9, user_id=1, filename="pic.png", file_type="png", storage_path="p/9.png",
    ))

    with pytest.raises(InvalidMessageContentError):
        await svc.reextract_attachment(user_id=1, attachment_id=9)


@pytest.mark.asyncio
async def test_reextract_other_user_not_found():
    svc = _make_service(repo_attachment=SimpleNamespace(
        id=10, user_id=2, filename="x.pdf", file_type="pdf", storage_path="p/10.pdf",
    ))

    with pytest.raises(AttachmentNotFoundError):
        await svc.reextract_attachment(user_id=1, attachment_id=10)


# ==================== 回放出口白名单与请求上限 ====================


def test_sanitize_attachments_strips_internal_fields():
    """回放出口：storage_path 等内部字段剥除，白名单字段（含 preview_url）保留"""
    extra = {
        "attachments": [
            {"id": 1, "filename": "a.pdf", "file_type": "pdf", "file_size": 3,
             "storage_path": "chat-attachments/1/x.pdf"},
            {"id": 2, "filename": "b.png", "file_type": "png", "file_size": 4,
             "storage_path": "chat-attachments/1/y.png", "preview_url": "https://signed"},
        ],
        "other_key": "keep-me",
    }

    sanitize_attachments_for_client(extra)

    atts = extra["attachments"]
    assert "storage_path" not in atts[0] and "storage_path" not in atts[1]
    assert atts[0]["filename"] == "a.pdf"
    assert atts[1]["preview_url"] == "https://signed"
    assert extra["other_key"] == "keep-me"  # 非 attachments 键不受影响


def test_sanitize_attachments_none_safe():
    sanitize_attachments_for_client(None)
    sanitize_attachments_for_client({})
    sanitize_attachments_for_client({"attachments": None})


def test_attachment_ids_max_length_enforced():
    """单条消息附件数上限 10：超限 schema 校验拒绝"""
    with pytest.raises(Exception):  # pydantic ValidationError
        AgentChatRequest(content="hi", attachment_ids=list(range(11)))
    ok = AgentChatRequest(content="hi", attachment_ids=list(range(10)))
    assert len(ok.attachment_ids) == 10
