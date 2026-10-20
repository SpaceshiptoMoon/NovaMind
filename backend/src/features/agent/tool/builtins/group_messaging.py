"""群聊通信工具：头脑风暴模式成员主动发信通道。

send_group_message——公开发言（进群时间线，编排器转投其他成员）；
send_direct_message——点对点私信（只进收件人私有会话，不进时间线，不触发执行）。
"""
import json
from typing import Any

from novamind.engines.agent.tool.base import BaseTool
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 成员通过 context["group_messaging"] 携带的回调字典键：
# fn=协程(tool_name, arguments)->str；members=同组成员清单（[{agent_id,name}]）
MESSAGING_CONTEXT_KEY = "group_messaging"
MESSAGING_FN_KEY = "fn"
MESSAGING_MEMBERS_KEY = "members"


class GroupMessagingTool(BaseTool):
    """群聊发信工具（send_group_message / send_direct_message）"""

    @property
    def name(self) -> str:
        return "group_messaging"

    @property
    def description(self) -> str:
        return "群聊通信：向全体成员公开发言，或向指定成员发点对点私信"

    def get_tools(self) -> list[dict[str, Any]]:
        """声明两个发信函数的 OpenAI schema。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "send_group_message",
                    "description": (
                        "Broadcast a message to the whole group. The message appears on "
                        "the group timeline and is delivered to every other member.\n\n"
                        "WHEN TO USE:\n"
                        "- You want all members (and the user) to see your point\n\n"
                        "NOT FOR:\n"
                        "- Private asides to one member (use send_direct_message)"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "公开发言内容",
                            },
                        },
                        "required": ["content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "send_direct_message",
                    "description": (
                        "Send a private message to ONE specific group member. Only the "
                        "recipient sees it — it does not appear on the group timeline and "
                        "does NOT wake the recipient; they will read it when next invoked.\n\n"
                        "WHEN TO USE:\n"
                        "- Side notes, coordination, or context meant for one member only\n\n"
                        "NOT FOR:\n"
                        "- Group-wide announcements (use send_group_message)"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to_member": {
                                "type": "integer",
                                "description": "收件成员的 Agent ID（须为同组成员）",
                            },
                            "content": {
                                "type": "string",
                                "description": "私信内容",
                            },
                        },
                        "required": ["to_member", "content"],
                    },
                },
            },
        ]

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """经 context 回调落投递（编排器注入），收件人校验限定同组成员。"""
        bundle = context.get(MESSAGING_CONTEXT_KEY) or {}
        fn = bundle.get(MESSAGING_FN_KEY)
        if fn is None:
            return "错误：当前会话未启用群聊通信"
        members = bundle.get(MESSAGING_MEMBERS_KEY) or []
        if tool_name == "send_direct_message":
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
