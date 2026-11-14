"""对话事件落库 mixin：chat_stream 事件分流调用的落库/记账方法（纯搬移自 chat_service）。

依赖主类属性：self.db/self.agent_service/self.logger/self.attachment_repo；
TurnPersistence 类型自独立模块导入（主文件反向 import 本模块的 plan 常量）。
"""
import json
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.engines.agent.agent_engine import AgentEvent
from novamind.features.agent.models.message import AgentMessage
from novamind.features.agent.models.session import AgentSession
from novamind.features.agent.services.turn_persistence import TurnPersistence
from sqlalchemy.orm.attributes import flag_modified

logger = get_logger(__name__)

# Plan-and-Execute 步骤状态值（与 novamind.engines.agent.flow.planning_flow 常量对齐；
# 本地定义避免 features → engines 仅为此拉 import。主文件自本模块 import。）
NOT_STARTED_VALUE = "not_started"
IN_PROGRESS_VALUE = "in_progress"


class ChatEventHandlersMixin:
    """对话事件落库 mixin：chat_stream 事件分流调用的落库/记账方法（纯搬移自 chat_service）。"""

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    def _extract_sources(
        self, event: AgentEvent, collected_sources: list[dict[str, Any]]
    ) -> None:
        """从 tool_result 事件中提取结构化来源引用（对齐 QA SourceRef）。"""
        tool_name = event.data.get("tool_name", "")
        result_str = event.data.get("result", "")
        if not result_str:
            return

        try:
            result_obj = json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            return

        if tool_name == "web_search":
            items = result_obj.get("results", [])
            if not isinstance(items, list):
                return
            start_idx = len(collected_sources)
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                collected_sources.append({
                    "index": start_idx + i + 1,
                    "kind": "web",
                    "document_name": str(item.get("title", "") or ""),
                    "url": str(item.get("url", "") or ""),
                    "snippet": str(item.get("snippet", "") or ""),
                })
        elif tool_name == "knowledge_search":
            items = result_obj.get("results", [])
            if not isinstance(items, list):
                return
            start_idx = len(collected_sources)
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                # filename 双形态兼容：扁平顶层（现役 knowledge_search）或
                # file_info 包装（QA SourceRef 旧协议），缺一取另一
                fi = item.get("file_info") or {}
                filename = fi.get("filename") or item.get("filename") or ""
                metadata = item.get("metadata") or {}
                collected_sources.append({
                    "index": start_idx + i + 1,
                    "kind": "kb",
                    "document_id": item.get("document_id"),
                    "document_name": str(filename),
                    "chunk_id": item.get("chunk_id") or metadata.get("chunk_id"),
                    "score": item.get("score"),
                    "snippet": str(item.get("content", "") or "")[:500],
                })

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _handle_plan_created(
        self, event: AgentEvent, conv: AgentSession, turn: TurnPersistence
    ) -> None:
        """处理 plan.created 事件：落库 role='plan' 消息（extra.plan 存计划清单），
        并在 turn 建立 plan_state 单一事实源（statuses 全 not_started）与 plan_msg_id，
        供后续 plan.* 事件推进状态后经 _persist_plan_state 持久化终态。
        """
        plan = event.data
        steps = plan.get("steps", [])
        msg = await self.agent_service.save_message(
            conversation_id=conv.id,
            role="plan",
            content=plan.get("title") or None,
            extra={"plan": {
                "title": plan.get("title", ""),
                "steps": steps,
                "step_count": plan.get("step_count", len(steps)),
                "statuses": [NOT_STARTED_VALUE] * len(steps),
            }},
        )
        turn.plan_msg_id = msg.id
        turn.plan_state = {
            "title": plan.get("title", ""),
            "steps": steps,
            "step_count": plan.get("step_count", len(steps)),
            "statuses": [NOT_STARTED_VALUE] * len(steps),
        }

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _apply_plan_step_status(
        self, turn: TurnPersistence, step_index: Any, status: str
    ) -> None:
        """推进 plan_state 中指定步骤的状态并持久化（step_started/completed/failed 共用）。

        Args:
            turn: 落库状态板（含 plan_state/plan_msg_id）。
            step_index: 步骤下标；None 或越界时静默跳过（防御畸形事件）。
            status: 目标状态（in_progress/completed/blocked）。
        """
        state = turn.plan_state
        if state is None or not isinstance(step_index, int):
            return
        statuses = state.get("statuses")
        if not isinstance(statuses, list) or step_index < 0 or step_index >= len(statuses):
            return
        statuses[step_index] = status
        await self._persist_plan_state(turn)

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _persist_plan_state(self, turn: TurnPersistence) -> None:
        """把 turn.plan_state 整体写回 plan 消息 extra（statuses/summary 终态）。

        update_extra 是整体替换：调用方必须传完整 plan dict。失败不阻断对话（warning）。
        """
        plan_msg_id = turn.plan_msg_id
        state = turn.plan_state
        if not plan_msg_id or not state:
            return
        try:
            await self.msg_repo.update_extra(plan_msg_id, {"plan": dict(state)})
        except Exception as e:
            logger.warning("计划状态持久化失败", error=str(e))

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _handle_plan_step_result(
        self,
        conv: AgentSession,
        turn: TurnPersistence,
        step_text: str,
        step_reasoning: str | None,
    ) -> None:
        """落库单步结论文本：role='assistant' + extra.plan_step_index 标记归属。

        内层 ReAct 最后一轮（不调工具、给出该步结论）不走决策消息落库路径，
        此处接通持久化（原三断路之一）。步内无产出时跳过；失败不阻断（warning）。
        """
        if not step_text and not step_reasoning:
            return
        try:
            await self.agent_service.save_message(
                conversation_id=conv.id,
                role="assistant",
                content=step_text or None,
                reasoning=step_reasoning,
                extra={"plan_step_index": turn.plan_step_index},
                iteration=turn.iteration,
            )
        except Exception as e:
            logger.warning("计划步骤结论落库失败", conversation_id=conv.id, error=str(e))

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _save_error_message(
        self, conv: AgentSession, content: str, extra: dict[str, Any] | None = None
    ) -> None:
        """落库错误/溢出消息（role='assistant' + extra.error），供历史回放还原失败对话。
        失败不阻断主流程（仅 warning 日志）。
        """
        try:
            text = content if content.startswith("[错误]") else f"[错误] {content}"
            await self.agent_service.save_message(
                conversation_id=conv.id,
                role="assistant",
                content=text,
                extra=extra,
            )
            # 错误消息是独立终态，立即提交：此前仅 flush 依赖后续 commit——
            # 断连 detach 模式下轮次结束即无人 commit，错误消息随会话关闭丢失
            # （真机 e2e 揪出）；连接内正常路径也一并修复（error 后生成器自然
            # 结束、handler 返回关会话，flush-only 同样丢）。
            await self.db.commit()
        except Exception as e:
            logger.warning("错误消息落库失败", conversation_id=conv.id, error=str(e))

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _handle_assistant_tool_calls(
        self,
        event: AgentEvent,
        conv: AgentSession,
        turn: TurnPersistence,
        iteration_text: str = "",
        iteration_reasoning: str = "",
    ) -> None:
        """处理 assistant_tool_calls 事件：落库「AI 决定调用工具」的 assistant 决策消息，
        并把 message_id 记入 turn，供本轮 tool_call 记录关联（而非挂在 user 消息上）。

        content 存该轮 AI 真实输出文本（经流级 scrubber 清洗，可能为空），
        reasoning 存该轮思考过程（同轮切片，供前端每步显示 think），
        extra.tool_calls 存该轮全部 OpenAI 格式 tool_calls，
        供历史回放还原完整 ReAct 链路：user → assistant(决策文本) → tool → assistant(最终)。
        """
        tool_calls = event.data.get("tool_calls", [])
        extra: dict[str, Any] = {"tool_calls": tool_calls}
        # per-iteration usage + LLM 调用耗时（轨迹视图 per-message token/耗时展示）
        if event.data.get("usage"):
            extra["usage"] = event.data["usage"]
        if event.data.get("duration_ms") is not None:
            extra["duration_ms"] = event.data["duration_ms"]
        msg = await self.agent_service.save_message(
            conversation_id=conv.id,
            role="assistant",
            content=iteration_text or None,
            reasoning=iteration_reasoning or None,
            extra=extra,
            iteration=turn.iteration,
        )
        turn.assistant_msg_id = msg.id

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _handle_tool_call(
        self,
        event: AgentEvent,
        user_msg: AgentMessage,
        conv: AgentSession,
        turn: TurnPersistence,
    ) -> None:
        """处理 tool_call 事件：保存工具调用记录"""
        call_id = event.data.get("call_id", "")
        # 优先关联到本轮 assistant 决策消息（_handle_assistant_tool_calls 写入）；
        # 缺失时 fallback 到 user 消息，保持旧链路兼容
        assistant_msg_id = turn.assistant_msg_id
        tc = await self.tc_repo.create(
            message_id=assistant_msg_id if assistant_msg_id is not None else user_msg.id,
            conversation_id=conv.id,
            call_id=call_id or None,
            tool_name=event.data["tool_name"],
            tool_source="mcp" if event.data["tool_name"].startswith("mcp__") else "skill" if event.data["tool_name"].startswith("skill__") else "builtin",
            arguments=event.data.get("arguments", {}),
            status="running",
            iteration=turn.iteration,
        )
        turn.tool_call_ids[call_id] = tc.id

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _handle_tool_result(
        self,
        event: AgentEvent,
        conv: AgentSession,
        turn: TurnPersistence,
    ) -> None:
        """处理 tool_result 事件：双路持久化（完整结果 → tool_calls，预览/原文 → messages）"""
        call_id = event.data.get("call_id", "")
        tc_id = turn.tool_call_ids.get(call_id)
        full_result = event.data.get("full_result", "")
        oversized = event.data.get("oversized", False)

        # 完整结果存 agent_tool_calls.result
        if tc_id:
            await self.tc_repo.update(
                tc_id,
                result=full_result,
                status=event.data.get("status", "completed"),
                duration_ms=event.data.get("duration_ms"),
            )

        # 预览+引用 或 原文存 agent_messages.content
        if oversized and tc_id:
            preview = event.data.get("result", "")
            original_length = event.data.get("original_length", 0)
            message_content = (
                preview + "\n\n"
                f"[结果已截断，完整结果共 {original_length} 字符。"
                f"使用 read_tool_result 工具并传入 tool_call_id={tc_id} 可获取完整结果。]"
            )
        else:
            message_content = full_result

        await self.agent_service.save_message(
            conversation_id=conv.id,
            role="tool",
            content=message_content,
            tool_call_id=call_id,
            tool_name=event.data.get("tool_name"),
            iteration=turn.iteration,
        )

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _handle_done(
        self,
        event: AgentEvent,
        conv: AgentSession,
        user_content: str,
        full_response: str,
        reasoning: str | None = None,
        sources: list[dict[str, Any]] | None = None,
        iteration: int | None = None,
    ) -> dict[str, Any]:
        """处理 done 事件：保存 assistant 消息、更新统计、设置标题"""
        total_tokens = event.data.get("total_tokens", 0)

        # 最后一轮 per-iteration usage + LLM 调用耗时（轨迹视图 per-message token/耗时）
        done_extra: dict[str, Any] = {}
        if event.data.get("last_iteration_usage"):
            done_extra["usage"] = event.data["last_iteration_usage"]
        if event.data.get("last_iteration_duration_ms") is not None:
            done_extra["duration_ms"] = event.data["last_iteration_duration_ms"]
        # 结构化引用随 assistant 消息落库：否则 sources 只活在 WS 事件里，
        # 刷新/历史回放后引用面板全空（front 端 fetchMessages 读 extra.sources）
        if sources:
            done_extra["sources"] = sources

        assistant_msg = await self.agent_service.save_message(
            conversation_id=conv.id,
            role="assistant",
            content=full_response,
            token_count=total_tokens,
            reasoning=reasoning,
            extra=done_extra or None,
            iteration=iteration,
        )

        await self.agent_service.update_session_stats(conv.id, total_tokens)

        # 更新会话标题
        await self.db.refresh(conv)
        if conv.message_count <= 1 and not conv.title:
            title = user_content[:50] + ("..." if len(user_content) > 50 else "")
            await self.session_repo.update(conv.id, title=title)

        # 轮次终态：清断连续跑标记（running_turn）与待审批（重连恢复用）
        extra = dict(conv.extra_config or {})
        if "running_turn" in extra or "pending_approval" in extra:
            extra.pop("running_turn", None)
            extra.pop("pending_approval", None)
            conv.extra_config = extra
            flag_modified(conv, "extra_config")

        await self.db.commit()

        event.data["message_id"] = assistant_msg.id
        if sources:
            event.data["sources"] = sources
        return event.data

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _record_usage(
        self,
        done_data: dict[str, Any],
        user_id: int,
        conv: AgentSession,
        agent_id: int,
        model: str,
    ) -> dict[str, Any]:
        """E1 可观测性：done_data 加 cost_usd + 写 agent_usage 表。

        失败不阻断对话（仅 warning 日志）。
        """
        usage_breakdown = done_data.get("usage_breakdown") or {}
        if not usage_breakdown:
            return done_data
        try:
            from novamind.features.agent.repository.agent_usage_repository import (
                AgentUsageRepository,
            )
            from novamind.shared.ai_models.usage import CanonicalUsage, estimate_cost

            usage = CanonicalUsage(
                input_tokens=usage_breakdown.get("input_tokens", 0),
                output_tokens=usage_breakdown.get("output_tokens", 0),
                cache_read_tokens=usage_breakdown.get("cache_read_tokens", 0),
                cache_write_tokens=usage_breakdown.get("cache_write_tokens", 0),
                reasoning_tokens=usage_breakdown.get("reasoning_tokens", 0),
            )
            cost = estimate_cost(usage, model)
            done_data["cost_usd"] = float(cost)

            usage_repo = AgentUsageRepository()
            await usage_repo.log_usage(
                user_id=user_id,
                session_id=conv.session_id,
                conversation_id=conv.id,
                agent_id=agent_id,
                model=model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                total_tokens=usage.total_tokens,
                cost_usd=cost,
                iterations=done_data.get("iterations", 0),
                tool_calls_count=done_data.get("tool_calls_count", 0),
            )
        except Exception as e:
            logger.warning("agent_usage 记录失败", error=str(e))
        return done_data

