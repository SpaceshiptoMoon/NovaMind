"""群聊 consult 成员工具：专家咨询模式下主持人把问题委派给群内成员并取回答复。

静态注册单一工具名 consult_member（执行路由走注册表二级索引）；可咨询成员
名单每次 run 经 context 注入，并以 member_id enum 形式动态覆盖工具 schema
（LLM 只能看到本群真实成员）。
"""
from typing import Any

from novamind.engines.agent.tool.base import BaseTool
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 主持人调用成员时通过 context["group_consult"] 携带的回调字典键
CONSULT_CONTEXT_KEY = "group_consult"
# 回调字典约定键：fn=协程(member_id, question)->str；members=本群可咨询成员清单
CONSULT_FN_KEY = "fn"
CONSULT_MEMBERS_KEY = "members"

TOOL_NAME = "consult_member"


def _member_brief(members: list[dict[str, Any]]) -> str:
    """成员清单 → 选人线索文本（DEPENDS ON/NOT FOR 结构的 ABOUT 段）。"""
    lines = []
    for m in members:
        name = str(m.get("name") or "").replace("<", "&lt;")
        role = str(m.get("role_hint") or "无补充描述").replace("<", "&lt;")
        lines.append(f"- member_id={m.get('agent_id')}: {name} — {role}")
    return "\n".join(lines) or "（本群暂无可咨询的其他成员）"


class ConsultMemberTool(BaseTool):
    """专家咨询成员工具（consult_member）"""

    # 成员 turn 是完整 ReAct 循环（可能带工具多轮迭代），通用 30s 不够
    default_timeout_ms = 600_000

    @property
    def name(self) -> str:
        return "consult_member"

    @property
    def description(self) -> str:
        return "专家咨询：把问题委派给群内指定成员智能体处理并取回其答复"

    def get_tools(self) -> list[dict[str, Any]]:
        """声明 consult_member 函数 schema（注册期校验用，无成员 enum）。

        真实 schema（member_id enum 列出本群成员）由编排器每次 run 按成员
        清单生成并覆盖 tools 列表中的同名定义；执行期参数校验按注册期静态
        schema（无 enum 约束，任意整数放行），成员合法性由执行体校验。
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": TOOL_NAME,
                    "description": (
                        "Delegate a question to a specific group member agent and "
                        "get their full answer back."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "member_id": {
                                "type": "integer",
                                "description": "目标成员的 Agent ID",
                            },
                            "question": {
                                "type": "string",
                                "description": "交给该成员处理的问题或任务（自包含，成员看不到当前对话）",
                            },
                        },
                        "required": ["member_id", "question"],
                    },
                },
            }
        ]

    @staticmethod
    def tool_def(members: list[dict[str, Any]]) -> dict[str, Any] | None:
        """按成员清单生成带 member_id enum 的工具定义（覆盖静态同名 schema）。

        Args:
            members: 可咨询成员清单，元素含 agent_id/name/role_hint。

        Returns:
            OpenAI 格式工具定义；成员清单为空时返回 None（无可咨询对象，
            不向主持人暴露该工具）。
        """
        if not members:
            return None
        member_ids = [m["agent_id"] for m in members]
        description = (
            "Delegate a question to a specific group member agent and get their "
            "full answer back. You are the group host: pick the member whose "
            "expertise matches the question.\n\n"
            f"AVAILABLE MEMBERS:\n{_member_brief(members)}\n\n"
            "WHEN TO USE:\n"
            "- The question falls within a member's expertise above\n"
            "- You need multiple members' input before synthesizing a final answer\n"
            "- A member's answer is unsatisfactory and another member should try\n\n"
            "NOT FOR:\n"
            "- Questions you can answer directly without delegation\n"
            "- member_id values not listed above (they will be rejected)"
        )
        return {
            "type": "function",
            "function": {
                "name": TOOL_NAME,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "member_id": {
                            "type": "integer",
                            "description": "目标成员的 Agent ID（见 AVAILABLE MEMBERS）",
                            "enum": member_ids,
                        },
                        "question": {
                            "type": "string",
                            "description": "交给该成员处理的问题或任务（自包含，成员看不到当前对话）",
                        },
                    },
                    "required": ["member_id", "question"],
                },
            },
        }

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """经 context 回调拉起成员 turn，答复全文回流（回调缺失/成员非法返回错误文本）。"""
        question = str(arguments.get("question") or "").strip()
        member_id = arguments.get("member_id")
        if not question:
            return "错误：question 不能为空"

        bundle = context.get(CONSULT_CONTEXT_KEY) or {}
        fn = bundle.get(CONSULT_FN_KEY)
        members = bundle.get(CONSULT_MEMBERS_KEY) or []
        member_ids = {m.get("agent_id") for m in members}
        if fn is None:
            return "错误：本次会话未启用成员咨询（仅专家咨询模式主持人可用）"
        if member_id not in member_ids:
            return f"错误：成员 {member_id} 不在本群可咨询名单内"
        return await fn(member_id, question)

    def get_system_prompt_fragment(self) -> str:
        """不注入系统提示片段（选人线索在工具 description，身份职责在群身份 prompt）。"""
        return ""
