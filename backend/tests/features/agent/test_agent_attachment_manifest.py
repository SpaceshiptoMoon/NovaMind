"""附件清单注入回归测试（对齐 deer-flow：清单进上下文，正文走 read_attachment）。

覆盖：
1. 错位 bug 回归——纯文本消息与带附件消息交错时，清单只挂最后一条用户消息，
   不再按位置索引对齐（旧 _inject_attachments_to_snapshot 的缺陷）
2. 清单分段格式（本轮 / 历史 "仍然可用" / 预览 / read_attachment 指引）
3. 无附件会话不动 snapshot
4. 本轮图片（非 VLM）以文本占位注入、文档不注入正文
5. 历史文档正文不出现在任何消息 content 中
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


def _service(db_msgs, att_records):
    """构造绕过 __init__ 的 AgentChatService 桩，注入 _inject_attachment_manifest 依赖"""
    svc = AgentChatService.__new__(AgentChatService)
    db_result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: db_msgs))
    svc.db = AsyncMock()
    svc.db.execute = AsyncMock(return_value=db_result)
    svc.attachment_repo = SimpleNamespace(get_by_ids=AsyncMock(return_value=att_records))
    svc._minio_client = None
    return svc


def _snapshot(messages):
    return SimpleNamespace(messages=messages)


def test_manifest_prepended_only_to_last_user_message():
    """错位回归：中间夹纯文本消息时清单只挂最后一条，历史/本轮分段正确"""
    # DB 侧：两条带附件消息（第一条历史、第二条本轮）；中间的纯文本消息不在查询结果里
    db_msgs = [
        _db_msg({"attachments": [_att(1, "旧文档.pdf")]}),
        _db_msg({"attachments": [_att(2, "新文档.pdf")]}),
    ]
    records = [
        _att_record(1, "旧文档.pdf", "pdf", extracted_text="旧文档正文内容"),
        _att_record(2, "新文档.pdf", "pdf", extracted_text="新文档正文内容"),
    ]
    svc = _service(db_msgs, records)

    # snapshot：3 条用户消息交错（旧附件轮 / 纯文本轮 / 本轮）+ 1 条 assistant
    snapshot = _snapshot([
        {"role": "user", "content": "请分析旧文档"},
        {"role": "assistant", "content": "好"},
        {"role": "user", "content": "中间纯文本追问"},
        {"role": "assistant", "content": "答"},
        {"role": "user", "content": "请分析新文档"},
    ])

    import asyncio
    asyncio.run(svc._inject_attachment_manifest(snapshot, conversation_id=1, user_id=1))

    msgs = snapshot.messages
    # 非最后一条用户消息不得被注入（旧实现会把附件 XML 错挂到它们头上）
    assert msgs[0]["content"] == "请分析旧文档"
    assert msgs[2]["content"] == "中间纯文本追问"

    last = msgs[4]["content"]
    assert last.startswith("<uploaded_files>")
    assert "本轮上传的文件：" in last
    assert "新文档.pdf" in last
    assert "之前轮次上传的文件（仍然可用）：" in last
    assert "旧文档.pdf" in last
    assert "attachment_id=2" in last
    # 正文只允许以 500 字符预览形态出现，不允许全文 XML 注入
    assert "<documents>" not in last
    assert "read_attachment" in last
    # 原问题保留在清单之后
    assert last.endswith("请分析新文档")


def test_no_attachments_snapshot_untouched():
    """无带附件消息时 snapshot 原样返回"""
    svc = _service([], [])
    snapshot = _snapshot([
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！"},
    ])
    import asyncio
    asyncio.run(svc._inject_attachment_manifest(snapshot, conversation_id=1, user_id=1))
    assert snapshot.messages[0]["content"] == "你好"


def test_no_user_message_in_snapshot_skips():
    """snapshot 无 user 消息（异常路径）不抛错、不动消息"""
    db_msgs = [_db_msg({"attachments": [_att(1, "文档.pdf")]})]
    svc = _service(db_msgs, [_att_record(1, "文档.pdf", "pdf")])
    snapshot = _snapshot([{"role": "assistant", "content": "占位"}])
    import asyncio
    asyncio.run(svc._inject_attachment_manifest(snapshot, conversation_id=1, user_id=1))
    assert snapshot.messages[0]["content"] == "占位"


def test_current_image_non_vlm_becomes_placeholder_parts():
    """本轮图片（非 VLM）：清单 + 文本占位 + 原问题组成 multimodal parts"""
    db_msgs = [_db_msg({"attachments": [_att(3, "截图.png", "png")]})]
    records = [_att_record(3, "截图.png", "png", extracted_text=None)]
    svc = _service(db_msgs, records)
    snapshot = _snapshot([{"role": "user", "content": "这张图里有什么"}])

    import asyncio
    asyncio.run(svc._inject_attachment_manifest(snapshot, 1, 1, is_vlm=False))

    content = snapshot.messages[0]["content"]
    assert isinstance(content, list), "带图片时应注入 multimodal parts"
    texts = [p["text"] for p in content if p.get("type") == "text"]
    assert any("截图.png" in t and "不支持视觉" in t for t in texts)
    assert texts[-1] == "这张图里有什么"  # 原问题保留在末尾
    joined = "\n".join(texts)
    assert joined.startswith("<uploaded_files>")


def test_manifest_sections_cap_at_ten_files():
    """单段超 10 个文件折叠为 omitted 提示"""
    atts = [_att(i, f"文档{i}.pdf") for i in range(1, 13)]
    db_msgs = [_db_msg({"attachments": atts})]
    records = [_att_record(a["id"], a["filename"], "pdf") for a in atts]
    svc = _service(db_msgs, records)
    snapshot = _snapshot([{"role": "user", "content": "分析"}])

    import asyncio
    asyncio.run(svc._inject_attachment_manifest(snapshot, 1, 1))

    content = snapshot.messages[0]["content"]
    assert "另有 2 个文件未列出" in content
    assert "文档1.pdf" in content
    assert "文档12.pdf" not in content  # 超出上限的不逐一列出


@pytest.mark.asyncio
async def test_history_doc_text_never_injected_as_full_xml():
    """历史文档正文绝不以 <documents> 全文形态进入任何消息"""
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
    snapshot = _snapshot([
        {"role": "user", "content": "旧问题"},
        {"role": "user", "content": "新问题"},
    ])

    await svc._inject_attachment_manifest(snapshot, 1, 1)

    assert snapshot.messages[0]["content"] == "旧问题"  # 历史消息保持干净
    last = snapshot.messages[1]["content"]
    assert "<documents>" not in last
    assert len(last) < 5000  # 清单只有几百 token，正文不进上下文