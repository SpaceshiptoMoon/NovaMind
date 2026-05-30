"""
深度研究核心服务

实现基于 RAG 的深度研究功能，支持动态选择内部/外部搜索
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, AsyncGenerator
import asyncio
import re
import time
import json

from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.utils.time_utils import now_china

from src.features.deep_research.models.research_session import (
    ResearchSession,
    ResearchStatus,
    ResearchMode,
    SearchSource,
    ExternalSearchProvider,
)
from src.features.deep_research.repository.research_repository import ResearchRepository
from src.features.deep_research.services.tavily_service import TavilySearchService
from src.features.deep_research.services.serpapi_service import SerpAPISearchService
from src.features.deep_research.services.duckduckgo_service import DuckDuckGoSearchService
from src.features.deep_research.schemas.research_schema import (
    InternalSearchConfig,
)
from src.features.knowledge_space.services.search_service import SearchService
from src.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
from src.features.knowledge_space.schemas.search_schema import (
    SearchRequest,
    WeightConfig,
    RerankConfig,
    SearchMode,
)
from src.features.knowledge_space.models.knowledge_base import KnowledgeBaseStatus
from src.core.middleware.structured_logging import get_logger
from src.shared.utils.heartbeat import stream_with_heartbeat
from src.shared.prompts import PromptTemplate, PromptManager
from src.features.deep_research.exceptions import (
    DeepResearchError,
    ResearchNotFoundError,
    ResearchFailedError,
    ResearchAccessDeniedError,
    ResearchRunningError,
    ResearchSpaceAccessDeniedError,
    InvalidResearchQueryError,
    ResearchModeNotSupportedError,
    SearchProviderNotConfiguredError,
    SearchProviderUnavailableError,
)


# 研究模式参数映射
# 结果充分性阈值常量
SUFFICIENT_RESULT_COUNT = 10  # 结果数量阈值
MAX_ITERATION_THRESHOLD = 3  # 最大迭代阈值


RESEARCH_MODE_CONFIG = {
    ResearchMode.QUICK: {"depth": 2, "iterations": 3},
    ResearchMode.STANDARD: {"depth": 3, "iterations": 5},
    ResearchMode.DEEP: {"depth": 5, "iterations": 7},
}


def _sanitize_search_field(text: str) -> str:
    """清理搜索结果字段中的特殊标记，空值时返回空字符串而不抛异常"""
    if not text or not text.strip():
        return ""
    markers = ["<|im_start|>", "<|im_end|>", "", "[INST]", "[/INST]", "<<SYS>>", "<</SYS>>"]
    sanitized = text
    for marker in markers:
        sanitized = sanitized.replace(marker, "")
    return sanitized.strip()


def _sanitize_user_input(text: str) -> str:
    """
    清理用户输入中的特殊标记，防止 prompt 注入

    注意：此方法基于黑名单机制，覆盖主流 LLM 的特殊标记。
    黑名单方式无法 100% 防御所有注入，但结合 prompt 中的分隔标记
    （---用户查询开始---/---用户查询结束---）提供双重防护。
    """
    if not text or not text.strip():
        raise InvalidResearchQueryError("查询内容不能为空")

    # 移除常见的 LLM 特殊标记
    markers = ["<|im_start|>", "<|im_end|>", "<|endoftext|>", "[INST]", "[/INST]", "<<SYS>>", "<</SYS>>"]
    sanitized = text
    for marker in markers:
        sanitized = sanitized.replace(marker, "")

    sanitized = sanitized.strip()
    if len(sanitized) < 2:
        raise InvalidResearchQueryError("清理后的查询内容过短，请提供更有意义的查询")

    return sanitized


@dataclass
class ResearchParams:
    """从请求中提取的研究参数（流式/非流式共享）"""
    query: str
    research_mode: Any
    search_source: Any
    internal_config: Any
    external_config: Any
    llm_config: Any
    retrieval_top_k: int
    retrieval_weight: float


def _extract_research_params(request) -> ResearchParams:
    """从 ResearchRequest 中提取参数"""
    return ResearchParams(
        query=request.query,
        research_mode=request.research_mode,
        search_source=request.search_source,
        internal_config=request.internal_search,
        external_config=request.external_search,
        llm_config=request.llm,
        retrieval_top_k=request.internal_search.top_k,
        retrieval_weight=request.internal_search.vector_weight,
    )


@dataclass
class ResearchContext:
    """研究管线上下文（贯穿整个流程，替代多方法间的参数传递）"""
    # 流程标识
    research_id: int = 0
    session_id: str = ""
    space_id: int = 0
    user_id: int = 0
    params: Optional[ResearchParams] = None
    mode_config: Optional[Dict[str, Any]] = None

    # ORM 对象
    research: Optional[Any] = None

    # 管线逐步填充
    research_topic: Optional[str] = None
    tasks: Optional[List[Dict[str, Any]]] = None
    search_results: Optional[Dict[str, Any]] = None
    report: Optional[str] = None
    stats: Optional[Dict[str, Any]] = None

    # 流式检索统计（仅 research_stream 使用）
    all_results: Optional[List[Dict[str, Any]]] = None
    internal_count: int = 0
    external_count: int = 0

    # 计时
    start_time: float = 0.0


class DeepResearchService:
    """
    深度研究服务

    工作流程：
    1. 分析查询，提取研究主题
    2. 分解研究任务（基于查询复杂度和模式）
    3. 动态决策搜索策略（内部 RAG / 外部 Web / 混合）
    4. 执行检索（多轮迭代）
    5. 综合信息生成报告
    6. 流式输出结果

    支持用户配置的 LLM 模型
    """

    def __init__(
        self,
        session: AsyncSession,
        model_config_service: Optional[Any] = None,
        search_service: Optional[SearchService] = None,
        es_client: Optional[Any] = None,
    ):
        self.session = session
        self.research_repo = ResearchRepository(session)
        self._es_client = es_client
        self._model_config_service = model_config_service
        self._search_service = search_service

        # 初始化外部搜索服务
        self._init_external_search_services()

        self.logger = get_logger(__name__)

    @property
    def search_service(self) -> SearchService:
        """延迟获取搜索服务（构造函数中不调用异步工厂）"""
        if self._search_service is None:
            if self._es_client is None:
                raise RuntimeError(
                    "DeepResearchService 需要通过 es_client 参数传入 Elasticsearch 客户端，"
                    "请使用依赖注入方式创建实例"
                )
            self._search_service = SearchService(
                self.session,
                es_client=self._es_client,
                model_config_service=self._model_config_service,
            )
        return self._search_service

    async def cleanup(self) -> None:
        """清理外部搜索服务资源"""
        for service in self.external_services.values():
            if hasattr(service, "close"):
                try:
                    await service.close()
                except Exception as e:
                    self.logger.warning("关闭外部搜索服务失败", error=str(e))

    async def _get_llm_client(
        self,
        user_id: int,
        llm_model: Optional[str]
    ):
        """
        获取 LLM 客户端

        通过 ModelConfigService 从数据库解析凭证，无配置时抛异常

        Args:
            user_id: 用户 ID
            llm_model: 模型名称（可选）

        Returns:
            LLM 客户端

        Raises:
            ResearchFailedError: 未配置模型
        """
        if self._model_config_service:
            # 如果没有指定模型，获取系统默认
            if not llm_model:
                llm_model = await self._model_config_service.get_default_model_name("llm")

            if llm_model:
                return await self._model_config_service.get_llm_client_by_model(
                    user_id, llm_model
                )

        raise ResearchFailedError("", "未配置 LLM 模型，请在模型配置中添加")

    async def list_researches(
        self,
        space_id: int,
        user_id: Optional[int] = None,
        status: Optional["ResearchStatus"] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple:
        """
        获取空间的研究历史列表

        Args:
            space_id: 知识空间 ID
            user_id: 用户 ID（可选，不传则返回空间所有研究）
            status: 状态过滤
            limit: 返回数量
            offset: 偏移量

        Returns:
            (items, total) 元组
        """
        items = await self.research_repo.get_by_space(
            space_id=space_id,
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        total = await self.research_repo.count_by_space(
            space_id=space_id,
            user_id=user_id,
            status=status,
        )
        return items, total

    async def get_research(
        self,
        session_id: str,
        space_id: int,
        user_id: int,
        is_admin: bool = False,
    ) -> Optional["ResearchSession"]:
        """
        获取研究会话详情（含权限校验）

        Args:
            session_id: 会话唯一标识
            space_id: 知识空间 ID
            user_id: 当前用户 ID
            is_admin: 是否管理员

        Returns:
            研究会话实例

        Raises:
            ResearchNotFoundError: 研究不存在
            ResearchSpaceAccessDeniedError: 无权访问知识空间
        """
        research = await self.research_repo.get_by_session_id(session_id)
        if not research:
            raise ResearchNotFoundError(session_id)

        # 验证空间归属
        if research.space_id != space_id:
            raise ResearchSpaceAccessDeniedError(space_id, user_id)

        # 非管理员只能查看自己的研究
        if not is_admin and research.user_id != user_id:
            raise ResearchAccessDeniedError(session_id, user_id)

        return research

    async def delete_research(
        self,
        session_id: str,
        space_id: int,
        user_id: int,
        is_admin: bool = False,
    ) -> None:
        """
        删除研究会话记录（含权限校验）

        Args:
            session_id: 会话唯一标识
            space_id: 知识空间 ID
            user_id: 当前用户 ID
            is_admin: 是否管理员

        Raises:
            ResearchNotFoundError: 研究不存在
            ResearchSpaceAccessDeniedError: 无权访问知识空间
            ResearchAccessDeniedError: 无权删除
            ResearchRunningError: 研究正在运行中
        """
        research = await self.research_repo.get_by_session_id(session_id)
        if not research:
            raise ResearchNotFoundError(session_id)

        # 验证空间归属
        if research.space_id != space_id:
            raise ResearchSpaceAccessDeniedError(space_id, user_id)

        # 权限检查：非管理员只能删除自己的研究
        if not is_admin and research.user_id != user_id:
            raise ResearchAccessDeniedError(session_id, user_id)

        # 状态检查：运行中的研究不允许删除
        if research.is_running():
            raise ResearchRunningError(session_id)

        await self.research_repo.delete(research.id)
        await self.session.commit()

    def _init_external_search_services(self):
        """初始化外部搜索服务"""
        self.external_services = {
            ExternalSearchProvider.TAVILY: TavilySearchService(),
            ExternalSearchProvider.SERPAPI: SerpAPISearchService(),
            ExternalSearchProvider.DUCKDUCKGO: DuckDuckGoSearchService(),
        }

    def _get_external_service(self, provider: ExternalSearchProvider):
        """获取外部搜索服务"""
        return self.external_services.get(provider)

    async def research(
        self,
        space_id: int,
        user_id: int,
        request: "ResearchRequest",
    ) -> Dict[str, Any]:
        """
        执行深度研究（非流式）

        Args:
            space_id: 知识空间 ID
            user_id: 用户 ID
            request: 研究请求配置

        Returns:
            研究结果字典
        """
        if request.research_mode not in RESEARCH_MODE_CONFIG:
            raise ResearchModeNotSupportedError(request.research_mode)

        ctx = ResearchContext(
            space_id=space_id,
            user_id=user_id,
            params=_extract_research_params(request),
            mode_config=RESEARCH_MODE_CONFIG[request.research_mode],
        )

        try:
            await self._create_research_session(ctx)
            # DR-1: 提前触发 search_service 初始化，尽早暴露 ES 配置问题
            if ctx.params.search_source != SearchSource.EXTERNAL:
                _ = self.search_service
            await self._analyze_and_save_topic(ctx)
            await self._decompose_and_save_tasks(ctx)
            await self._execute_research_search(ctx)
            await self._synthesize_and_save_report(ctx)
            return self._build_research_result(ctx)
        except DeepResearchError as e:
            await self._handle_research_error(ctx, e)
            raise ResearchFailedError(ctx.session_id, str(e)) from e
        except Exception as e:
            await self._handle_research_error(ctx, e)
            raise ResearchFailedError(ctx.session_id, "研究执行失败，请稍后重试") from e

    async def research_stream(
        self,
        space_id: int,
        user_id: int,
        request: "ResearchRequest",
    ) -> AsyncGenerator[str, None]:
        """
        执行深度研究（流式）

        Yield SSE 格式的 JSON 字符串

        事件类型：
        - progress: 进度更新
        - content: 报告内容片段
        - error: 错误信息
        - done: 研究完成
        """
        if request.research_mode not in RESEARCH_MODE_CONFIG:
            raise ResearchModeNotSupportedError(request.research_mode)

        ctx = ResearchContext(
            space_id=space_id,
            user_id=user_id,
            params=_extract_research_params(request),
            mode_config=RESEARCH_MODE_CONFIG[request.research_mode],
            all_results=[],
        )

        def send_event(event_type: str, data: dict) -> str:
            """生成 SSE 事件"""
            event = {
                "event_type": event_type,
                "data": data,
                "timestamp": time.time(),
            }
            return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        try:
            # 0. 创建会话
            await self._create_research_session(ctx)
            # DR-1: 提前触发 search_service 初始化，尽早暴露 ES 配置问题
            if ctx.params.search_source != SearchSource.EXTERNAL:
                _ = self.search_service

            # 1. 分析查询
            yield send_event("progress", {
                "status": "analyzing",
                "current_step": "分析查询，提取研究主题",
                "progress_percent": 10.0,
                "completed_tasks": 0,
                "total_tasks": 0,
            })
            await self._analyze_and_save_topic(ctx)

            # 2. 分解任务
            await self._decompose_and_save_tasks(ctx)
            yield send_event("progress", {
                "status": "analyzing",
                "current_step": f"研究主题：{ctx.research_topic}，正在分解子任务",
                "progress_percent": 20.0,
                "completed_tasks": 0,
                "total_tasks": len(ctx.tasks),
            })

            # 3. 逐任务执行检索（yield SSE 进度事件）
            total_steps = len(ctx.tasks) * ctx.mode_config["iterations"]
            step_count = 0
            for task in ctx.tasks:
                task_query = task.get("description", ctx.params.query)
                for iteration in range(ctx.mode_config["iterations"]):
                    step_count += 1
                    use_external = self._should_use_external_search(
                        ctx.params.search_source, iteration
                    )
                    step_desc = f"{'外部搜索' if use_external else '内部检索'}：{task_query[:50]}"
                    yield send_event("progress", {
                        "status": "searching",
                        "current_step": step_desc,
                        "progress_percent": 20.0 + (step_count / total_steps) * 60.0,
                        "completed_tasks": step_count,
                        "total_tasks": total_steps,
                    })
                    if use_external:
                        results = await self._execute_external_search(
                            provider=ctx.params.external_config.provider,
                            query=task_query,
                            max_results=ctx.params.external_config.max_results,
                        )
                        ctx.external_count += 1
                    else:
                        results = await self._execute_internal_search(
                            space_id=ctx.space_id,
                            user_id=ctx.user_id,
                            query=task_query,
                            config=ctx.params.internal_config,
                        )
                        ctx.internal_count += 1
                    self._deduplicate_results(ctx.all_results, results)
                    if self._is_sufficient_results(ctx.all_results, iteration):
                        break

            # 构建统一搜索结果结构（与非流式路径一致）
            ctx.search_results = {
                "results": ctx.all_results,
                "summary": {
                    "internal_count": ctx.internal_count,
                    "external_count": ctx.external_count,
                    "total_results": len(ctx.all_results),
                    "key_sources": self._extract_key_sources(ctx.all_results),
                },
                "internal_count": ctx.internal_count,
                "external_count": ctx.external_count,
            }

            # 4. 流式综合报告
            yield send_event("progress", {
                "status": "synthesizing",
                "current_step": "综合信息生成报告",
                "progress_percent": 85.0,
                "completed_tasks": total_steps,
                "total_tasks": total_steps,
            })

            full_report = ""
            context_str = self._format_search_context(ctx.all_results)
            key_sources = self._extract_key_sources(ctx.all_results)
            raw_stream = self._synthesize_report_stream(
                query=ctx.params.query,
                research_topic=ctx.research_topic,
                context=context_str,
                key_sources=key_sources,
                max_tokens=ctx.params.llm_config.max_tokens,
                temperature=ctx.params.llm_config.temperature,
                top_p=ctx.params.llm_config.top_p,
                user_id=ctx.user_id,
                llm_model=ctx.params.llm_config.llm_model,
            )

            async for chunk in stream_with_heartbeat(raw_stream):
                if chunk.startswith(": "):  # SSE 心跳注释，只转发保活不追加到报告
                    yield chunk
                    continue
                full_report += chunk
                yield send_event("content", {"chunk": chunk})

            # 5. 持久化并完成
            elapsed_seconds = int(time.time() - ctx.start_time)
            stats = {
                "elapsed_seconds": elapsed_seconds,
                "internal_searches": ctx.internal_count,
                "external_searches": ctx.external_count,
                "total_results": len(ctx.all_results),
            }
            await self.research_repo.update_search_results(ctx.research_id, ctx.all_results)
            await self.research_repo.complete_research(ctx.research_id, full_report, stats, key_sources)
            await self.session.commit()

            yield send_event("done", {
                "session_id": ctx.session_id,
                "final_report": full_report,
                "stats": stats,
                "sources": key_sources,
            })

        except DeepResearchError as e:
            await self._handle_research_error(ctx, e)
            yield send_event("error", {"message": str(e), "session_id": ctx.session_id})
            return
        except Exception as e:
            await self._handle_research_error(ctx, e)
            yield send_event("error", {"message": "研究执行失败，请稍后重试", "session_id": ctx.session_id})
            return

    # ==================== 私有方法 ====================

    async def _analyze_query(self, query: str, user_id: int = None, llm_model: str = None) -> str:
        """分析查询，提取研究主题"""
        safe_query = _sanitize_user_input(query)
        prompt = PromptManager.format_prompt(
            PromptTemplate.RESEARCH_ANALYZE_QUERY.value,
            query=safe_query,
        )

        llm = await self._get_llm_client(user_id, llm_model)
        result = await llm.generate_text(
            prompt=prompt,
            max_tokens=100,
            temperature=0.3,
            enable_thinking=False,
        )

        return result.strip()

    async def _decompose_tasks(
        self,
        query: str,
        research_topic: str,
        depth: int,
        user_id: int = None,
        llm_model: str = None,
    ) -> List[Dict[str, Any]]:
        """分解研究任务"""
        safe_query = _sanitize_user_input(query)
        safe_topic = _sanitize_user_input(research_topic)
        prompt = PromptManager.format_prompt(
            PromptTemplate.RESEARCH_DECOMPOSE_TASKS.value,
            research_topic=safe_topic,
            query=safe_query,
            depth=depth,
        )

        llm = await self._get_llm_client(user_id, llm_model)
        result = await llm.generate_text(
            prompt=prompt,
            max_tokens=1000,
            temperature=0.5,
            enable_thinking=False,
        )

        try:
            # 尝试解析 JSON
            json_pattern = r'\[[\s\S]*\]'
            matches = re.findall(json_pattern, result)
            if not matches:
                raise json.JSONDecodeError("未找到 JSON 数组", result, 0)
            json_match = matches[0]
            tasks = json.loads(json_match)
            # 校验每个 task 是否包含必填字段
            validated_tasks = []
            for i, task in enumerate(tasks[:depth]):
                validated_tasks.append({
                    "task_id": task.get("task_id") or task.get("id") or f"task_{i+1}",
                    "description": task.get("description", f"研究 {research_topic} 的第 {i+1} 个方面"),
                    "priority": task.get("priority", i + 1),
                })
            return validated_tasks
        except (json.JSONDecodeError, ValueError) as e:
            # 降级：生成默认任务
            logger.warning("LLM 任务分解 JSON 解析失败，使用默认任务", error=str(e))
            return [
                {
                    "task_id": f"task_{i+1}",
                    "description": f"研究 {research_topic} 的第 {i+1} 个方面",
                    "priority": i + 1,
                }
                for i in range(depth)
            ]

    # ==================== 管线方法 ====================

    async def _create_research_session(self, ctx: ResearchContext) -> None:
        """创建研究会话并 flush 到数据库"""
        # 序列化子配置到 config JSON 字段
        config = {
            "internal_search": ctx.params.internal_config.model_dump() if hasattr(ctx.params.internal_config, "model_dump") else {},
            "external_search": ctx.params.external_config.model_dump() if hasattr(ctx.params.external_config, "model_dump") else {},
            "llm": ctx.params.llm_config.model_dump() if hasattr(ctx.params.llm_config, "model_dump") else {},
        }
        research = await self.research_repo.create(
            space_id=ctx.space_id,
            user_id=ctx.user_id,
            query=ctx.params.query,
            mode=ctx.params.research_mode,
            search_source=ctx.params.search_source,
            external_provider=ctx.params.external_config.provider,
            config=config,
        )
        ctx.research = research
        ctx.research_id = research.id
        ctx.session_id = research.session_id
        ctx.start_time = time.time()
        self.logger.info("开始深度研究", session_id=ctx.session_id, query=ctx.params.query[:50])

    async def _analyze_and_save_topic(self, ctx: ResearchContext) -> None:
        """分析查询提取研究主题，标记研究开始"""
        # 刷新对象以确保 commit 后状态正确
        await self.session.refresh(ctx.research)

        # 标记开始
        ctx.research.mark_started()
        await self.session.flush()

        # 分析查询
        ctx.research_topic = await self._analyze_query(
            ctx.params.query,
            user_id=ctx.user_id,
            llm_model=ctx.params.llm_config.llm_model,
        )

        # 持久化主题
        await self.research_repo.update_research_topic(ctx.research_id, ctx.research_topic)
        await self.session.flush()
        self.logger.debug("研究主题提取完成", session_id=ctx.session_id, topic=ctx.research_topic)

    async def _decompose_and_save_tasks(self, ctx: ResearchContext) -> None:
        """分解研究任务并持久化"""
        depth = ctx.mode_config["depth"]
        ctx.tasks = await self._decompose_tasks(
            ctx.params.query, ctx.research_topic, depth,
            user_id=ctx.user_id, llm_model=ctx.params.llm_config.llm_model,
        )
        await self.research_repo.update_tasks(ctx.research_id, ctx.tasks)
        await self.session.flush()
        self.logger.debug("任务分解完成", session_id=ctx.session_id, tasks_count=len(ctx.tasks))

    async def _execute_research_search(self, ctx: ResearchContext) -> None:
        """串行执行所有任务的检索（SQLAlchemy AsyncSession 不保证并发安全）"""

        async def _search_single_task(task: Dict[str, Any]) -> Dict[str, Any]:
            """单个任务的多轮迭代检索"""
            task_results = []
            internal_count = 0
            external_count = 0
            task_query = task.get("description", ctx.params.query)

            for iteration in range(ctx.mode_config["iterations"]):
                use_external = self._should_use_external_search(
                    ctx.params.search_source, iteration
                )
                if use_external:
                    results = await self._execute_external_search(
                        provider=ctx.params.external_config.provider,
                        query=task_query,
                        max_results=ctx.params.external_config.max_results,
                    )
                    external_count += 1
                else:
                    results = await self._execute_internal_search(
                        space_id=ctx.space_id,
                        user_id=ctx.user_id,
                        query=task_query,
                        config=ctx.params.internal_config,
                    )
                    internal_count += 1

                self._deduplicate_results(task_results, results)
                if self._is_sufficient_results(task_results, iteration):
                    break

            return {
                "results": task_results,
                "internal_count": internal_count,
                "external_count": external_count,
            }

        # 串行执行所有任务（避免共享 SQLAlchemy session 的并发问题）
        all_results = []
        total_internal = 0
        total_external = 0
        for task in ctx.tasks:
            try:
                result = await _search_single_task(task)
                total_internal += result["internal_count"]
                total_external += result["external_count"]
                self._deduplicate_results(all_results, result["results"])
            except Exception as e:
                self.logger.warning(
                    "任务检索失败",
                    task_id=task.get("task_id"),
                    error=str(e),
                )

        ctx.search_results = {
            "results": all_results,
            "summary": {
                "internal_count": total_internal,
                "external_count": total_external,
                "total_results": len(all_results),
                "key_sources": self._extract_key_sources(all_results),
            },
            "internal_count": total_internal,
            "external_count": total_external,
        }

    async def _synthesize_and_save_report(self, ctx: ResearchContext) -> None:
        """综合报告并持久化全部结果"""
        report, metadata = await self._synthesize_report(
            query=ctx.params.query,
            research_topic=ctx.research_topic,
            search_results=ctx.search_results,
            max_tokens=ctx.params.llm_config.max_tokens,
            temperature=ctx.params.llm_config.temperature,
            top_p=ctx.params.llm_config.top_p,
            user_id=ctx.user_id,
            llm_model=ctx.params.llm_config.llm_model,
        )
        ctx.report = report

        elapsed_seconds = int(time.time() - ctx.start_time)
        ctx.stats = {
            "elapsed_seconds": elapsed_seconds,
            "internal_searches": ctx.search_results.get("internal_count", 0),
            "external_searches": ctx.search_results.get("external_count", 0),
            "total_results": len(ctx.search_results.get("results", [])),
            "tasks_completed": len(ctx.tasks),
            **metadata,
        }

        # 持久化搜索结果
        await self.research_repo.update_search_results(
            ctx.research_id, ctx.search_results.get("results", [])
        )
        key_sources = self._extract_key_sources(ctx.search_results.get("results", []))
        await self.research_repo.complete_research(ctx.research_id, ctx.report, ctx.stats, key_sources)
        await self.session.commit()

        self.logger.info(
            "深度研究完成",
            session_id=ctx.session_id,
            elapsed_seconds=elapsed_seconds,
        )

    def _build_research_result(self, ctx: ResearchContext) -> Dict[str, Any]:
        """构建返回字典（纯数据组装，无 IO）"""
        return {
            "session_id": ctx.session_id,
            "query": ctx.params.query,
            "status": ResearchStatus.COMPLETED.value,
            "research_mode": ctx.params.research_mode,
            "search_source": ctx.params.search_source,
            "research_topic": ctx.research_topic,
            "research_tasks": ctx.tasks,
            "final_report": ctx.report,
            "search_summary": ctx.search_results.get("summary", {}),
            "stats": ctx.stats,
            "created_at": ctx.research.created_at,
            "completed_at": now_china(),
            "external_provider": ctx.params.external_config.provider,
        }

    async def _handle_research_error(self, ctx: ResearchContext, error: Exception) -> None:
        """统一的错误处理：回滚事务 + 标记研究失败"""
        is_known_error = isinstance(error, DeepResearchError)
        error_msg = str(error) if is_known_error else "研究执行失败，请稍后重试"

        self.logger.error(
            "深度研究失败" + ("(DeepResearchError)" if is_known_error else ""),
            session_id=ctx.session_id,
            error=str(error),
        )
        await self.session.rollback()
        try:
            if ctx.research_id > 0:
                from src.core.database.database import get_db_session
                from sqlalchemy import select, update
                async with get_db_session() as recovery_session:
                    # 先查询当前状态，避免覆盖已 COMMIT 的 COMPLETED 状态
                    result = await recovery_session.execute(
                        select(ResearchSession.status).where(ResearchSession.id == ctx.research_id)
                    )
                    current_status = result.scalar_one_or_none()
                    if current_status is not None and current_status == ResearchStatus.COMPLETED:
                        self.logger.warning(
                            "研究已处于 COMPLETED 状态，跳过 FAILED 标记",
                            research_id=ctx.research_id,
                            session_id=ctx.session_id,
                        )
                        return
                    await recovery_session.execute(
                        update(ResearchSession)
                        .where(ResearchSession.id == ctx.research_id)
                        .values(status=ResearchStatus.FAILED, status_info={"error_message": error_msg})
                    )
                    await recovery_session.commit()
        except Exception as commit_err:
            self.logger.error(
                "标记研究失败时提交异常，需手动恢复",
                research_id=ctx.research_id,
                session_id=ctx.session_id,
                original_error=str(error),
                recovery_error=str(commit_err),
            )

    async def _execute_internal_search(
        self,
        space_id: int,
        user_id: int,
        query: str,
        config: "InternalSearchConfig",
    ) -> List[Dict[str, Any]]:
        """
        执行内部 RAG 检索

        Args:
            space_id: 知识空间 ID
            user_id: 用户 ID
            query: 查询文本
            config: 内部检索配置

        Returns:
            检索结果列表
        """
        try:
            # 确定要搜索的知识库（仅搜索活跃状态的知识库）
            kb_repo = KnowledgeBaseRepository(self.session)
            if config.kb_ids:
                # 指定了知识库 ID 列表
                kbs = []
                for kb_id in config.kb_ids:
                    kb = await kb_repo.get_by_id(kb_id)
                    # 检查知识库归属、状态是否活跃
                    if kb and kb.space_id == space_id and kb.status == KnowledgeBaseStatus.ACTIVE:
                        kbs.append(kb)
            else:
                # 搜索空间下所有活跃知识库
                all_kbs = await kb_repo.get_by_space(space_id)
                kbs = [kb for kb in all_kbs if kb.status == KnowledgeBaseStatus.ACTIVE]

            if not kbs:
                self.logger.warning("空间无可用知识库，跳过内部检索", space_id=space_id)
                return []

            # 构建检索请求
            weights = WeightConfig(
                vector_weight=config.vector_weight,
                bm25_weight=config.bm25_weight,
            )
            rerank_config = None
            if config.rerank_enabled:
                rerank_config = RerankConfig(
                    enabled=True,
                    top_k=config.rerank_top_k,
                    model=config.rerank_model,
                )

            search_req = SearchRequest(
                query=query,
                search_mode=SearchMode(config.search_mode),
                top_k=config.top_k,
                weights=weights,
                rerank=rerank_config,
                score_threshold=config.score_threshold,
            )

            # 顺序搜索所有知识库并合并结果（共享 session 不能并发）
            search_results = []
            for kb in kbs:
                try:
                    result = await self.search_service.search(
                        space_id=space_id,
                        kb_id=kb.id,
                        user_id=user_id,
                        request=search_req,
                    )
                    search_results.append(result)
                except Exception as e:
                    self.logger.warning("知识库搜索失败", kb_id=kb.id, error=str(e))
                    search_results.append({"results": []})

            all_results = []
            for kb, search_result in zip(kbs, search_results):
                for r in search_result.get("results", []):
                    all_results.append({
                        "source_type": "internal",
                        "content": r.get("content", ""),
                        "document_id": r.get("document_id"),
                        "chunk_id": r.get("chunk_id"),
                        "document_name": r.get("file_info", {}).get("filename") or r.get("document_name"),
                        "kb_id": kb.id,
                        "kb_name": kb.name,
                        "score": r.get("score", 0),
                    })

            # 按 score 排序并截取 top_k
            all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
            return all_results[:config.top_k]
        except Exception as e:
            self.logger.warning("内部检索失败", query=query, error=str(e))
            raise DeepResearchError("内部检索失败，请稍后重试")

    async def _execute_external_search(
        self,
        provider: ExternalSearchProvider,
        query: str,
        max_results: int,
    ) -> List[Dict[str, Any]]:
        """执行外部搜索"""
        service = self._get_external_service(provider)
        if not service:
            raise SearchProviderNotConfiguredError(provider.value)

        if not service.is_available():
            raise SearchProviderUnavailableError(provider.value, "服务不可用或未配置")

        try:
            results = await service.search(query, max_results)
            return [
                {
                    "source_type": "external",
                    "content": r.content,
                    "url": r.url,
                    "title": r.title,
                    "score": r.score,
                }
                for r in results
            ]
        except (SearchProviderNotConfiguredError, SearchProviderUnavailableError):
            raise
        except DeepResearchError:
            raise
        except Exception as e:
            self.logger.error("外部搜索失败", provider=provider, error=str(e))
            raise SearchProviderUnavailableError(provider.value, str(e))

    def _should_use_external_search(
        self,
        search_source: SearchSource,
        iteration: int,
    ) -> bool:
        """动态决策是否使用外部搜索"""
        if search_source == SearchSource.EXTERNAL:
            return True
        elif search_source == SearchSource.INTERNAL:
            return False
        else:  # hybrid
            # 首次迭代优先内部 RAG
            if iteration == 0:
                return False
            # 后续迭代交替使用
            return iteration % 2 == 1

    def _is_sufficient_results(
        self,
        results: List[Dict[str, Any]],
        iteration: int,
    ) -> bool:
        """检查结果是否足够"""
        if len(results) >= SUFFICIENT_RESULT_COUNT:
            return True
        if len(results) > 0 and iteration >= MAX_ITERATION_THRESHOLD:
            return True
        return False

    def _deduplicate_results(
        self,
        all_results: List[Dict[str, Any]],
        new_results: List[Dict[str, Any]],
    ) -> None:
        """基于 URL、标题或 chunk_id 过滤重复结果，将去重后的新结果追加到 all_results"""
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

    def _extract_key_sources(self, results: List[Dict[str, Any]]) -> List[str]:
        """提取关键来源"""
        sources = []
        seen = set()

        for r in results[:10]:
            source = r.get("url") or f"文档: {r.get('document_name', r.get('document_id', '未知'))}"
            if source not in seen:
                sources.append(source)
                seen.add(source)

        return sources[:5]

    def _format_search_context(self, results: List[Dict[str, Any]]) -> str:
        """格式化检索结果为上下文（清理内容防止 prompt 注入）"""
        context_parts = []

        for i, r in enumerate(results[:15], start=1):
            raw_source = r.get("url") or f"文档 {r.get('document_name', r.get('document_id', '未知'))}"
            source = _sanitize_search_field(raw_source) or f"来源 {i}"
            raw_content = r.get("content", "")
            content = _sanitize_search_field(raw_content)
            if content:
                context_parts.append(f"【来源 {i}】({source})\n{content}\n")

        return "\n".join(context_parts)

    async def _synthesize_report(
        self,
        query: str,
        research_topic: str,
        search_results: Dict[str, Any],
        max_tokens: int,
        temperature: float,
        top_p: float,
        user_id: int = None,
        llm_model: str = None,
    ) -> tuple:
        """综合信息生成报告（非流式）"""
        context = self._format_search_context(search_results.get("results", []))
        key_sources = search_results.get("summary", {}).get("key_sources", [])

        safe_query = _sanitize_user_input(query)
        safe_topic = _sanitize_user_input(research_topic)
        key_sources_str = chr(10).join(f"- {s}" for s in key_sources) if key_sources else "无外部来源"
        prompt = PromptManager.format_prompt(
            PromptTemplate.RESEARCH_SYNTHESIZE_REPORT.value,
            query=safe_query,
            research_topic=safe_topic,
            context=context,
            key_sources=key_sources_str,
        )

        llm = await self._get_llm_client(user_id, llm_model)
        report = await llm.generate_text(
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

    async def _synthesize_report_stream(
        self,
        query: str,
        research_topic: str,
        context: str,
        key_sources: List[str],
        max_tokens: int,
        temperature: float,
        top_p: float,
        user_id: int = None,
        llm_model: str = None,
    ) -> AsyncGenerator[str, None]:
        """综合信息生成报告（流式）"""
        safe_query = _sanitize_user_input(query)
        try:
            safe_topic = _sanitize_user_input(research_topic)
        except Exception:
            self.logger.warning("research_topic sanitize 失败，使用原始值", topic=research_topic)
            safe_topic = research_topic or ""
        key_sources_str = chr(10).join(f"- {s}" for s in key_sources) if key_sources else "无外部来源"
        prompt = PromptManager.format_prompt(
            PromptTemplate.RESEARCH_SYNTHESIZE_REPORT_STREAM.value,
            query=safe_query,
            research_topic=safe_topic,
            context=context,
            key_sources=key_sources_str,
        )

        llm = await self._get_llm_client(user_id, llm_model)
        async for chunk in llm.generate_text_stream(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            enable_thinking=False,
        ):
            yield chunk
