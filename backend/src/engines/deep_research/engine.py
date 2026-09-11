"""
Deep Research 核心引擎：可复用的研究机制（查询分析/任务分解/迭代检索/综合）。

本模块为纯逻辑层，不得 import ``novamind.features.*`` / ``novamind.setting.*`` /
ORM 模型 / ``core.database``。LLM 客户端、prompt 提供者、检索数据源、日志均按调用注入
（AgentEngine 风格）；引擎类无状态。

- 纯模块函数：检索结果清洗/充分性/去重/关键来源/上下文格式化/观察摘要/
  query 决策解析/计划解析 + 常量 + prompt key。
- ``DeepResearchEngine`` 类：``analyze_query``/``analyze_plan``（deer-flow planner
  对齐）/``synthesize_report[_stream]``（按调用接 llm_client + prompt_provider）+
  ``background_investigation``（规划前单轮背景检索）+ ``search``（迭代检索循环，
  AsyncIterator[SearchEvent]，按调用接 ``sources: List[SearchSourceBinding]``——
  可插拔数据源，每轮迭代查全部启用源；llm_client/prompt_provider 可选注入——
  注入即启用 deer-flow 对齐的观察驱动模式；循环内按 step_type 路由
  research/processing 步骤）。
"""
from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from novamind.shared.ai_models.llm import BaseLLM
from novamind.shared.logging import Logger
from novamind.engines.ports import PromptProvider
from novamind.engines.deep_research.sources import SearchSourceBinding
from novamind.engines.deep_research.types import (
    EngineResearchParams,
    IterationProgress,
    PlanStep,
    ResearchPlan,
    SearchComplete,
    SearchEvent,
    SearchSource,
    SourceType,
    StepType,
    TaskFailed,
    TaskFinding,
    TaskStarted,
)


# 结果充分性阈值常量
SUFFICIENT_RESULT_COUNT = 10  # 结果数量阈值
MAX_ITERATION_THRESHOLD = 3  # 最大迭代阈值

# 观察驱动模式（deer-flow 对齐）：喂给 LLM 的观察条数与单条内容截断长度
OBSERVATION_FEED_LIMIT = 8
OBSERVATION_SNIPPET_CHARS = 200

# 背景调查（deer-flow background_investigation 对齐）：单轮检索上限
BACKGROUND_INVESTIGATION_MAX_RESULTS = 8
BACKGROUND_RESULT_SNIPPET_CHARS = 500

# Plan 执行结果回填截断长度（持久化前）
EXECUTION_RES_MAX_CHARS = 1000

# Prompt key 常量（防 key 漂移；模板留 feature 侧 deep_research_prompts.py，经 PromptProvider 解析）
KEY_ANALYZE_QUERY = "research_analyze_query"
KEY_PLAN = "research_plan"
KEY_PROCESSING_STEP = "research_processing_step"
KEY_SYNTHESIZE_REPORT = "research_synthesize_report"
KEY_SYNTHESIZE_REPORT_STREAM = "research_synthesize_report_stream"
KEY_GENERATE_QUERY = "research_generate_query"
KEY_TASK_FINDING = "research_task_finding"


def _sanitize_search_field(text: str) -> str:
    """清理搜索结果字段中的特殊标记，空值时返回空字符串而不抛异常。"""
    if not text or not text.strip():
        return ""
    markers = ["<|im_start|>", "<|im_end|>", "", "[INST]", "[/INST]", "<<SYS>>", "<</SYS>>"]
    sanitized = text
    for marker in markers:
        sanitized = sanitized.replace(marker, "")
    return sanitized.strip()


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


def extract_citations(results: List[Any]) -> List[Dict[str, str]]:
    """提取全量引用列表（deer-flow Key Citations 对齐，不截断）。

    每条 {title, url, source_type}：url 为空（内部文档）时以 document_name 兜底
    填 url 字段；按 (url, title) 去重。
    """
    citations: List[Dict[str, str]] = []
    seen: set = set()
    for r in results:
        title = str(r.get("title") or r.get("document_name") or "").strip()
        url = str(r.get("url") or "").strip()
        if not url:
            url = str(r.get("document_name") or "").strip()
        source_type = str(r.get("source_type") or "").strip()
        if not title and not url:
            continue
        key = (url, title)
        if key in seen:
            continue
        seen.add(key)
        citations.append({"title": title, "url": url, "source_type": source_type})
    return citations


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


def summarize_observations_for_llm(results: List[Any]) -> str:
    """将本任务已得检索结果压缩为观察摘要（喂 query 生成 LLM，防 token 爆炸）。

    只取前 OBSERVATION_FEED_LIMIT 条，每条 content 截 OBSERVATION_SNIPPET_CHARS 字符。
    """
    lines: List[str] = []
    for i, r in enumerate(results[:OBSERVATION_FEED_LIMIT], start=1):
        title = _sanitize_search_field(str(r.get("title") or r.get("document_name") or ""))[:80]
        content = _sanitize_search_field(str(r.get("content", "")))[:OBSERVATION_SNIPPET_CHARS]
        source = r.get("url") or r.get("document_name") or ""
        label = f"观察{i}: " + (f"[{title}] " if title else "")
        if source:
            label += f"({source}) "
        lines.append(label + content)
    return "\n".join(lines) if lines else "（暂无观察结果）"


def parse_query_decision(raw: str) -> tuple:
    """解析 query 生成 LLM 的 JSON 决策输出 → (sufficient, next_query, reason)。

    容错降级：非 JSON / 缺字段 / 字段类型错 → (False, "", reason 含错误说明)，
    调用方以空 next_query 降级为固定 query 继续。
    """
    if not raw or not raw.strip():
        return False, "", "LLM 返回为空"
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # 容忍 LLM 把 JSON 包在代码块或前后文字里：抓第一个 {...}
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return False, "", "LLM 返回不含 JSON"
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return False, "", "LLM 返回 JSON 解析失败"
    if not isinstance(data, dict):
        return False, "", "LLM 返回非 JSON 对象"
    sufficient = bool(data.get("sufficient", False))
    next_query = data.get("next_query")
    if not isinstance(next_query, str):
        next_query = ""
    next_query = _sanitize_search_field(next_query)
    reason = data.get("reason")
    if not isinstance(reason, str):
        reason = ""
    return sufficient, next_query, reason


def _extract_json_block(raw: str):
    """从 LLM 输出中提取 JSON 对象/数组（容忍代码块包裹与前后杂文字）。"""
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass
    # 数组优先（decompose 兼容）再对象
    for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
        match = re.search(pattern, raw)
        if match:
            try:
                return json.loads(match.group(0))
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def parse_plan(raw: str, *, depth: int, topic: str, iteration: int) -> ResearchPlan:
    """解析 planner LLM 输出为 ResearchPlan（deer-flow Plan 对齐）。

    容错降级：非 JSON / 缺 steps / 类型错 → 默认计划（按 depth 生成全 research
    步骤，沿用 decompose_tasks 降级风格）。守卫：全 processing 计划强制首步转
    research（避免零检索纯空谈计划）。
    """
    data = _extract_json_block(raw)

    def _default_plan() -> ResearchPlan:
        return ResearchPlan(
            title=topic,
            thought="",
            has_enough_context=False,
            steps=[
                PlanStep(
                    step_id=f"step_{i + 1}",
                    title=f"{topic} 第 {i + 1} 方面",
                    description=f"研究 {topic} 的第 {i + 1} 个方面",
                    step_type=StepType.RESEARCH,
                    need_search=True,
                )
                for i in range(depth)
            ],
            iteration=iteration,
        )

    if not isinstance(data, dict):
        # 兼容旧 decompose 数组形状（[{task_id/description/priority}]）
        if isinstance(data, list) and data:
            data = {"steps": data}
        else:
            return _default_plan()

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        return _default_plan()

    steps: List[PlanStep] = []
    for i, s in enumerate(raw_steps[:depth]):
        if not isinstance(s, dict):
            continue
        # step_type 容错：非法值一律归 research
        raw_type = str(s.get("step_type", "research")).lower()
        step_type = StepType.PROCESSING if raw_type == "processing" else StepType.RESEARCH
        need_search = bool(s.get("need_search", True))
        steps.append(PlanStep(
            step_id=str(s.get("step_id") or s.get("task_id") or f"step_{len(steps) + 1}"),
            title=str(s.get("title", f"步骤 {len(steps) + 1}")),
            description=str(s.get("description", f"研究 {topic} 的第 {len(steps) + 1} 个方面")),
            step_type=step_type,
            need_search=need_search,
        ))

    # 全 processing 守卫：强制首步转 research（planner 滥用 processing 的防呆）
    if steps and all(s.step_type == StepType.PROCESSING or not s.need_search for s in steps):
        steps[0].step_type = StepType.RESEARCH
        steps[0].need_search = True

    has_enough = bool(data.get("has_enough_context", False))
    if not steps and not has_enough:
        # 无步骤且未判足够 → 降级默认计划；has_enough=true 时空 steps 合法
        # （planner 判定背景已足够，管线跳过检索直接 reporter）
        return _default_plan()
    return ResearchPlan(
        title=str(data.get("title", topic)),
        thought=str(data.get("thought", "")),
        has_enough_context=has_enough,
        steps=steps,
        iteration=iteration,
    )


__all__ = [
    "SUFFICIENT_RESULT_COUNT",
    "MAX_ITERATION_THRESHOLD",
    "OBSERVATION_FEED_LIMIT",
    "OBSERVATION_SNIPPET_CHARS",
    "BACKGROUND_INVESTIGATION_MAX_RESULTS",
    "BACKGROUND_RESULT_SNIPPET_CHARS",
    "EXECUTION_RES_MAX_CHARS",
    "KEY_ANALYZE_QUERY",
    "KEY_PLAN",
    "KEY_PROCESSING_STEP",
    "KEY_SYNTHESIZE_REPORT",
    "KEY_SYNTHESIZE_REPORT_STREAM",
    "KEY_GENERATE_QUERY",
    "KEY_TASK_FINDING",
    "should_use_external_search",
    "is_sufficient_results",
    "deduplicate_results",
    "extract_key_sources",
    "extract_citations",
    "format_search_context",
    "summarize_observations_for_llm",
    "parse_query_decision",
    "parse_plan",
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

    async def analyze_plan(
        self,
        llm_client: BaseLLM,
        prompt_provider: PromptProvider,
        *,
        query: str,
        topic: str,
        background_results: List[Dict[str, Any]],
        depth: int,
        iteration: int = 0,
        feedback: str = "",
    ) -> ResearchPlan:
        """生成结构化研究计划（deer-flow planner 对齐，替代 decompose_tasks）。

        输入背景调查结果与（重规划时的）用户反馈，输出
        ``ResearchPlan{title, thought, has_enough_context, steps[PlanStep]}``。
        解析失败降级默认计划（parse_plan 内部处理），不抛异常。
        """
        bg_block = (
            "\n".join(
                f"- [{r.get('title', '')}]({r.get('url', '') or r.get('document_name', '')}) "
                f"{str(r.get('content', ''))[:BACKGROUND_RESULT_SNIPPET_CHARS]}"
                for r in background_results[:BACKGROUND_INVESTIGATION_MAX_RESULTS]
            )
            if background_results
            else "（无背景调查结果）"
        )
        prompt = prompt_provider.format(
            KEY_PLAN,
            research_topic=topic,
            query=query,
            depth=depth,
            background_results=bg_block,
            feedback=feedback or "（无，首轮规划）",
            iteration=str(iteration),
        )
        raw = await llm_client.generate_text(
            prompt=prompt,
            max_tokens=2000,
            temperature=0.5,
            enable_thinking=False,
        )
        return parse_plan(raw, depth=depth, topic=topic, iteration=iteration)

    async def background_investigation(
        self,
        *,
        sources: List[SearchSourceBinding],
        query: str,
        params: EngineResearchParams,
        max_results: int = BACKGROUND_INVESTIGATION_MAX_RESULTS,
    ) -> List[Dict[str, Any]]:
        """规划前背景调查（deer-flow background_investigator 对齐）。

        单轮检索（不调 LLM）：逐启用数据源查询（每轮查全部源语义），结果归一化 +
        去重。per-source 失败跳过（与主循环单源降级一致）；全部源失败或无启用源
        降级返回 []，不阻断规划。
        """
        deduped: List[Dict[str, Any]] = []
        for binding in sources:
            try:
                results = await binding.port.search(query, top_k=max_results)
                deduplicate_results(deduped, results)
            except Exception:
                # 单源失败降级跳过，不影响其余源与主流程
                continue
        # content 截断（防 plan JSON 膨胀）
        for r in deduped:
            if len(r.get("content", "")) > BACKGROUND_RESULT_SNIPPET_CHARS:
                r["content"] = r["content"][:BACKGROUND_RESULT_SNIPPET_CHARS]
        return deduped

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
        style_block: str = "",
        findings_block: str = "（无）",
    ) -> tuple:
        """综合信息生成报告（非流式）。``results`` 经 ``format_search_context`` 格式化为上下文。

        ``style_block`` 为 feature 预格式化的报告风格指令块（deer-flow report_style
        对齐）；``findings_block`` 为各研究步骤 finding 摘要（提升报告 grounding）。
        """
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
            report_style=style_block,
            findings_block=findings_block,
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
        style_block: str = "",
        findings_block: str = "（无）",
    ) -> AsyncIterator[str]:
        """综合信息生成报告（流式，yield 原始 chunk，不含 heartbeat）。

        与非流式不同，接收 feature 预格式化的 ``context``（stream 路径在调用前已格式化）。
        ``style_block``/``findings_block`` 语义同 ``synthesize_report``。
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
            report_style=style_block,
            findings_block=findings_block,
        )
        async for chunk in llm_client.generate_text_stream(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            enable_thinking=False,
        ):
            yield chunk

    async def search(
        self,
        *,
        sources: List[SearchSourceBinding],
        tasks: List[Dict[str, Any]],
        params: EngineResearchParams,
        logger: Optional[Logger] = None,
        llm_client: Optional[BaseLLM] = None,
        prompt_provider: Optional[PromptProvider] = None,
    ) -> AsyncIterator[SearchEvent]:
        """迭代检索循环（AsyncIterator[SearchEvent]），流式与非流式共用。

        两种模式（llm_client=None 时走降级路径，行为与历史版本一致）：

        **降级模式**（llm_client 未注入）：逐任务串行；每任务多轮迭代，每轮查
        **全部启用数据源**（``sources`` 逐 binding 查询）；固定 query（任务描述）
        重复检索；每任务内按 URL/标题/chunk_id 去重（``deduplicate_results`` 原地）；
        ``is_sufficient_results`` 命中则提前结束；单源失败降级跳过，全部源失败才
        ``TaskFailed``，catch-and-continue。

        **观察驱动模式**（deer-flow 对齐，llm_client + prompt_provider 注入）：
        - 每轮检索后 LLM 反思（``research_generate_query``）：输出
          ``{sufficient, next_query, reason}``——sufficient=true 提前结束本任务
          （信息已足够），false 则下一轮改用 ``next_query``（观察驱动 query 演化）；
        - 前序任务的 finding 摘要（``research_task_finding``）注入后续任务的
          query 生成 prompt（跨任务信息流，避免重复检索）；
        - 每任务完成产出 ``TaskFinding`` 事件；LLM 调用失败降级为固定 query 继续
          （不中断研究）；
        - 机械阈值 ``is_sufficient_results`` 保留为成本兜底（先于 LLM 反思判断）。

        签名除新增可空 ``llm_client``/``prompt_provider`` 外不含其它 LLM 参数：
        循环本体不接 feature DTO。数据源经 ``sources`` 注入（可插拔，binding.port
        产出统一 dict 形状结果，归一化在 feature 适配器完成），与纯函数及 feature
        持久化一致。
        """
        all_results: List[Dict[str, Any]] = []
        source_counts: Dict[str, int] = {}
        total_steps = len(tasks) * params.iterations
        step_count = 0
        aligned = llm_client is not None and prompt_provider is not None
        # 跨任务信息流（deer-flow 对齐）：前序任务 finding 摘要累积
        prior_findings: List[str] = []
        # 各任务 finding 累积（随 SearchComplete 产出，供 reporter grounding）
        task_findings_acc: List[Dict[str, str]] = []

        for task in tasks:
            task_id = str(task.get("task_id", ""))
            task_query = task.get("description", "") or ""
            # step_type 路由（deer-flow 对齐）：research+need_search 走检索迭代；
            # processing（或 need_search=False）走纯 LLM 分析。旧形状 dict（无
            # step_type 字段）默认 research 路径，向后兼容。
            raw_step_type = str(task.get("step_type", "research")).lower()
            need_search = bool(task.get("need_search", True))
            is_processing = raw_step_type == "processing" or not need_search
            step_title = str(task.get("title", "")) or task_query
            yield TaskStarted(
                task_id=task_id,
                description=task_query,
                total_iterations=params.iterations,
            )
            try:
                if is_processing:
                    step_count += 1
                    # processing 纯分析步骤：LLM 综合前序发现产出结论（不调检索）。
                    # 未对齐模式（无 LLM）下降级为跳过（不产出 finding）。
                    if aligned:
                        conclusion = await self._run_processing_step(
                            llm_client,
                            prompt_provider,
                            task_description=task_query,
                            step_title=step_title,
                            prior_findings=prior_findings,
                        )
                        prior_findings.append(conclusion)
                        task_findings_acc.append({"task_id": task_id, "finding": conclusion})
                        yield TaskFinding(task_id=task_id, finding=conclusion)
                    continue
                task_results: List[Dict[str, Any]] = []
                for iteration in range(params.iterations):
                    step_count += 1
                    # 每轮查全部启用源：逐源查询、逐源去重入 task_results；
                    # per-source 失败降级跳过（失败源计数），全部源失败才抛错。
                    yield IterationProgress(
                        task_id=task_id,
                        iteration=iteration,
                        use_external=any(
                            b.source_type == SourceType.EXTERNAL.value for b in sources
                        ),
                        step_count=step_count,
                        total_steps=total_steps,
                        current_results_count=len(task_results),
                        current_query=task_query,
                        source_types=[b.source_type for b in sources],
                    )
                    source_errors = 0
                    for binding in sources:
                        try:
                            results = await binding.port.search(
                                task_query, top_k=binding.top_k
                            )
                            deduplicate_results(task_results, results)
                            source_counts[binding.source_type] = (
                                source_counts.get(binding.source_type, 0) + 1
                            )
                        except Exception as e:
                            source_errors += 1
                            if logger is not None:
                                logger.warning(
                                    "数据源检索失败（降级跳过）",
                                    task_id=task_id,
                                    source_type=binding.source_type,
                                    error=str(e),
                                )
                    if source_errors >= len(sources):
                        raise RuntimeError("全部数据源检索失败")
                    # 机械充分性优先（成本兜底）：结果数达标直接收尾，不再花 LLM 反思
                    if is_sufficient_results(task_results, iteration):
                        break
                    if not aligned:
                        continue
                    # deer-flow 对齐：观察驱动反思——LLM 判充分性 + 产出下一 query
                    sufficient, next_query, reason = await self._reflect_and_generate_query(
                        llm_client,
                        prompt_provider,
                        task_description=task.get("description", "") or task_query,
                        task_query=task_query,
                        observations=task_results,
                        prior_findings=prior_findings,
                        iteration=iteration,
                    )
                    if logger is not None:
                        logger.info(
                            "检索反思决策",
                            task_id=task_id,
                            iteration=iteration,
                            sufficient=sufficient,
                            next_query=next_query[:50] if next_query else "",
                            reason=reason[:80] if reason else "",
                        )
                    if sufficient:
                        break
                    if next_query:
                        task_query = next_query
                # 任务成功：去重并入 all_results
                deduplicate_results(all_results, task_results)
                # deer-flow 对齐：产出本任务 finding 摘要，供后续任务参考
                if aligned and task_results:
                    finding = await self._generate_task_finding(
                        llm_client,
                        prompt_provider,
                        task_description=task.get("description", "") or task_query,
                        observations=task_results,
                    )
                    prior_findings.append(finding)
                    task_findings_acc.append({"task_id": task_id, "finding": finding})
                    yield TaskFinding(task_id=task_id, finding=finding)
            except Exception as e:
                if logger is not None:
                    logger.warning("任务检索失败", task_id=task_id, error=str(e))
                yield TaskFailed(task_id=task_id, error=str(e))

        summary = {
            "internal_count": source_counts.get(SourceType.INTERNAL.value, 0),
            "external_count": source_counts.get(SourceType.EXTERNAL.value, 0),
            "source_counts": dict(source_counts),
            "total_results": len(all_results),
            "key_sources": extract_key_sources(all_results),
        }
        yield SearchComplete(
            all_results=all_results, summary=summary, task_findings=task_findings_acc
        )

    async def _run_processing_step(
        self,
        llm_client: BaseLLM,
        prompt_provider: PromptProvider,
        *,
        task_description: str,
        step_title: str,
        prior_findings: List[str],
    ) -> str:
        """processing 纯分析步骤（deer-flow processing/analyst 对齐）。

        LLM 综合前序发现产出该步骤结论（不调检索）。调用失败返回降级文本。
        """
        try:
            findings_block = (
                "\n".join(f"- {f}" for f in prior_findings) if prior_findings else "（无）"
            )
            prompt = prompt_provider.format(
                KEY_PROCESSING_STEP,
                step_title=step_title,
                task_description=task_description,
                prior_findings=findings_block,
            )
            raw = await llm_client.generate_text(
                prompt=prompt,
                max_tokens=600,
                temperature=0.4,
                enable_thinking=False,
            )
            conclusion = _sanitize_search_field(raw)
            if conclusion:
                return conclusion[:EXECUTION_RES_MAX_CHARS]
        except Exception:
            pass
        return f"（分析步骤 {step_title} 执行失败，跳过）"

    async def _reflect_and_generate_query(
        self,
        llm_client: BaseLLM,
        prompt_provider: PromptProvider,
        *,
        task_description: str,
        task_query: str,
        observations: List[Any],
        prior_findings: List[str],
        iteration: int,
    ) -> tuple:
        """观察驱动反思（deer-flow 对齐）：判断信息是否足够 + 产出下一 query。

        返回 (sufficient, next_query, reason)。LLM 调用/解析失败 → 降级为
        (False, "", 错误说明)，调用方以原 query 继续（不中断研究）。
        """
        try:
            findings_block = (
                "\n".join(f"- {f}" for f in prior_findings) if prior_findings else "（无）"
            )
            prompt = prompt_provider.format(
                KEY_GENERATE_QUERY,
                task_description=task_description,
                current_query=task_query,
                observations=summarize_observations_for_llm(observations),
                prior_findings=findings_block,
                iteration=str(iteration + 1),
            )
            raw = await llm_client.generate_text(
                prompt=prompt,
                max_tokens=200,
                temperature=0.3,
                enable_thinking=False,
            )
            sufficient, next_query, reason = parse_query_decision(raw)
            if sufficient or next_query:
                return sufficient, next_query, reason
            # sufficient=false 且无有效 query：视为降级（避免空 query 空转）
            return False, "", reason or "LLM 未产出有效 query"
        except Exception as e:
            return False, "", f"反思调用失败: {e}"

    async def _generate_task_finding(
        self,
        llm_client: BaseLLM,
        prompt_provider: PromptProvider,
        *,
        task_description: str,
        observations: List[Any],
    ) -> str:
        """生成任务 finding 摘要（deer-flow 对齐：要点+结论，供后续任务参考）。

        LLM 调用失败返回机械摘要（前 3 条结果标题/来源拼接），不中断研究。
        """
        try:
            prompt = prompt_provider.format(
                KEY_TASK_FINDING,
                task_description=task_description,
                observations=summarize_observations_for_llm(observations),
            )
            raw = await llm_client.generate_text(
                prompt=prompt,
                max_tokens=300,
                temperature=0.3,
                enable_thinking=False,
            )
            finding = _sanitize_search_field(raw)
            if finding:
                return finding[:1000]
        except Exception:
            pass
        # 降级：机械拼接前 3 条来源
        parts = []
        for r in observations[:3]:
            label = r.get("title") or r.get("document_name") or r.get("url") or ""
            if label:
                parts.append(str(label))
        return "；".join(parts) if parts else "（本任务无有效发现）"