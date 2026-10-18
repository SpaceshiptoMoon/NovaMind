"""附件下载业务下沉回归测试（get_attachment_content）。

正例：归属匹配 → 返回附件记录 + MinIO 原始字节；
反例：附件不存在 / 他人附件 → ChatAttachmentNotFoundError（不泄漏存在性）。
"""
from types import SimpleNamespace

import pytest
from novamind.features.qa.exceptions import ChatAttachmentNotFoundError
from novamind.features.qa.services.ai_chat_service import AIChatService

pytestmark = pytest.mark.unit


def _make_service(repo_attachment, downloaded):
    async def _get_by_id(_id):
        return repo_attachment

    async def _download(_bucket, _path):
        return downloaded

    svc = AIChatService.__new__(AIChatService)
    svc.logger = SimpleNamespace(warning=lambda *a, **k: None)
    svc.attachment_repo = SimpleNamespace(get_by_id=_get_by_id)
    svc.minio_client = SimpleNamespace(
        default_bucket="bucket",
        download_document=_download,
    )
    return svc


@pytest.mark.asyncio
async def test_get_attachment_content_returns_record_and_bytes():
    attachment = SimpleNamespace(id=7, user_id=1, filename="a.pdf", storage_path="p/7.pdf")
    svc = _make_service(attachment, b"pdf-bytes")

    att, content = await svc.get_attachment_content(7, user_id=1)

    assert att is attachment
    assert content == b"pdf-bytes"


@pytest.mark.asyncio
async def test_get_attachment_content_missing_raises():
    svc = _make_service(None, b"")

    with pytest.raises(ChatAttachmentNotFoundError):
        await svc.get_attachment_content(404, user_id=1)


@pytest.mark.asyncio
async def test_get_attachment_content_other_user_raises_not_leaks():
    """他人附件按不存在处理，不泄漏附件存在性"""
    attachment = SimpleNamespace(id=9, user_id=2, filename="b.pdf", storage_path="p/9.pdf")
    svc = _make_service(attachment, b"secret")

    with pytest.raises(ChatAttachmentNotFoundError):
        await svc.get_attachment_content(9, user_id=1)
