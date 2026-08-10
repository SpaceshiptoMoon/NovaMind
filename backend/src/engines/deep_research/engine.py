"""
Deep Research 核心引擎：可复用的研究机制（查询分析/任务分解/迭代检索/综合）。

本模块为纯逻辑层，不得 import ``novamind.features.*`` / ``novamind.setting.*`` /
ORM 模型 / ``core.database``。LLM 客户端、prompt 提供者、检索端口、日志均按调用注入
（AgentEngine 风格）；引擎类无状态。

A-1 阶段：仅落纯模块函数（检索结果清洗/外部搜索决策/充分性/去重/关键来源/上下文格式化）
+ 常量 + prompt key 常量。LLM 方法（analyze_query/decompose_tasks/synthesize_report[_stream]）
与迭代检索循环（``search``）在 A-2/A-3 阶段迁入 ``DeepResearchEngine`` 类。
"""
from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from novamind.shared.ai_models.llm import BaseLLM
from novamind.shared.logging import Logger
from novamind.engines.ports import PromptProvider
from novamind.engines.deep_research.types import SearchSource


# 结果充分性阈值常量
SUFFICIENT_RESULT_COUNT = 10  # 结果数量阈值
MAX_ITERATION_THRESHOLD = 3  # 最大迭代阈值

# Prompt key 常量（防 key 漂移；模板留 feature 侧 deep_research_prompts.py，经 PromptProvider 解析）
KEY_ANALYZE_QUERY = "research_analyze_query"
KEY_DECOMPOSE_TASKS = "research_decompose_tasks"
KEY_SYNTHESIZE_REPORT = "research_synthesize_report"
KEY_SYNTHESIZE_REPORT_STREAM = "research_synthesize_report_stream"


def _sanitize_search_field(text: str) -> str:
    """清理搜索结果字段中的特殊标记，空值时返回空字符串而不抛异常。"""
    if not text or not text.strip():
        return ""
    markers = ["<|im_start|>", "<|im_end|>", "", "[INST]", "[/INST]", "<<SYS>>", "<</SYS>>"]
    sanitized = text
    for marker in markers:
        sanitized = sanitized.replace(marker, "")
    return sanitized.strip()


def should_use_external_search(search_source: SearchSource, iteration: int) -> bool:
    """动态决策是否使用外部搜索。

    - external：始终外部
    - internal：始终内部
    - hybrid：首次迭代内部优先，后续交替（奇数迭代外部）
    """
    if search_source == SearchSource.EXTERNAL:
        return True
    if search_source == SearchSource.INTERNAL:
        return False
    # hybrid
    if iteration == 0:
        return False
    return iteration % 2 == 1


def is_sufficient_results(results: List[Any], iteration: int) -> bool:
    """检查结果是否足够（达到数量阈值，或已有结果且达到最大迭代阈值）。"""
    if len(results) >= SUFFICIENT_RESULT_COUNT:
        return True
    if len(results) > 0 and iteration >= MAX_ITERATION_THRESHOLD:
        return True
    return False


def deduplicate_results(all_results: List[Any], new_results: List[Any]) -> None:
    """基于 URL、标题或 chunk_id 过滤重复结果，将去重后的新结果追加到 all_results（原地去重）。"""
    existing_urls = {r.get("url") for r in all_results if r.get("url")}
    existing_titles = {r.get("title") for r in all_results if r.get("title")}
    existing_chunk_ids = {r.get("chunk_id") for r in all_results if r.get("chunk_id")}
    for r in new_results:
        r_url = r.get("url")
        r_title = r.get("title")
        r_chunk_id = r.get("chunk_id")
        if r_url and r_url in existing_urls:
            continue
        if r_title and r_title in existing_titles:
            continue
        if r_chunk_id and r_chunk_id in existing_chunk_ids:
            continue
        all_results.append(r)
        if r_url:
            existing_urls.add(r_url)
        if r_title:
            existing_titles.add(r_title)
        if r_chunk_id:
            existing_chunk_ids.add(r_chunk_id)


def extract_key_sources(results: List[Any]) -> List[str]:
    """提取关键来源（前 10 条去重后取前 5）。"""
    sources: List[str] = []
    seen: set[str] = set()

    for r in results[:10]:
        source = r.get("url") or f"文档: {r.get('document_name', r.get('document_id', '未知'))}"
        if source not in seen:
            sources.append(source)
            seen.add(source)

    return sources[:5]


def format_search_context(results: List[Any]) -> str:
    """格式化检索结果为上下文（清理内容防止 prompt 注入）。"""
    context_parts: List[str] = []

    for i, r in enumerate(results[:15], start=1):
        raw_source = r.get("url") or f"文档 {r.get('document_name', r.get('document_id', '未知'))}"
        source = _sanitize_search_field(raw_source) or f"来源 {i}"
        raw_content = r.get("content", "")
        content = _sanitize_search_field(raw_content)
        if content:
            context_parts.append(f"【来源 {i}】({source})\n{content}\n")

    return "\n".join(context_parts)


__all__ = [
    "SUFFICIENT_RESULT_COUNT",
    "MAX_ITERATION_THRESHOLD",
    "KEY_ANALYZE_QUERY",
    "KEY_DECOMPOSE_TASKS",
    "KEY_SYNTHESIZE_REPORT",
    "KEY_SYNTHESIZE_REPORT_STREAM",
    "should_use_external_search",
    "is_sufficient_results",
    "deduplicate_results",
    "extract_key_sources",
    "format_search_context",
    "DeepResearchEngine",
]


class DeepResearchEngine:
    """深度研究核心引擎（无状态）：可复用的研究机制。

    LLM 客户端、prompt 提供者按调用注入（AgentEngine 风格）；日志经构造器注入。
    不持业务上下文 / ORM / 租户 / 配置；业务编排（会话创建/持久化/SSE/多租户）留 feature。

    输入约定：``analyze_query`` / ``decompose_tasks`` / ``synthesize_report[_stream]`` 接收
    **feature 入口已 sanitize** 的 query/topic（feature ``_sanitize_user_input`` 抛 feature 异常），
    引擎不重复 sanitize，只负责 LLM 调用与结果解析。
    """

    def __init__(self, *, logger: Optional[Logger] = None):
        self._logger = logger

    async def analyze_query(
        self,
        llm_client: BaseLLM,
        prompt_provider: PromptProvider,
        query: str,
    ) -> str:
        """分析查询，提取研究主题（接已 sanitize 的 query）。"""
        prompt = prompt_provider.format(KEY_ANALYZE_QUERY, query=query)
        result = await llm_client.generate_text(
            prompt=prompt,
            max_tokens=100,
            temperature=0.3,
            enable_thinking=False,
        )
        return result.strip()

    async def decompose_tasks(
        self,
        llm_client: BaseLLM,
        prompt_provider: PromptProvider,
        query: str,
        topic: str,
        depth: int,
    ) -> List[Dict[str, Any]]:
        """分解研究任务（接已 sanitize 的 query/topic；``depth`` 为整数，不接 ResearchMode）。

        LLM 返回 JSON 解析失败时降级为默认任务（按 depth 生成），并经注入 logger 告警。
        """
        prompt = prompt_provider.format(
            KEY_DECOMPOSE_TASKS,
            research_topic=topic,
            query=query,
            depth=depth,
        )
        result = await llm_client.generate_text(
            prompt=prompt,
            max_tokens=1000,
            temperature=0.5,
            enable_thinking=False,
        )
        try:
            json_pattern = r"\[[\s\S]*\]"
            matches = re.findall(json_pattern, result)
            if not matches:
                raise json.JSONDecodeError("未找到 JSON 数组", result, 0)
            json_match = matches[0]
            tasks = json.loads(json_match)
            validated_tasks: List[Dict[str, Any]] = []
            for i, task in enumerate(tasks[:depth]):
                validated_tasks.append({
                    "task_id": task.get("task_id") or task.get("id") or f"task_{i+1}",
                    "description": task.get("description", f"研究 {topic} 的第 {i+1} 个方面"),
                    "priority": task.get("priority", i + 1),
                })
            return validated_tasks
        except (json.JSONDecodeError, ValueError) as e:
            if self._logger is not None:
                self._logger.warning(
                    "LLM 任务分解 JSON 解析失败，使用默认任务", error=str(e)
                )
            return [
                {
                    "task_id": f"task_{i+1}",
                    "description": f"研究 {topic} 的第 {i+1} 个方面",
                    "priority": i + 1,
                }
                for i in range(depth)
            ]

    async def synthesize_report(
        self,
        llm_client: BaseLLM,
        prompt_provider: PromptProvider,
        *,
        query: str,
        research_topic: str,
        results: List[Dict[str, Any]],
        key_sources: List[str],
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> tuple:
        """综合信息生成报告（非流式）。``results`` 经 ``format_search_context`` 格式化为上下文。"""
        context = format_search_context(results)
        key_sources_str = (
            chr(10).join(f"- {s}" for s in key_sources) if key_sources else "无外部来源"
        )
        prompt = prompt_provider.format(
            KEY_SYNTHESIZE_REPORT,
            query=query,
            research_topic=research_topic,
            context=context,
            key_sources=key_sources_str,
        )
        report = await llm_client.generate_text(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            enable_thinking=False,
        )
        metadata = {
            "report_length": len(report),
            "sources_count": len(key_sources),
        }
        return report, metadata

    async def synthesize_report_stream(
        self,
        llm_client: BaseLLM,
        prompt_provider: PromptProvider,
        *,
        query: str,
        research_topic: str,
        context: str,
        key_sources: List[str],
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> AsyncIterator[str]:
        """综合信息生成报告（流式，yield 原始 chunk，不含 heartbeat）。

        与非流式不同，接收 feature 预格式化的 ``context``（stream 路径在调用前已格式化）。
        """
        key_sources_str = (
            chr(10).join(f"- {s}" for s in key_sources) if key_sources else "无外部来源"
        )
        prompt = prompt_provider.format(
            KEY_SYNTHESIZE_REPORT_STREAM,
            query=query,
            research_topic=research_topic,
            context=context,
            key_sources=key_sources_str,
        )
        async for chunk in llm_client.generate_text_stream(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            enable_thinking=False,
        ):
            yield chunk