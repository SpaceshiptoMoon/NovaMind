"""
可插拔的检索前查询改写组件（Query Rewriting）

支持 4 种改写策略，一次选择一个。
通过 session_config.kb_bindings.query_rewriting 配置。

提示词统一托管在中央注册表（shared.prompts），见 qa_prompts.py 的
qa_rw_completion / qa_rw_synonym / qa_rw_decompose / qa_rw_hyde。
"""
import re
from enum import Enum
from typing import Optional, List
from dataclasses import dataclass, field

from novamind.shared.ai_models.base_model import BaseLLM
from novamind.shared.prompts.templates import PromptManager, PromptTemplate


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
        prompt = PromptManager.format_prompt(
            PromptTemplate.QA_RW_COMPLETION.value, history=formatted, query=query
        )
        rewritten = await self._call_llm(prompt)
        return RewriteResult(
            queries=[rewritten] if rewritten else [query],
            strategy="completion",
            original_query=query,
            degraded=not rewritten,
        )

    async def _synonym(self, query: str) -> RewriteResult:
        prompt = PromptManager.format_prompt(PromptTemplate.QA_RW_SYNONYM.value, query=query)
        rewritten = await self._call_llm(prompt)
        return RewriteResult(
            queries=[rewritten] if rewritten else [query],
            strategy="synonym",
            original_query=query,
            degraded=not rewritten,
        )

    async def _decompose(self, query: str) -> RewriteResult:
        prompt = PromptManager.format_prompt(PromptTemplate.QA_RW_DECOMPOSE.value, query=query)
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
        prompt = PromptManager.format_prompt(PromptTemplate.QA_RW_HYDE.value, query=query)
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
            from novamind.core.middleware.structured_logging import get_logger
            get_logger(__name__).warning("QueryRewriter LLM 调用失败", error=str(e))
            return None
