"""子 agent 委派 runner（E6）。

主 agent 经 ``TaskTool`` 调用 ``run_subagent``，启动一个独立子 ReAct 循环：
- 独立 messages（只含 prompt，不继承父对话上下文）
- 裁剪工具集（exclude task/todo，防递归 + 避免改全局 todo）
- 复用父 context 的端口（web_search/knowledge_search/memory 等）
- 跑完取 ``done`` 事件 full_response 作为 summary 返回

子 agent 不再委派（工具集已裁剪 task + context subagent_runner=None 双保险）。
首版不持久化子 session（session_id=None），parent_session_id 预留待后续。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from novamind.engines.agent.agent_engine import AgentEngine
from novamind.engines.agent.tool.executor import ToolExecutor
from novamind.shared.logging import get_logger
from novamind.shared.model_config_ports import ModelConfigPort

logger = get_logger(__name__)

# 子 agent 禁用工具（防递归 + 避免改全局 todo）
DELEGATE_BLOCKED_TOOLS = {"task", "todo"}


class SubAgentRunner:
    """子 agent runner：构造裁剪工具集 + 独立 messages 跑子 ReAct，返回 summary。"""

    def __init__(
        self,
        agent_engine: AgentEngine,
        tool_executor: ToolExecutor,
        model_config_service: ModelConfigPort,
        user_id: int,
        model: str,
        enabled_tools: List[str],
        enabled_mcp_ids: List[int],
        parent_context: Dict[str, Any],
    ) -> None:
        self._agent_engine = agent_engine
        self._tool_executor = tool_executor
        self._mcs = model_config_service
        self._user_id = user_id
        self._model = model
        self._enabled_tools = [
            t for t in (enabled_tools or []) if t not in DELEGATE_BLOCKED_TOOLS
        ]
        self._enabled_mcp_ids = enabled_mcp_ids or []
        self._parent_context = parent_context

    async def run_subagent(
        self, prompt: str, description: str = ""
    ) -> Dict[str, Any]:
        """跑子 agent，返回 ``{summary, session_id, description}``。"""
        # LLM 客户端（优先 LLM，fallback VLM）
        try:
            llm_client = await self._mcs.get_llm_client_by_model(
                self._user_id, self._model
            )
        except Exception:
            llm_client = await self._mcs.get_vlm_client_by_model(
                self._user_id, self._model
            )

        # 裁剪工具集（exclude task/todo）
        tools = self._tool_executor.resolve_tools_openai_format(
            self._enabled_tools, self._enabled_mcp_ids
        )

        # 独立 messages（不继承父上下文）
        messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]

        # 子 context：复用父端口，但 subagent_runner=None（双保险防递归）
        sub_context = dict(self._parent_context)
        sub_context["subagent_runner"] = None

        # 跑子 ReAct（非流式，max_iterations 收紧）
        full_response = ""
        async for event in self._agent_engine.run(
            llm_client,
            messages,
            tools,
            sub_context,
            max_iterations=5,
            stream=False,
            enable_thinking=False,
        ):
            if event.event_type == "done":
                full_response = event.data.get("full_response", "")
            elif event.event_type == "error":
                full_response = f"子 agent 执行失败：{event.data.get('content', '')}"

        return {
            "summary": full_response,
            "session_id": None,
            "description": description,
        }


__all__ = ["SubAgentRunner", "DELEGATE_BLOCKED_TOOLS"]