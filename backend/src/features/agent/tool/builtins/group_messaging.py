"""群聊通信工具：头脑风暴模式成员主动发信通道。

send_message——统一发信：缺省 to_member 群发全体成员（过程性投递，可被
提前看到）；指定 to_member 点对点私信（只进收件人私有会话，不进时间线，
不触发执行）。群时间线由编排器按 turn 最终发言统一落，工具发信不落时间线。
"""
import json
from typing import Any

from novamind.engines.agent.tool.base import BaseTool
from novamind.engines.agent.tool.context import ToolContext
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 成员经 ToolContext.group_messaging 携带回调字典：
# fn=协程(tool_name, arguments)->str；members=同组成员清单（[{agent_id,name}]）
MESSAGING_FN_KEY = "fn"
MESSAGING_MEMBERS_KEY = "members"


class GroupMessagingTool(BaseTool):
    """群聊发信工具（send_message）"""

    @property
    def name(self) -> str:
        return "group_messaging"

    @property
    def description(self) -> str:
        return "群聊通信：向全体成员公开发言，或向指定成员发点对点私信"

    def get_tools(self) -> list[dict[str, Any]]:
        """声明 send_message 函数的 OpenAI schema（to_member 可选：缺省群发）。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "send_message",
                    "description": (
                        "Send a message to the whole group OR to one specific member.\n\n"
                        "- WITHOUT to_member: broadcast — delivered to every other "
                        "member as a group message.\n"
                        "- WITH to_member: private note — only that member sees it; it "
                        "does not appear on the group timeline and does NOT wake the "
                        "recipient; they will read it when next invoked.\n\n"
                        "WHEN TO USE:\n"
                        "- Group-wide points (omit to_member)\n"
                        "- Side notes, coordination, or context meant for one member "
                        "only (set to_member)\n\n"
                        "NOT FOR:\n"
                        "- Your final answer: the turn's closing statement is collected "
                        "automatically — never send it via this tool"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "消息内容",
                            },
                            "to_member": {
                                "type": "integer",
                                "description": (
                                    "收件成员的 Agent ID（须为同组成员）；缺省=群发全体成员"
                                ),
                            },
                        },
                        "required": ["content"],
                    },
                },
            },
        ]

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any], context: ToolContext
    ) -> str:
        """经 context 回调落投递（编排器注入），收件人校验限定同组成员。"""
        bundle = context.group_messaging or {}
        fn = bundle.get(MESSAGING_FN_KEY)
        if fn is None:
            return "错误：当前会话未启用群聊通信"
        members = bundle.get(MESSAGING_MEMBERS_KEY) or []
        if arguments.get("to_member") is not None:
            try:
                to_member = int(arguments.get("to_member"))
            except (TypeError, ValueError):
                return json.dumps({"error": "to_member 必须是成员 Agent ID（整数）"})
            member_ids = {m.get("agent_id") for m in members}
            if to_member not in member_ids:
                return json.dumps({"error": f"成员 {to_member} 不在同组成员名单内"})
        return await fn(tool_name, arguments)

    def get_system_prompt_fragment(self) -> str:
        """不注入系统提示片段（使用指引在 agent_group_identity prompt）。"""
        return ""
