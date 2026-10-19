from novamind.engines.agent.tool.registry import ToolRegistry
from novamind.shared.logging import get_logger
from novamind.shared.prompts.prompt_manager import PromptManager

logger = get_logger(__name__)

# 模型名关键词 → 适配模板键（模板正文注册于 engines/agent/prompts.py）
_MODEL_ADAPTATION: list[tuple[tuple[str, ...], str]] = [
    (("gpt", "o1", "o3", "o4"), "agent_engine_model_adaptation_gpt"),
    (("gemini", "gemma"), "agent_engine_model_adaptation_gemini"),
]

# 通用工具使用纪律模板键（所有模型默认注入）
_DEFAULT_TOOL_DISCIPLINE_KEY = "agent_engine_tool_discipline_default"


# 结构化标签约定（恒定注入，最高优先级，不参与预算丢弃）：
# 消息流中的系统注入一律包裹在 <system-*> 标签内，用户内容已转义 '<' 无法伪造
# 标签。这段约定是模型正确理解 <system-compaction>/<plan-context> 等注入块的
# 钥匙——丢了它，标签约定的整条防线失效，故优先级高于 identity 层。
# 调用期取用：模块级读注册表会与测试 collection 期的 import 序耦合（注册在
# conftest fixture，晚于部分模块 import）。
_TAG_CONVENTION_KEY = "agent_engine_tag_convention"


def _tag_convention() -> str:
    """取 <system-*> 标签约定层文本（调用期，注册表已就绪）。"""
    return PromptManager.get_template(_TAG_CONVENTION_KEY)


class SystemPromptBuilder:
    """分层组装 Agent 系统提示词"""

    def __init__(self, tool_registry: ToolRegistry):
        """注入工具注册表，用于收集已启用工具的系统提示片段。"""
        self._registry = tool_registry

    async def build(
        self,
        base_prompt: str,
        enabled_tools: list[str],
        skill_fragments: list[str],
        frozen_memory: str = "",
        model_name: str = "",
        max_prompt_tokens: int | None = None,
    ) -> str:
        """按层组装完整系统提示（含 Token 预算保护）。

        Args:
            base_prompt: 基础身份层（最高优先级，不丢弃）。
            enabled_tools: 已启用工具名列表（skill__ 前缀跳过）。
            skill_fragments: 技能指令片段列表。
            frozen_memory: 冻结记忆快照文本。
            model_name: 模型名（决定适配层内容与 token 计数口径）。
            max_prompt_tokens: 提示词预算，超限按优先级从低到高丢层；None 不限。

        Returns:
            组装后的系统提示文本（各层以分隔线连接）。
        """
        # 收集各层内容
        tool_guidance = self._collect_tool_guidance(enabled_tools)
        model_hints = self._build_model_adaptation(model_name)
        skills_text = "\n\n".join(skill_fragments) if skill_fragments else ""

        # 按优先级排序（priority 越高越不能丢）：tag_convention > identity > tool > memory > skills > adaptation
        # 标签约定恒定置顶：它是理解 <system-*> 注入块的钥匙，不参与预算丢弃
        named_layers = [
            (_tag_convention(), "tag_convention", 10),
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

        # Token 预算保护（tag_convention priority=10 恒在 active 首位，len(active)>1
        # 的弹栈条件保证它永不弹出；仅当只剩它一条时 while 条件天然不满足）
        if max_prompt_tokens and result:
            from novamind.engines.agent.memory.token_budget import TokenBudget
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

    def _collect_tool_guidance(self, enabled_tools: list[str]) -> str:
        """收集已启用工具的 system_prompt_fragment"""
        fragments: list[str] = []
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
        for keywords, template_key in _MODEL_ADAPTATION:
            if any(kw in model_lower for kw in keywords):
                return PromptManager.get_template(template_key)
        return PromptManager.get_template(_DEFAULT_TOOL_DISCIPLINE_KEY)
