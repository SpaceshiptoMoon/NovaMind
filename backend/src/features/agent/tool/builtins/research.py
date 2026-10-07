"""深度研究内置工具：包装 DeepResearchService.research_stream 为 agent 长任务工具。

进度经 context 的 event_sink 旁路直推前端 WS（approval_request 同款通道，不进
chat_stream 主事件链）；auto_approve=True 计划直接采纳（feedback_registry=None）。
研究双轨期继续写 research_sessions 留档（批4 清退时再评估剥离）。
"""
import json
from typing import Any

from novamind.engines.agent.tool.base import BaseTool
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 事件类型前缀：research_ 专用命名空间，避免与主循环 content/done 冲突
RESEARCH_PROGRESS_EVENT = "research_progress"

# 工具结果里报告正文截断上限：主模型只需要结论消化报告，全文经 research_done
# 事件与 research_sessions 留档，塞满上下文反而挤占预算
_REPORT_PREVIEW_CHARS = 6_000


class ResearchTool(BaseTool):
    """深度研究工具（对齐 DeerFlow task 语义的迭代上界：mode_config 的 depth×iterations）"""

    default_timeout_ms = 15 * 60 * 1000

    @property
    def name(self) -> str:
        return "research"

    @property
    def description(self) -> str:
        return "深度研究：对复杂课题做多轮检索、计划、综合，产出带引用的研究报告（耗时数分钟）"

    def get_tools(self) -> list[dict[str, Any]]:
        """返回深度研究工具定义：query 必填，模式/来源/风格可选。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "research",
                    "description": (
                        "Run deep research on a complex topic. Plans the investigation, "
                        "searches internal knowledge bases and/or the web over multiple "
                        "iterations, then synthesizes a cited research report. "
                        "Takes several minutes; progress is streamed to the user.\n\n"
                        "USAGE:\n"
                        "- Use ONLY for complex, multi-facet questions that need broad "
                        "investigation (surveys, comparisons, state-of-the-art reviews)\n"
                        "- Do NOT use for simple factual questions (answer directly or "
                        "use knowledge_search / web_search)\n"
                        "- Write a self-contained research query; the user's context is "
                        "NOT carried over automatically\n"
                        "- Report progress to the user before calling this tool"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Research question/topic, self-contained and specific",
                            },
                            "research_mode": {
                                "type": "string",
                                "enum": ["quick", "standard", "deep"],
                                "description": "Research depth: quick / standard (default) / deep",
                                "default": "standard",
                            },
                            "search_source": {
                                "type": "string",
                                "enum": ["internal", "external", "hybrid"],
                                "description": "Search sources: internal KB / external web / both (default)",
                                "default": "hybrid",
                            },
                            "report_style": {
                                "type": "string",
                                "enum": ["academic", "popular_science", "news", "default"],
                                "description": "Report style (default: default)",
                                "default": "default",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
        ]

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """执行深度研究：消费 research_stream 事件流，进度旁路推 WS，报告落工具结果。

        Args:
            tool_name: 工具名（仅认 research）。
            arguments: 工具参数：query 必填，research_mode/search_source/report_style 可选。
            context: 执行上下文：research_service_factory（缺失时拒绝执行）、
                event_sink（进度旁路通道，缺失时静默降级只留最终结果）。

        Returns:
            JSON 文本：成功为 {report, topic, stats, citations}（report 截断预览）；
            失败为 {error}。
        """
        if tool_name != "research":
            return f"未知工具：{tool_name}"

        factory = context.get("research_service_factory")
        if factory is None:
            return json.dumps(
                {"error": "深度研究服务未配置（需 Agent 勾选 research 工具）"},
                ensure_ascii=False,
            )

        query = str(arguments.get("query") or "").strip()
        if len(query) < 5:
            return json.dumps(
                {"error": "研究主题过短（至少 5 个字符），请给出具体的研究问题"},
                ensure_ascii=False,
            )

        event_sink = context.get("event_sink")
        request = self._build_request(arguments)
        user_id = int(context.get("user_id") or 0)
        # 研究空间取会话知识绑定的第一个 space（批2 范围约束同样约束研究）；
        # 无绑定时 None——研究会话落库 NULL（无空间归属），内部检索无空间上下文
        pipeline_cfg = context.get("knowledge_pipeline") or {}
        bound_space_ids = ((pipeline_cfg.get("knowledge_bindings") or {}).get("space_ids"))
        space_id = int(bound_space_ids[0]) if bound_space_ids else None

        topic = ""
        stats: dict[str, Any] = {}
        citations: list[dict[str, str]] = []
        full_report = ""
        service = factory()
        try:
            async for event in service.research_stream(
                space_id=space_id, user_id=user_id, request=request
            ):
                etype = event.get("type", "")
                data = event.get("data") or {}
                if etype == "progress":
                    await self._emit_progress(event_sink, data)
                elif etype == "plan_generated":
                    await self._emit_plan(event_sink, data)
                elif etype == "content":
                    full_report += str(data.get("chunk") or "")
                elif etype == "done":
                    full_report = str(data.get("final_report") or full_report)
                    stats = data.get("stats") or {}
                    citations = data.get("citations") or []
                    topic = str(data.get("session_id") or "")
                elif etype == "error":
                    return json.dumps(
                        {"error": str(data.get("message") or "研究执行失败")},
                        ensure_ascii=False,
                    )
        except Exception as e:
            logger.error("深度研究工具执行失败", error=str(e))
            return json.dumps(
                {"error": f"深度研究失败：{str(e)}"}, ensure_ascii=False
            )
        finally:
            await service.cleanup()
            # research 服务持有独立 db session（与外层 chat 事务隔离），用完即关
            session = getattr(service, "session", None)
            if session is not None:
                try:
                    await session.close()
                except Exception:
                    pass

        if not full_report:
            return json.dumps(
                {"error": "研究未产出报告内容"}, ensure_ascii=False
            )

        return json.dumps(
            {
                "report": full_report[:_REPORT_PREVIEW_CHARS],
                "report_truncated": len(full_report) > _REPORT_PREVIEW_CHARS,
                "full_report_length": len(full_report),
                "research_session_id": topic,
                "stats": stats,
                "citations": citations,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _build_request(arguments: dict[str, Any]) -> Any:
        """把工具参数映射为 ResearchRequest（非法枚举值回退默认档）。"""
        from novamind.features.deep_research.schemas.research_schema import (
            ResearchRequest,
        )

        query = str(arguments.get("query") or "").strip()
        mode = str(arguments.get("research_mode") or "standard")
        if mode not in ("quick", "standard", "deep"):
            mode = "standard"
        source = str(arguments.get("search_source") or "hybrid")
        if source not in ("internal", "external", "hybrid"):
            source = "hybrid"
        style = str(arguments.get("report_style") or "default")
        if style not in ("academic", "popular_science", "news", "default"):
            style = "default"

        return ResearchRequest(
            query=query,
            research_mode=mode,
            search_source=source,
            report_style=style,
            auto_accepted_plan=True,
        )

    async def _emit_progress(self, event_sink: Any, data: dict[str, Any]) -> None:
        """旁路推送进度事件（event_sink 缺失静默跳过——进度是增强不是依赖）。"""
        if event_sink is None:
            return
        try:
            await event_sink({
                "type": RESEARCH_PROGRESS_EVENT,
                "data": {
                    "status": data.get("status", ""),
                    "current_step": data.get("current_step", ""),
                    "progress_percent": data.get("progress_percent", 0),
                    "completed_tasks": data.get("completed_tasks", 0),
                    "total_tasks": data.get("total_tasks", 0),
                },
            })
        except Exception as e:
            # 客户端断开（WS 已 close）后长研究每条进度都会走到这里，debug 降噪
            logger.debug("研究进度事件推送失败（前端可能已断开）", error=str(e))

    async def _emit_plan(self, event_sink: Any, data: dict[str, Any]) -> None:
        """旁路推送计划事件（auto-approve 模式仅展示用途）。"""
        if event_sink is None:
            return
        try:
            await event_sink({
                "type": RESEARCH_PROGRESS_EVENT,
                "data": {
                    "status": "plan",
                    "plan": data.get("plan"),
                    "current_step": "研究计划已生成",
                    "progress_percent": 15,
                },
            })
        except Exception as e:
            logger.warning("研究计划事件推送失败", error=str(e))

    def get_system_prompt_fragment(self) -> str:
        """返回深度研究的使用指导（何时用/何时不用/耗时预期）。"""
        return (
            "## Deep Research\n"
            "The `research` tool runs a full multi-round investigation: planning, "
            "iterative search across internal KBs and the web, then a synthesized "
            "cited report. It takes several minutes.\n"
            "- Use it when the user asks for in-depth research, surveys, comparisons, "
            "or comprehensive analysis of a complex topic\n"
            "- Do NOT use it for simple questions — prefer direct answers, "
            "knowledge_search, or web_search\n"
            "- Before calling it, briefly tell the user research is starting and may "
            "take a few minutes\n"
            "- After receiving the report, summarize key findings and cite sources "
            "rather than repeating the full text"
        )
