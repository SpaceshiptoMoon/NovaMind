"""子 agent 委派工具（E6）。

主 agent 经此工具把子任务委派给独立子 agent（``SubAgentRunner``）跑，
返回子 agent 的 summary。子 agent 不继承父上下文、不能再委派（防递归）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from novamind.engines.agent.tool.base import BaseTool
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class TaskTool(BaseTool):
    """子 agent 委派工具。"""

    @property
    def name(self) -> str:
        return "task"

    @property
    def description(self) -> str:
        return "子 agent 委派工具"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "task",
                    "description": (
                        "Delegate a sub-task to an independent sub-agent that runs in "
                        "isolation (no parent conversation context). Use for parallelizable "
                        "or independent sub-tasks. The sub-agent cannot delegate further "
                        "(no recursion). Returns the sub-agent's final answer summary.\n\n"
                        "When to use: complex multi-step research, multiple independent "
                        "queries, divide-and-conquer. Launch multiple task calls in one "
                        "message for parallelism."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "description": {
                                "type": "string",
                                "description": "3-5 词短描述",
                            },
                            "prompt": {
                                "type": "string",
                                "description": "给子 agent 的详细任务指令",
                            },
                            "subagent_type": {
                                "type": "string",
                                "description": "子 agent 类型（预留，默认 general）",
                                "default": "general",
                            },
                        },
                        "required": ["description", "prompt"],
                    },
                },
            }
        ]

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        if tool_name != "task":
            return f"未知工具：{tool_name}"
        runner = context.get("subagent_runner")
        if runner is None:
            return json.dumps(
                {"error": "子 agent runner 未配置（需 Agent 勾选 task 工具）"},
                ensure_ascii=False,
            )
        prompt = arguments.get("prompt") or ""
        description = arguments.get("description") or ""
        if not prompt:
            return json.dumps({"error": "prompt 不能为空"}, ensure_ascii=False)
        try:
            result = await runner.run_subagent(prompt, description)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            logger.error("子 agent 委派失败", error=str(e))
            return json.dumps(
                {"error": f"子 agent 委派失败：{str(e)}"}, ensure_ascii=False
            )