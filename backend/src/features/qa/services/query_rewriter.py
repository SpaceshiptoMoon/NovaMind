"""
可插拔的检索前查询改写组件（Query Rewriting）

支持 4 种改写策略，一次选择一个。
通过 session_config.kb_bindings.query_rewriting 配置。
"""
import re
from enum import Enum
from typing import Optional, List
from dataclasses import dataclass, field

from src.shared.ai_models.base_model import BaseLLM


class RewriteStrategy(str, Enum):
    """改写策略枚举"""
    NONE = "none"
    COMPLETION = "completion"  # 基于对话历史补全
    SYNONYM = "synonym"        # 同义改写
    DECOMPOSE = "decompose"    # 子问题分解
    HYDE = "hyde"              # 假设文档检索


@dataclass
class RewriteResult:
    """改写结果"""
    queries: List[str] = field(default_factory=list)  # 检索用的 query 列表
    strategy: str = "none"
    original_query: str = ""
    degraded: bool = False  # True=LLM 改写失败/不可用，已回退到原 query（透传到 trace 告知用户）


# ==================== Prompt 模板 ====================

_PROMPT_COMPLETION = """你是一个对话助手。用户的问题是针对一段对话历史提出的，其中可能使用了代词或省略表达。
请根据对话历史，将用户的问题补全为一个完整的、无需上下文就能理解的独立问题。
只输出补全后的问题，不要任何解释。

对话历史：
{history}

用户问题：{query}

补全后的问题："""

_PROMPT_SYNONYM = """你是一个检索优化专家。请将用户的问题改写为更适合知识库检索的形式。
要求：
- 保留核心意图
- 使用更精确的关键词
- 去除口语化表达
- 直接输出改写结果，不要解释

用户问题：{query}

改写后的检索查询："""

_PROMPT_DECOMPOSE = """你是一个问题分析专家。用户的问题是复合型的，包含多个子问题。
请将问题拆解为多个独立的原子子问题，每个子问题只问一件事。
每个子问题应能独立检索知识库。
按从基础到进阶的顺序排列。

输出格式：每行一个子问题，不要编号，不要解释。

用户问题：{query}

子问题："""

_PROMPT_HYDE = """你是一个知识库专家。用户提出了一个问题。
请根据你的知识，生成一段假设性的文档片段，该文档应该包含回答该问题所需的关键信息。
这段文档将用于检索相似的知识库文档，因此应该使用事实性、陈述性语言。

用户问题：{query}

假设文档："""


# ==================== DECOMPOSE 子查询清洗（O-RAG6） ====================

# 仅当「数字+句点/右括号」或项目符号时才视为列表前缀并剥离；
# 不匹配裸数字，避免误伤「2024年…」「1+1」这类合法子查询。
_SUBQ_PREFIX_RE = re.compile(r"^\s*(?:\d+[\.\)]|[-•*·])\s*")
_SUBQ_HEADER_RE = re.compile(r"^(?:子问题|子问题列表|子问题分解|分解|以下|如下|结果)[：:]")


def _clean_sub_query(line: str) -> Optional[str]:
    """清洗 DECOMPOSE 单行：去列表编号/项目符号前缀，过滤标题/说明行；返回 None 表示该行应丢弃。"""
    line = line.strip()
    if not line:
        return None
    line = _SUBQ_PREFIX_RE.sub("", line).strip()
    if not line or _SUBQ_HEADER_RE.match(line):
        return None
    return line


class QueryRewriter:
    """可插拔的检索前查询改写组件"""

    def __init__(self, llm_client: BaseLLM):
        self._llm = llm_client

    async def rewrite(
        self, query: str, strategy: RewriteStrategy,
        history: Optional[List[dict]] = None,
    ) -> RewriteResult:
        """按指定策略改写查询"""
        if strategy == RewriteStrategy.COMPLETION:
            return await self._completion(query, history or [])
        elif strategy == RewriteStrategy.SYNONYM:
            return await self._synonym(query)
        elif strategy == RewriteStrategy.DECOMPOSE:
            return await self._decompose(query)
        elif strategy == RewriteStrategy.HYDE:
            return await self._hyde(query)
        else:
            return RewriteResult(queries=[query], strategy=strategy.value, original_query=query)

    async def _completion(self, query: str, history: List[dict]) -> RewriteResult:
        # 只取最近 3 轮对话作为上下文
        recent = history[-6:] if len(history) > 6 else history
        formatted = "\n".join(
            f"{'User' if m.get('role') == 'user' else 'Assistant'}: {m.get('content', '')}"
            for m in recent
        )
        prompt = _PROMPT_COMPLETION.format(history=formatted, query=query)
        rewritten = await self._call_llm(prompt)
        return RewriteResult(
            queries=[rewritten] if rewritten else [query],
            strategy="completion",
            original_query=query,
            degraded=not rewritten,
        )

    async def _synonym(self, query: str) -> RewriteResult:
        prompt = _PROMPT_SYNONYM.format(query=query)
        rewritten = await self._call_llm(prompt)
        return RewriteResult(
            queries=[rewritten] if rewritten else [query],
            strategy="synonym",
            original_query=query,
            degraded=not rewritten,
        )

    async def _decompose(self, query: str) -> RewriteResult:
        prompt = _PROMPT_DECOMPOSE.format(query=query)
        result = await self._call_llm(prompt)
        if result:
            # O-RAG6：清洗编号/项目符号前缀与标题行，避免 "1. xxx"/"- xxx"/"子问题：xxx" 被当作子查询
            sub_queries = [q for q in (_clean_sub_query(line) for line in result.split("\n")) if q]
            degraded = not sub_queries  # 清洗后无有效子问题（LLM 返回纯标题/空行），无法分解
            if degraded:
                sub_queries = [query]
        else:
            sub_queries = [query]
            degraded = True  # LLM 调用失败，回退到原 query
        return RewriteResult(
            queries=sub_queries,
            strategy="decompose",
            original_query=query,
            degraded=degraded,
        )

    async def _hyde(self, query: str) -> RewriteResult:
        prompt = _PROMPT_HYDE.format(query=query)
        hypothetical = await self._call_llm(prompt)
        return RewriteResult(
            queries=[hypothetical] if hypothetical else [query],
            strategy="hyde",
            original_query=query,
            degraded=not hypothetical,
        )

    async def _call_llm(self, prompt: str) -> Optional[str]:
        """调 LLM 生成文本，失败时返回 None（fallback 到原 query）"""
        try:
            return await self._llm.generate_text(
                prompt=prompt, max_tokens=512, temperature=0.3,
            )
        except Exception as e:
            from src.core.middleware.structured_logging import get_logger
            get_logger(__name__).warning("QueryRewriter LLM 调用失败", error=str(e))
            return None
