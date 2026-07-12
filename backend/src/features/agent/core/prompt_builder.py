"""
分层系统提示词组装器

按层组装 Agent 系统提示词：
  Layer 1: 基础身份（agent.system_prompt）    — 优先级 5（最高）
  Layer 2: 已启用工具的行为引导（条件注入）      — 优先级 4
  Layer 3: 技能广场 Markdown 指令              — 优先级 2
  Layer 4: 模型适配规则（按模型名条件注入）     — 优先级 1（最低）
  Layer 5: 长期记忆冻结快照                    — 优先级 3

支持 Token 预算保护：超限时按优先级从低到高丢弃层。
"""
from typing import List, Optional, Tuple

from novamind.features.agent.core.tool.registry import ToolRegistry
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# 模型名关键词 → 适配提示
_MODEL_ADAPTATION: List[Tuple[Tuple[str, ...], str]] = [
    (
        ("gpt", "o1", "o3", "o4"),
        (
            "## Execution Discipline\n\n"
            "<tool_persistence>\n"
            "- Use tools whenever they improve correctness, completeness, or grounding.\n"
            "- Do not stop early when another tool call would materially improve the result.\n"
            "- If a tool returns empty or partial results, retry with a different query before giving up.\n"
            "- Keep calling tools until: (1) the task is complete, AND (2) you have verified the result.\n"
            "</tool_persistence>\n\n"
            "<mandatory_tool_use>\n"
            "NEVER answer these from memory or mental computation -- ALWAYS use a tool:\n"
            "- Arithmetic, math, calculations → use code_execution\n"
            "- Hashes, encodings, checksums → use code_execution\n"
            "- Current time, date, timezone → use available tools\n"
            "- System state: OS, CPU, memory, disk, ports → use available tools\n"
            "- File contents, sizes, line counts → use available tools\n"
            "- Git history, branches, diffs → use available tools\n"
            "- Current facts (weather, news, versions) → use web_search\n"
            "Your memory describes the USER, not the system you are running on.\n"
            "</mandatory_tool_use>\n\n"
            "<act_dont_ask>\n"
            "When a question has an obvious default interpretation, act on it immediately "
            "instead of asking for clarification. Examples:\n"
            "- 'Is port 443 open?' → check THIS machine (don't ask 'open where?')\n"
            "- 'What time is it?' → run a command (don't guess)\n"
            "Only ask for clarification when ambiguity genuinely changes which tool you would call.\n"
            "</act_dont_ask>\n\n"
            "<prerequisite_checks>\n"
            "- Before taking an action, check whether prerequisite discovery or context-gathering steps are needed.\n"
            "- Do not skip prerequisite steps just because the final action seems obvious.\n"
            "- If a task depends on output from a prior step, resolve that dependency first.\n"
            "</prerequisite_checks>\n\n"
            "<verification>\n"
            "Before responding, verify:\n"
            "- Correctness: does the output satisfy every stated requirement?\n"
            "- Grounding: are factual claims backed by tool outputs or provided context?\n"
            "- Formatting: does the output match the requested format?\n"
            "</verification>\n\n"
            "<missing_context>\n"
            "- If required context is missing, do NOT guess or hallucinate an answer.\n"
            "- Use the appropriate lookup tool when missing information is retrievable.\n"
            "- Ask a clarifying question only when the information cannot be retrieved by tools.\n"
            "- If you must proceed with incomplete information, label assumptions explicitly.\n"
            "</missing_context>"
        ),
    ),
    (
        ("gemini", "gemma"),
        (
            "## Execution Discipline\n"
            "- Always construct and use absolute file paths for all file system operations.\n"
            "- Use tools to check file contents and project structure before making changes. Never guess.\n"
            "- Never assume a library is available — check dependencies before importing.\n"
            "- Keep explanatory text brief — a few sentences, not paragraphs. Focus on actions and results.\n"
            "- When you need to perform multiple independent operations, make all tool calls in a single response.\n"
            "- Use non-interactive flags (e.g. -y, --yes) to prevent CLI tools from hanging.\n"
            "- Work autonomously until the task is fully resolved. Do not stop with a plan — execute it.\n"
        ),
    ),
]

# 通用工具使用纪律（所有模型默认注入）
_DEFAULT_TOOL_DISCIPLINE = (
    "## Tool-Use Enforcement\n"
    "You MUST use your tools to take action -- do not describe what you would do or plan to do "
    "without actually doing it. When you say you will perform an action, you MUST immediately "
    "make the corresponding tool call in the same response. Never end your turn with a promise "
    "of future action -- execute it now.\n"
    "Keep working until the task is actually complete. Do not stop with a summary of what you "
    "plan to do next time. If you have tools available that can accomplish the task, use them "
    "instead of telling the user what you would do.\n"
    "Every response should either (a) contain tool calls that make progress, or (b) deliver a "
    "final result. Responses that only describe intentions without acting are not acceptable.\n"
    "If a tool call fails, analyze the error and retry with a different approach. Do not repeat the same call."
)


class SystemPromptBuilder:
    """分层组装 Agent 系统提示词"""

    def __init__(self, tool_registry: ToolRegistry):
        self._registry = tool_registry

    async def build(
        self,
        base_prompt: str,
        enabled_tools: List[str],
        skill_fragments: List[str],
        frozen_memory: str = "",
        model_name: str = "",
        max_prompt_tokens: Optional[int] = None,
    ) -> str:
        """按层组装完整系统提示（含 Token 预算保护）"""
        # 收集各层内容
        tool_guidance = self._collect_tool_guidance(enabled_tools)
        model_hints = self._build_model_adaptation(model_name)
        skills_text = "\n\n".join(skill_fragments) if skill_fragments else ""

        # 按优先级排序（priority 越高越不能丢）：identity > tool > memory > skills > adaptation
        named_layers = [
            (model_hints, "model_adaptation", 1),
            (skills_text, "skills", 2),
            (frozen_memory, "frozen_memory", 3),
            (tool_guidance, "tool_guidance", 4),
            (base_prompt, "identity", 5),
        ]
        # 过滤空层
        active = [(c, n, p) for c, n, p in named_layers if c]
        # 按 priority 降序排列（高优先级在前面）
        active.sort(key=lambda x: x[2], reverse=True)

        result = "\n\n---\n\n".join(c for c, _, _ in active)

        # Token 预算保护
        if max_prompt_tokens and result:
            from novamind.features.agent.core.memory.token_budget import TokenBudget
            budget = TokenBudget(model_name or "gpt-4")
            threshold = int(max_prompt_tokens * 0.20)

            while budget.count_text_tokens(result) > threshold and len(active) > 1:
                dropped = active.pop()  # 弹出最低优先级（末尾）
                logger.warning(
                    "系统提示超出预算，丢弃低优先级层",
                    layer=dropped[1],
                    threshold=threshold,
                )
                result = "\n\n---\n\n".join(c for c, _, _ in active)

        return result

    def _collect_tool_guidance(self, enabled_tools: List[str]) -> str:
        """收集已启用工具的 system_prompt_fragment"""
        fragments: List[str] = []
        for tool_name in enabled_tools:
            if tool_name.startswith("skill__"):
                continue
            tool = self._registry.get_tool(tool_name)
            if tool:
                fragment = tool.get_system_prompt_fragment()
                if fragment:
                    fragments.append(fragment)
        return "\n\n".join(fragments)

    @staticmethod
    def _build_model_adaptation(model_name: str) -> str:
        """根据模型名返回适配提示"""
        if not model_name:
            return ""
        model_lower = model_name.lower()
        for keywords, hint in _MODEL_ADAPTATION:
            if any(kw in model_lower for kw in keywords):
                return hint
        return _DEFAULT_TOOL_DISCIPLINE
