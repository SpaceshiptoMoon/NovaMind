"""
内置工具：会话附件按需读取（对齐 deer-flow read_file 模式）。

附件正文不注入上下文——上下文里只有 <uploaded_files> 清单（文件名/大小/
attachment_id/预览），模型通过本工具按 offset/limit 分片读取完整内容。
"""
import json
from typing import Any, Dict, List

from novamind.engines.agent.tool.base import BaseTool
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 单次读取上限（字符）
MAX_CHUNK_LIMIT = 20000


class ReadAttachmentTool(BaseTool):
    """会话附件文本读取工具"""

    @property
    def name(self) -> str:
        return "read_attachment"

    @property
    def description(self) -> str:
        return "会话附件按需读取：读取用户上传文档的完整提取文本"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_attachment",
                    "description": (
                        "Read the extracted text of a user-uploaded attachment "
                        "in the current conversation.\n\n"
                        "USAGE:\n"
                        "- attachment_id comes from the <uploaded_files> manifest "
                        "prepended to the user's message\n"
                        "- Start with offset=0; if has_more is true, continue "
                        "reading with offset += limit\n"
                        "- limit is in characters (default 8000, max 20000)"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "attachment_id": {
                                "type": "integer",
                                "description": "Attachment ID from the <uploaded_files> manifest",
                            },
                            "offset": {
                                "type": "integer",
                                "description": "Character offset to start reading from (default 0)",
                                "default": 0,
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max characters to return (default 8000, max 20000)",
                                "default": 8000,
                            },
                        },
                        "required": ["attachment_id"],
                    },
                },
            },
        ]

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        port = context.get("attachment_read_port")
        if port is None:
            return json.dumps(
                {"error": "附件读取端口未配置，无法读取附件内容"},
                ensure_ascii=False,
            )

        try:
            attachment_id = int(arguments.get("attachment_id", 0))
        except (TypeError, ValueError):
            return json.dumps(
                {"error": "attachment_id 必须是整数"},
                ensure_ascii=False,
            )

        try:
            offset = max(0, int(arguments.get("offset") or 0))
        except (TypeError, ValueError):
            offset = 0
        try:
            limit = int(arguments.get("limit") or 8000)
        except (TypeError, ValueError):
            limit = 8000
        limit = min(max(1, limit), MAX_CHUNK_LIMIT)

        user_id = context.get("user_id")
        if user_id is None:
            return json.dumps(
                {"error": "缺少 user_id，无法校验附件归属"},
                ensure_ascii=False,
            )

        try:
            chunk = await port.get_attachment_text(attachment_id, user_id, offset, limit)
        except KeyError:
            return json.dumps(
                {
                    "error": (
                        f"附件不存在或无权访问：attachment_id={attachment_id}。"
                        "请以 <uploaded_files> 清单中的 attachment_id 为准。"
                    )
                },
                ensure_ascii=False,
            )
        except Exception as e:
            logger.warning(
                "read_attachment 执行失败",
                attachment_id=attachment_id,
                offset=offset,
                limit=limit,
                error=str(e),
            )
            return json.dumps(
                {"error": f"读取附件失败：{e}"},
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "attachment_id": chunk.attachment_id,
                "filename": chunk.filename,
                "file_type": chunk.file_type,
                "total_length": chunk.total_length,
                "offset": chunk.offset,
                "has_more": chunk.has_more,
                "content": chunk.content,
            },
            ensure_ascii=False,
        )