"""read_attachment 工具单元测试。

验证：schema 声明、端口缺失容错、分片参数钳制、归属校验失败的错误返回、
正常分片读取返回 JSON 结构。
"""
import json
from unittest.mock import AsyncMock

import pytest

from novamind.engines.agent.ports import AttachmentTextChunk
from novamind.engines.agent.tool.builtins.read_attachment import (
    MAX_CHUNK_LIMIT,
    ReadAttachmentTool,
)


def _chunk(**overrides) -> AttachmentTextChunk:
    base = dict(
        attachment_id=7,
        filename="年报.pdf",
        file_type="pdf",
        total_length=10000,
        offset=0,
        content="前 8000 字符",
        has_more=True,
    )
    base.update(overrides)
    return AttachmentTextChunk(**base)


def test_schema_declares_read_attachment():
    tool = ReadAttachmentTool()
    assert tool.name == "read_attachment"
    specs = tool.get_tools()
    assert len(specs) == 1
    fn = specs[0]["function"]
    assert fn["name"] == "read_attachment"
    assert fn["parameters"]["required"] == ["attachment_id"]


@pytest.mark.asyncio
async def test_port_missing_returns_error():
    tool = ReadAttachmentTool()
    out = json.loads(await tool.execute_tool("read_attachment", {"attachment_id": 1}, {}))
    assert "error" in out


@pytest.mark.asyncio
async def test_reads_via_port_with_clamped_limit():
    tool = ReadAttachmentTool()
    port = AsyncMock()
    port.get_attachment_text.return_value = _chunk()
    context = {"user_id": 42, "attachment_read_port": port}

    out = json.loads(
        await tool.execute_tool(
            "read_attachment",
            {"attachment_id": 7, "offset": -5, "limit": 999999},
            context,
        )
    )

    # offset 负数归零、limit 钳到上限
    port.get_attachment_text.assert_awaited_once_with(7, 42, 0, MAX_CHUNK_LIMIT)
    assert out["attachment_id"] == 7
    assert out["filename"] == "年报.pdf"
    assert out["has_more"] is True
    assert out["content"] == "前 8000 字符"


@pytest.mark.asyncio
async def test_attachment_not_owned_returns_error():
    tool = ReadAttachmentTool()
    port = AsyncMock()
    port.get_attachment_text.side_effect = KeyError("nope")
    context = {"user_id": 42, "attachment_read_port": port}

    out = json.loads(
        await tool.execute_tool("read_attachment", {"attachment_id": 999}, context)
    )
    assert "error" in out
    assert "999" in out["error"]


@pytest.mark.asyncio
async def test_port_internal_error_returns_error():
    tool = ReadAttachmentTool()
    port = AsyncMock()
    port.get_attachment_text.side_effect = RuntimeError("db down")
    context = {"user_id": 42, "attachment_read_port": port}

    out = json.loads(
        await tool.execute_tool("read_attachment", {"attachment_id": 7}, context)
    )
    assert "error" in out


def test_chunk_dataclass_fields():
    c = _chunk()
    assert c.total_length == 10000
    assert c.has_more is True