"""
深度研究核心服务

实现基于 RAG 的深度研究功能，支持动态选择内部/外部搜索
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, AsyncGenerator
from novamind.shared.model_config_ports import ModelConfigPort
import re
import time
import json

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.shared.utils.time_utils import now_china

from novamind.features.deep_research.models.research_session import (
    ResearchSession,
    ResearchStatus,
    ResearchMode,
)
from novamind.engines.deep_research.types import SearchSource
from novamind.engines.deep_research.types import (
    EngineResearchParams,
    IterationProgress,
    SearchComplete,
    TaskFailed,
)
from novamind.engines.deep_research.errors import EngineInvalidResearchQueryError
from novamind.features.deep_research.repository.research_repository import ResearchRepository
from novamind.features.deep_research.schemas.research_schema import (
    ResearchRequest,
)
from novamind.features.knowledge_space.services.search_service import SearchService
from novamind.shared.retrieval_port import RetrievalPort
from novamind.features.knowledge_space.adapters.retrieval_adapter import HostRetrievalPort
from novamind.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.utils.heartbeat import stream_with_heartbeat
from novamind.features.deep_research.exceptions import (
    DeepResearchError,
    ResearchNotFoundError,
    ResearchFailedError,
    ResearchAccessDeniedError,
    ResearchRunningError,
    ResearchSpaceAccessDeniedError,
    InvalidResearchQueryError,
    ResearchModeNotSupportedError,
)
from novamind.features.deep_research.adapters.web_search_port_adapter import (
    build_web_search_port_for_provider,
)
from novamind.features.deep_research.adapters.internal_search_port_adapter import (
    as_internal_search_port,
)


# 研究模式参数映射（业务配置，留 feature；与 setting/yaml_config/config.py 重复）
RESEARCH_MODE_CONFIG = {
    ResearchMode.QUICK: {"depth": 2, "iterations": 3},
    ResearchMode.STANDARD: {"depth": 3, "iterations": 5},
    ResearchMode.DEEP: {"depth": 5, "iterations": 7},
}


# 纯检索辅助函数自 engines/deep_research 反向引用（feature -> engine 合法）。
# A-3：迭代循环（去重/充分性/外部决策）已迁入 DeepResearchEngine.search；
# feature 仅保留综合上下文/关键来源两个纯函数代理（synthesize 路径用）。
from novamind.engines.deep_research.engine import (  # noqa: E402
    extract_key_sources as _extract_key_sources_fn,
    format_search_context as _format_search_context_fn,
)


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
        model_config_service: Optional[ModelConfigPort] = None,
        search_service: Optional[SearchService] = None,
        es_client: Optional[Any] = None,
    ):
        self.session = session
        self.research_repo = ResearchRepository(session)
        self._es_client = es_client
        self._model_config_service = model_config_service
        self._search_service = search_service
        self._search_port: Optional[RetrievalPort] = None
        # A-3：web_search_port 按请求 provider 构造（build_web_search_port_for_provider），
        # 在 cleanup() 关闭。每请求一个 DeepResearchService 实例（见 api/dependencies）。
        self._web_search_port: Optional[Any] = None

        self.logger = get_logger(__name__)

        # A-2/A-3：核心研究机制（查询分析/任务分解/迭代检索/综合）委托无状态 DeepResearchEngine；
        # prompt 经注入的 PromptProvider（HostPromptProvider 委托 PromptManager）取模板。
        from novamind.engines.prompt_provider_adapter import as_prompt_provider
        from novamind.engines.deep_research import DeepResearchEngine

        self._prompt_provider = as_prompt_provider()
        self._engine = DeepResearchEngine(logger=self.logger)

    @property
    def search_port(self) -> RetrievalPort:
        """延迟获取检索端口（HostRetrievalPort 包 SearchService）。

        批次 2 接缝：本服务依赖 RetrievalPort 抽象而非直接依赖 SearchService。
        构造函数中不调用异步工厂；若调用方传入 SearchService 则包为 HostRetrievalPort，
        否则按需构造 SearchService(self.session, es_client, model_config_service) 再包。
        """
        if self._search_port is None:
            if self._search_service is not None:
                self._search_port = HostRetrievalPort(self._search_service)
            else:
                if self._es_client is None:
                    raise RuntimeError(
                        "DeepResearchService 需要通过 es_client 参数传入 Elasticsearch 客户端，"
                        "请使用依赖注入方式创建实例"
                    )
                self._search_port = HostRetrievalPort(
                    SearchService(
                        self.session,
                        es_client=self._es_client,
                        model_config_service=self._model_config_service,
                    )
                )
        return self._search_port

    async def cleanup(self) -> None:
        """清理外部搜索服务资源（关闭按请求构造的 web_search_port）"""
        if self._web_search_port is not None:
            try:
                close = getattr(self._web_search_port, "close", None)
                if close is not None:
                    await close()
            except Exception as e:
                self.logger.warning("关闭 web_search_port 失败", error=str(e))
            self._web_search_port = None

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
            # 如果没有指定模型，获取用户配置的默认
            if not llm_model:
                llm_model = await self._model_config_service.get_user_default_model_name(user_id, "llm")

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

    def _build_engine_params(self, ctx: ResearchContext) -> EngineResearchParams:
        """从 feature ``ResearchContext`` 装配引擎纯参数 ``EngineResearchParams``。"""
        llm_cfg = ctx.params.llm_config
        return EngineResearchParams(
            search_source=ctx.params.search_source,
            depth=ctx.mode_config["depth"],
            iterations=ctx.mode_config["iterations"],
            top_k=ctx.params.internal_config.top_k,
            external_max_results=ctx.params.external_config.max_results,
            llm_max_tokens=llm_cfg.max_tokens,
            llm_temperature=llm_cfg.temperature,
            llm_top_p=llm_cfg.top_p,
            llm_model=llm_cfg.llm_model,
        )

    def _build_search_ports(self, ctx: ResearchContext) -> tuple:
        """按 search_source 构造引擎检索端口（web/internal，未用的一侧为 None）。

        - EXTERNAL：仅 web_search_port（按 request.provider 构造，存 self._web_search_port 供 cleanup）。
        - INTERNAL：仅 internal_search_port（绑定 space_id/user_id/internal_config）。
        - HYBRID：两者皆构造。
        """
        search_source = ctx.params.search_source
        web_port = None
        internal_port = None
        if search_source != SearchSource.INTERNAL:
            # 按请求 provider 构造；未配置/不可用抛 SearchProvider*Error（DeepResearchError 子类）
            self._web_search_port = build_web_search_port_for_provider(
                ctx.params.external_config.provider
            )
            web_port = self._web_search_port
        if search_source != SearchSource.EXTERNAL:
            kb_repo = KnowledgeBaseRepository(self.session)
            internal_port = as_internal_search_port(
                search_port=self.search_port,
                kb_repo=kb_repo,
                space_id=ctx.space_id,
                user_id=ctx.user_id,
                internal_config=ctx.params.internal_config,
                logger=self.logger,
            )
        return web_port, internal_port

    async def research(
        self,
        space_id: int,
        user_id: int,
        request: ResearchRequest,
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
                _ = self.search_port
            await self._analyze_and_save_topic(ctx)
            await self._decompose_and_save_tasks(ctx)
            await self._execute_research_search(ctx)
            await self._synthesize_and_save_report(ctx)
            return self._build_research_result(ctx)
        except EngineInvalidResearchQueryError as e:
            # E2：引擎级查询错映射为 feature 异常，避免落 generic 分支丢具体信息
            raise InvalidResearchQueryError(str(e)) from e
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
        request: ResearchRequest,
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
                _ = self.search_port

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

            # 3. 逐任务执行检索（消费 DeepResearchEngine.search 事件流，yield SSE 进度）
            # A-3：流式与非流式共用引擎迭代循环（按任务去重+充分性+catch-and-continue），
            # 消除原 research_stream 内联重复循环。单任务失败 → TaskFailed（catch-and-continue），
            # 与非流式行为统一（原流式此处无 per-task try/except，单任务失败会中止整个研究）。
            total_steps = len(ctx.tasks) * ctx.mode_config["iterations"]
            task_desc_by_id = {
                str(t.get("task_id", "")): t.get("description", "")
                for t in ctx.tasks
            }
            engine_params = self._build_engine_params(ctx)
            web_port, internal_port = self._build_search_ports(ctx)

            async for event in self._engine.search(
                web_search_port=web_port,
                internal_search_port=internal_port,
                tasks=ctx.tasks,
                params=engine_params,
                logger=self.logger,
            ):
                if isinstance(event, IterationProgress):
                    task_query = task_desc_by_id.get(event.task_id, "")
                    step_desc = f"{'外部搜索' if event.use_external else '内部检索'}：{task_query[:50]}"
                    yield send_event("progress", {
                        "status": "searching",
                        "current_step": step_desc,
                        "progress_percent": 20.0 + (event.step_count / total_steps) * 60.0,
                        "completed_tasks": event.step_count,
                        "total_tasks": total_steps,
                    })
                elif isinstance(event, TaskFailed):
                    # 引擎已 log；feature 仅记录，catch-and-continue（与非流式统一）
                    self.logger.warning(
                        "研究任务检索失败（catch-and-continue）",
                        task_id=event.task_id,
                        error=event.error,
                    )
                elif isinstance(event, SearchComplete):
                    ctx.all_results = event.all_results
                    ctx.search_results = {
                        "results": event.all_results,
                        "summary": event.summary,
                        "internal_count": event.summary.get("internal_count", 0),
                        "external_count": event.summary.get("external_count", 0),
                    }

            # 兜底：若未收到 SearchComplete（不应发生），保空结果
            if ctx.search_results is None:
                ctx.search_results = {
                    "results": [],
                    "summary": {
                        "internal_count": 0,
                        "external_count": 0,
                        "total_results": 0,
                        "key_sources": [],
                    },
                    "internal_count": 0,
                    "external_count": 0,
                }
                ctx.all_results = []

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
            key_sources = ctx.search_results["summary"].get("key_sources", [])
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
                "internal_searches": ctx.search_results.get("internal_count", 0),
                "external_searches": ctx.search_results.get("external_count", 0),
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

        except EngineInvalidResearchQueryError as e:
            # E2：引擎级查询错映射为 feature 异常，避免落 generic 分支丢具体信息
            yield send_event("error", {
                "message": str(e),
                "session_id": ctx.session_id,
            })
            return
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
        """分析查询，提取研究主题（薄委托 DeepResearchEngine.analyze_query）。

        feature 入口 sanitize（抛 InvalidResearchQueryError），引擎接已 sanitize 的 query。
        """
        safe_query = _sanitize_user_input(query)
        llm = await self._get_llm_client(user_id, llm_model)
        return await self._engine.analyze_query(llm, self._prompt_provider, safe_query)

    async def _decompose_tasks(
        self,
        query: str,
        research_topic: str,
        depth: int,
        user_id: int = None,
        llm_model: str = None,
    ) -> List[Dict[str, Any]]:
        """分解研究任务（薄委托 DeepResearchEngine.decompose_tasks）。

        feature 入口 sanitize query/topic；引擎接 depth 整数与已 sanitize 输入。
        """
        safe_query = _sanitize_user_input(query)
        safe_topic = _sanitize_user_input(research_topic)
        llm = await self._get_llm_client(user_id, llm_model)
        return await self._engine.decompose_tasks(
            llm, self._prompt_provider, safe_query, safe_topic, depth
        )

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
        """执行迭代检索（薄委托 DeepResearchEngine.search 事件流）。

        A-3：可复用迭代循环（按任务去重+充分性+catch-and-continue）已迁入引擎，
        feature 仅消费事件并在 SearchComplete 时填充 ctx.search_results。TaskStarted/
        IterationProgress/TaskFailed 在非流式路径下静默（引擎内部已 log TaskFailed）。
        """
        engine_params = self._build_engine_params(ctx)
        web_port, internal_port = self._build_search_ports(ctx)

        async for event in self._engine.search(
            web_search_port=web_port,
            internal_search_port=internal_port,
            tasks=ctx.tasks,
            params=engine_params,
            logger=self.logger,
        ):
            if isinstance(event, SearchComplete):
                ctx.all_results = event.all_results
                ctx.search_results = {
                    "results": event.all_results,
                    "summary": event.summary,
                    "internal_count": event.summary.get("internal_count", 0),
                    "external_count": event.summary.get("external_count", 0),
                }

        # 兜底：若未收到 SearchComplete（不应发生），保空结果
        if ctx.search_results is None:
            ctx.search_results = {
                "results": [],
                "summary": {
                    "internal_count": 0,
                    "external_count": 0,
                    "total_results": 0,
                    "key_sources": [],
                },
                "internal_count": 0,
                "external_count": 0,
            }
            ctx.all_results = []

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
                from novamind.core.database.database import get_db_session
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

    def _extract_key_sources(self, results: List[Dict[str, Any]]) -> List[str]:
        """提取关键来源（委托 engines/deep_research 纯函数）。"""
        return _extract_key_sources_fn(results)

    def _format_search_context(self, results: List[Dict[str, Any]]) -> str:
        """格式化检索结果为上下文（委托 engines/deep_research 纯函数，内部清理防注入）。"""
        return _format_search_context_fn(results)

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
        """综合信息生成报告（非流式，薄委托 DeepResearchEngine.synthesize_report）。

        feature 入口 sanitize query/topic；引擎自 results 格式化 context。
        """
        safe_query = _sanitize_user_input(query)
        safe_topic = _sanitize_user_input(research_topic)
        llm = await self._get_llm_client(user_id, llm_model)
        results = search_results.get("results", [])
        key_sources = search_results.get("summary", {}).get("key_sources", [])
        return await self._engine.synthesize_report(
            llm, self._prompt_provider,
            query=safe_query,
            research_topic=safe_topic,
            results=results,
            key_sources=key_sources,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
        )

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
        """综合信息生成报告（流式，薄委托 DeepResearchEngine.synthesize_report_stream）。

        feature 入口 sanitize query/topic（topic sanitize 失败降级原始值）；context 由
        调用方预格式化（stream 路径在调用前已格式化），引擎直接消费。
        """
        safe_query = _sanitize_user_input(query)
        try:
            safe_topic = _sanitize_user_input(research_topic)
        except Exception:
            self.logger.warning("research_topic sanitize 失败，使用原始值", topic=research_topic)
            safe_topic = research_topic or ""
        llm = await self._get_llm_client(user_id, llm_model)
        async for chunk in self._engine.synthesize_report_stream(
            llm, self._prompt_provider,
            query=safe_query,
            research_topic=safe_topic,
            context=context,
            key_sources=key_sources,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
        ):
            yield chunk
