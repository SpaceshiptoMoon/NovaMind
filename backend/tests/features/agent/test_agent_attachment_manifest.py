"""附件清单构建回归测试（对齐 deer-flow：清单进 overlays，正文走 read_attachment）。

5a13ed79 重构后注入面拆分：_build_attachment_manifest 只构建
(manifest, img_parts)，文本清单经 overlays 进 system 层（计量前），
本轮图片经 _inject_current_images 附加到最后一条 user 消息。本文件锁定
构建产物的语义契约：
1. 清单分段（本轮 / 历史 "仍然可用" / 预览 / read_attachment 指引）
2. 历史附件去重（同附件多轮引用只列一次）
3. 无附件返回 (None, [])
4. 本轮图片（非 VLM）产出文本占位 parts、文档不产出全文
5. 单段超 10 个文件折叠为 omitted 提示
6. 历史文档正文只以 500 字符预览形态出现
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from novamind.features.agent.services.chat_service import AgentChatService

pytestmark = pytest.mark.unit


def _db_msg(extra):
    return SimpleNamespace(extra=extra)


def _att(attachment_id, filename, file_type="pdf", file_size=2048):
    return {"id": attachment_id, "filename": filename, "file_type": file_type, "file_size": file_size}


def _att_record(attachment_id, filename, file_type, extracted_text="正文" * 20, file_size=2048):
    return SimpleNamespace(
        id=attachment_id, filename=filename, file_type=file_type,
        file_size=file_size, extracted_text=extracted_text,
    )


def _service(db_msgs, att_records, minio_client=None):
    """构造绕过 __init__ 的 AgentChatService 桩，注入 _build_attachment_manifest 依赖"""
    svc = AgentChatService.__new__(AgentChatService)
    db_result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: db_msgs))
    svc.db = AsyncMock()
    svc.db.execute = AsyncMock(return_value=db_result)
    svc.attachment_repo = SimpleNamespace(get_by_ids=AsyncMock(return_value=att_records))
    svc._minio_client = minio_client
    return svc


@pytest.mark.asyncio
async def test_manifest_sections_current_and_history():
    """分段：本轮附件与历史附件分列，历史段带「仍然可用」提示与去重"""
    # 历史：附件 1；本轮：附件 1（复引）+ 2（新）——同 id 只在本轮段计一次去重
    db_msgs = [
        _db_msg({"attachments": [_att(1, "旧文档.pdf")]}),
        _db_msg({"attachments": [_att(1, "旧文档.pdf"), _att(2, "新文档.pdf")]}),
    ]
    # 划分规则：最后一条带附件消息 = 本轮，其余 = 历史候选（去重后仅剩新附件）
    # 想让历史段非空需三条消息：旧附件轮 / 纯引用轮 / 本轮新附件
    records = [
        _att_record(1, "旧文档.pdf", "pdf", extracted_text="旧文档正文内容"),
        _att_record(2, "新文档.pdf", "pdf", extracted_text="新文档正文内容"),
    ]
    svc = _service(db_msgs, records)

    manifest, img_parts = await svc._build_attachment_manifest(1, 1)

    assert manifest is not None
    assert manifest.startswith("<system-uploaded-files>")
    assert "本轮上传的文件：" in manifest
    assert "新文档.pdf" in manifest
    assert "attachment_id=2" in manifest
    # 同附件多轮引用去重：附件 1 只出现一次（本轮段），不重复进历史段
    assert manifest.count("attachment_id=1") == 1
    # 正文只允许 500 字符预览，不允许全文注入
    assert "<documents>" not in manifest
    assert "read_attachment" in manifest
    assert img_parts == []


@pytest.mark.asyncio
async def test_no_attachments_returns_none():
    """无带附件消息 → (None, [])"""
    svc = _service([], [])
    manifest, img_parts = await svc._build_attachment_manifest(1, 1)
    assert manifest is None
    assert img_parts == []


@pytest.mark.asyncio
async def test_current_image_non_vlm_becomes_placeholder_parts():
    """本轮图片（非 VLM）：产出文本占位 parts；manifest 可为 None（纯图片）"""
    db_msgs = [_db_msg({"attachments": [_att(3, "截图.png", "png")]})]
    records = [_att_record(3, "截图.png", "png", extracted_text=None)]
    svc = _service(db_msgs, records)

    manifest, img_parts = await svc._build_attachment_manifest(1, 1, is_vlm=False)

    # 纯图片无文档段 → 无分段内容但仍产出骨架清单（有 current_imgs 不提前返回）
    assert manifest is not None
    assert "本轮上传的文件：" not in manifest
    assert len(img_parts) == 1
    assert "截图.png" in img_parts[0]["text"]
    assert "不支持视觉" in img_parts[0]["text"]


@pytest.mark.asyncio
async def test_manifest_sections_cap_at_ten_files():
    """单段超 10 个文件折叠为 omitted 提示"""
    atts = [_att(i, f"文档{i}.pdf") for i in range(1, 13)]
    db_msgs = [_db_msg({"attachments": atts})]
    records = [_att_record(a["id"], a["filename"], "pdf") for a in atts]
    svc = _service(db_msgs, records)

    manifest, _ = await svc._build_attachment_manifest(1, 1)

    assert "另有 2 个文件未列出" in manifest
    assert "文档1.pdf" in manifest
    assert "文档12.pdf" not in manifest  # 超出上限的不逐一列出


@pytest.mark.asyncio
async def test_history_doc_text_never_injected_as_full_xml():
    """历史文档正文只以预览形态出现在清单，绝不全文注入"""
    long_text = "机密正文" * 3000
    db_msgs = [
        _db_msg({"attachments": [_att(1, "大文档.pdf")]}),
        _db_msg({"attachments": [_att(2, "本轮.pdf")]}),
    ]
    records = [
        _att_record(1, "大文档.pdf", "pdf", extracted_text=long_text),
        _att_record(2, "本轮.pdf", "pdf", extracted_text="本轮正文"),
    ]
    svc = _service(db_msgs, records)

    manifest, _ = await svc._build_attachment_manifest(1, 1)

    assert "<documents>" not in manifest
    assert long_text not in manifest
    # 历史文档正文以 500 字符预览形态出现（预览截断：MANIFEST_PREVIEW_CHARS=500）
    assert ("机密正文" * 125) in manifest
    assert ("机密正文" * 126) not in manifest


@pytest.mark.asyncio
async def test_dry_run_skips_image_download_but_keeps_placeholder():
    """download_images=False（dry_run）：非 VLM 图片仍产出占位部件，无 MinIO 副作用"""
    db_msgs = [_db_msg({"attachments": [_att(4, "图.png", "png")]})]
    records = [_att_record(4, "图.png", "png", extracted_text=None)]
    minio = SimpleNamespace()  # 不应被触碰
    svc = _service(db_msgs, records, minio_client=minio)

    manifest, img_parts = await svc._build_attachment_manifest(1, 1, is_vlm=True, download_images=False)

    assert len(img_parts) == 1
    assert "图.png" in img_parts[0]["text"]
