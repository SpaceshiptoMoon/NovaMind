"""
内置工具：查询 Plan-and-Execute 已完成步骤的完整产出，从 agent_messages 表取回落库全文。

读取对象是 chat_service 落库的计划步骤结论消息（role=assistant + extra.plan_step_index=N）；
上下文里各步只注入头尾节选（planning_flow._bound_step_output），本工具供模型按需回查全文，
仅计划模式（extra_config.plan_mode）下由 chat_service 自动注入。
"""
import json
from typing import Any

from novamind.engines.agent.tool.base import BaseTool
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class PlanOutputTool(BaseTool):
    """查询已完成计划步骤的完整产出"""

    @property
    def name(self) -> str:
        return "plan_output"

    @property
    def description(self) -> str:
        return "查询 Plan-and-Execute 已完成步骤的完整产出（上下文只注入各步节选）"

    def get_tools(self) -> list[dict[str, Any]]:
        """声明 plan_output 函数 schema：必填 step（1-based 步骤号），可选 offset/limit 分页。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "plan_output",
                    "description": (
                        "Retrieve the FULL output of a completed plan step. The context "
                        "only injects each step's head+tail excerpt. Call this ONLY when "
                        "the current work needs details from an earlier step that the "
                        "excerpt doesn't cover. Do NOT call speculatively every step — "
                        "injected excerpts are sufficient for most steps. Steps are "
                        "1-based (step 1 = the first step of the plan)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "step": {
                                "type": "integer",
                                "description": "步骤号（从 1 开始，对应计划中的第 N 步）",
                            },
                            "offset": {
                                "type": "integer",
                                "description": "起始字符偏移量（默认 0）",
                                "default": 0,
                            },
                            "limit": {
                                "type": "integer",
                                "description": "最多返回的字符数（默认 10000）",
                                "default": 10000,
                            },
                        },
                        "required": ["step"],
                    },
                },
            }
        ]

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """按步骤号从 agent_messages 表取回该步落库全文，超长按 offset/limit 切片。

        Args:
            tool_name: 工具函数名（恒为 plan_output，由执行器透传）。
            arguments: LLM 传入的参数（step 必填 1-based；offset/limit 可选）。
            context: 工具上下文，须含 conversation_id、db_session、user_id。

        Returns:
            JSON 字符串：全文或切片（step/content/offset/limit/total_length/has_more）；
            缺参数/越权/无产出（未执行或被中断）返回含 error 的 JSON。
        """
        step = arguments.get("step")
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit", 10000)

        if not isinstance(step, int) or step < 1:
            return json.dumps({"error": "step 必须为从 1 开始的整数"})

        conversation_id = context.get("conversation_id")
        db = context.get("db_session")
        if not conversation_id or not db:
            return json.dumps({"error": "无法确定会话或数据库不可用"})

        from novamind.features.agent.models.message import AgentMessage
        from novamind.features.agent.models.session import AgentSession
        from sqlalchemy import select

        # 归属校验：会话必须属于当前用户（conversation_id 可枚举，无校验时
        # 用户可借自家 agent 读他人会话的步骤产出）。越权与未找到同文案防探测。
        sess = await db.execute(select(AgentSession).where(AgentSession.id == conversation_id))
        session_row = sess.scalar_one_or_none()
        if not session_row or session_row.user_id != context.get("user_id"):
            return json.dumps({"error": f"步骤 {step} 无已落库产出"})

        # plan_step_index 存 0-based 下标（planning_flow 循环变量 i），工具对模型暴露
        # 1-based 步骤号。extra 是 JSON 列，Python 侧过滤——会话内消息量有界，
        # 且 JSON 路径查询写法 MySQL/SQLite 不一致，不引入方言分支。
        stmt = (
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .where(AgentMessage.role == "assistant")
            .order_by(AgentMessage.id.asc())
        )
        result = await db.execute(stmt)
        step_index = step - 1
        for msg in result.scalars():
            if (msg.extra or {}).get("plan_step_index") == step_index:
                content = msg.content or ""
                total_length = len(content)
                if offset > 0 or limit < total_length:
                    sliced = content[offset : offset + limit]
                    return json.dumps(
                        {
                            "step": step,
                            "content": sliced,
                            "offset": offset,
                            "limit": limit,
                            "total_length": total_length,
                            "has_more": offset + limit < total_length,
                        },
                        ensure_ascii=False,
                    )
                return json.dumps(
                    {
                        "step": step,
                        "content": content,
                        "total_length": total_length,
                    },
                    ensure_ascii=False,
                )

        return json.dumps(
            {"error": f"步骤 {step} 无已落库产出（可能未执行或被中断）"},
            ensure_ascii=False,
        )

    def get_system_prompt_fragment(self) -> str:
        """不注入系统提示片段。"""
        return ""
