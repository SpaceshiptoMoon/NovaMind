"""
ClawMate AI 对话服务

编排 ReAct 循环，将用户消息转化为工具调用序列。
复用 NovaMind 已有的 AgentEngine，通过 ClawMate 专用的工具链执行操作。

增强功能：
- 上下文压缩：复用 ContextCompressor，长对话不崩溃
- Todo 追踪：多步骤任务进度管理
- 对话历史限制：防止无限增长
"""

import json
from typing import Any, AsyncGenerator, Dict, List, Optional

from src.core.middleware.structured_logging import get_logger
from src.features.agent.core.engine import AgentEngine
from src.features.clawmate.core.session_manager import SessionManager, ClawMateSessionState
from src.features.clawmate.core.file_operations import FileOperations
from src.features.clawmate.core.memory_store import MemoryStore
from src.features.clawmate.core.prompt import build_clawmate_system_prompt
from src.features.clawmate.core.tools import TOOL_NAMES

logger = get_logger(__name__)

# 对话历史限制（保留最近 N 轮 = 2N 条消息）
MAX_HISTORY_PAIRS = 20


class ClawMateChatService:
    """ClawMate AI 对话服务"""

    def __init__(
        self,
        session_manager: SessionManager,
        agent_engine: AgentEngine,
        model_config_service: Any,
    ):
        """
        Args:
            session_manager: Session 管理器（app.state 单例）
            agent_engine: ClawMate 专用 AgentEngine（app.state 单例）
            model_config_service: 模型配置服务（per-request，需要 DB）
        """
        self.session_manager = session_manager
        self.agent_engine = agent_engine
        self.model_config_service = model_config_service

    async def chat_stream(
        self,
        user_id: int,
        content: str,
        model: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """SSE 流式 AI 对话

        Args:
            user_id: 用户 ID
            content: 用户消息
            model: 可选的模型名称

        Yields:
            SSE 格式的事件字符串
        """
        # 1. 获取/创建 session state
        state = self.session_manager.get_or_create_state(user_id)

        # 2. 防并发锁
        if state.chat_lock.locked():
            yield self._sse("error", {"message": "上一轮对话尚未完成，请等待"})
            return

        async with state.chat_lock:
            try:
                async for event in self._run_chat(state, user_id, content, model):
                    yield event
            except Exception as e:
                logger.error("ClawMate 对话失败", user_id=user_id, error=str(e))
                yield self._sse("error", {"message": f"对话失败: {str(e)}"})

    async def _run_chat(
        self,
        state: ClawMateSessionState,
        user_id: int,
        content: str,
        model: Optional[str],
    ) -> AsyncGenerator[str, None]:
        """执行一轮对话的核心逻辑"""

        # 3. 解析 LLM 模型
        llm_client = await self._resolve_model(user_id, model)
        if llm_client is None:
            yield self._sse("error", {"message": "未配置可用的 LLM 模型，请先在设置中添加模型"})
            return

        # 4. 构建系统提示词
        system_prompt = build_clawmate_system_prompt(
            cwd=state.env.cwd,
            frozen_memory=state.frozen_memory,
            frozen_user=state.frozen_user,
        )

        # 5. 构建 messages
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        # 添加历史对话
        messages.extend(state.conversation_history)
        # 添加当前用户消息
        messages.append({"role": "user", "content": content})

        # 6. 构建 context
        file_ops = FileOperations(state.env)
        memory_store = MemoryStore(state.env.cwd, file_ops)
        context = {
            "env": state.env,
            "file_ops": file_ops,
            "workspace_root": state.env.cwd,
            "memory_store": memory_store,
            "todo_store": state.todo_store,
            "user_id": user_id,
        }

        # 7. 获取工具定义（OpenAI 格式）
        tools = self.agent_engine.tool_executor.resolve_tools_openai_format(
            enabled_tools=TOOL_NAMES,
            enabled_mcp_server_ids=[],
        )

        # 8. 创建上下文压缩回调
        compress_fn = self._create_compress_fn(llm_client)

        # 9. 运行 ReAct 循环
        full_response = ""
        async for event in self.agent_engine.run(
            llm_client=llm_client,
            messages=messages,
            tools=tools,
            context=context,
            max_iterations=15,
            max_tokens=4096,
            temperature=0.7,
            stream=True,
            compress_fn=compress_fn,
        ):
            if event.event_type == "content":
                text = event.data.get("content", "")
                full_response += text
                yield self._sse("content", {"text": text})

            elif event.event_type == "reasoning":
                yield self._sse("reasoning", {"text": event.data.get("content", "")})

            elif event.event_type == "tool_call":
                yield self._sse("tool_call", {
                    "name": event.data.get("tool_name", ""),
                    "arguments": event.data.get("arguments", {}),
                    "call_id": event.data.get("call_id", ""),
                })

            elif event.event_type == "tool_result":
                # 截断过长的工具结果（SSE 前端预览用）
                result_text = event.data.get("result", "")
                if len(result_text) > 500:
                    result_text = result_text[:500] + "..."
                yield self._sse("tool_result", {
                    "name": event.data.get("tool_name", ""),
                    "result": result_text,
                })

            elif event.event_type == "context_overflow":
                # 上下文溢出 — 引擎已尝试压缩但失败或不可用
                yield self._sse("warning", {
                    "message": "对话上下文过长，已无法继续。建议开启新对话或缩减当前话题范围"
                })

            elif event.event_type == "error":
                yield self._sse("error", {"message": event.data.get("content", "未知错误")})

            elif event.event_type == "done":
                yield self._sse("done", {
                    "response": full_response,
                    "iterations": event.data.get("iterations", 0),
                    "tool_calls_count": event.data.get("tool_calls_count", 0),
                    "total_tokens": event.data.get("total_tokens", 0),
                })

        # 10. 保存对话历史（只保存 user + assistant，不保存中间 tool 调用）
        state.conversation_history.append({"role": "user", "content": content})
        if full_response:
            state.conversation_history.append({"role": "assistant", "content": full_response})

        # 11. 对话历史限制（保留最近 N 轮）
        if len(state.conversation_history) > MAX_HISTORY_PAIRS * 2:
            state.conversation_history = state.conversation_history[-(MAX_HISTORY_PAIRS * 2):]

        # 更新活跃时间
        self.session_manager.touch(user_id)

        logger.info(
            "ClawMate 对话完成",
            user_id=user_id,
            response_len=len(full_response),
            history_count=len(state.conversation_history),
        )

    def _create_compress_fn(self, llm_client: Any) -> Any:
        """创建上下文压缩回调

        捕获 ImportError — 如果 ContextCompressor 或 TokenBudget 不可用，
        返回 None（不压缩，由引擎的 context_overflow 事件处理）。
        """
        try:
            from src.features.clawmate.core.context_adapter import create_compress_fn
            context_length = getattr(llm_client, 'context_length', None)
            if not context_length:
                context_length = 128000  # 默认 128K
            return create_compress_fn(
                llm_client=llm_client,
                context_length=context_length,
            )
        except ImportError as e:
            logger.warning("上下文压缩模块不可用，长对话可能中断", error=str(e))
            return None

    async def _resolve_model(self, user_id: int, model: Optional[str]):
        """解析 LLM 模型客户端"""
        try:
            if model:
                return await self.model_config_service.get_llm_client_by_model(user_id, model)

            # 尝试获取用户默认 LLM
            default_model = await self.model_config_service.get_user_default_model_name(
                user_id, "llm"
            )
            if default_model:
                return await self.model_config_service.get_llm_client_by_model(
                    user_id, default_model
                )

            # 尝试获取任意可用 LLM
            return await self.model_config_service.get_llm_client_by_model(user_id, None)

        except Exception as e:
            logger.warning("ClawMate 模型解析失败", user_id=user_id, error=str(e))
            return None

    @staticmethod
    def _sse(event_type: str, data: dict) -> str:
        """格式化 SSE 事件"""
        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
