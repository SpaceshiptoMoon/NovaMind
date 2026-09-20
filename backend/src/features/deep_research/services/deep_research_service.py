"""
深度研究核心服务

实现基于 RAG 的深度研究功能，支持动态选择内部/外部搜索
"""

import asyncio
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Optional

from novamind.core.middleware.structured_logging import get_logger
from novamind.core.ws import envelope

# 纯检索辅助函数自 engines/deep_research 反向引用（feature -> engine 合法）。
# A-3：迭代循环（去重/充分性/外部决策）已迁入 DeepResearchEngine.search；
# feature 仅保留综合上下文/关键来源两个纯函数代理（synthesize 路径用）。
from novamind.engines.deep_research.engine import (
    extract_citations as _extract_citations_fn,
)
from novamind.engines.deep_research.engine import (
    extract_key_sources as _extract_key_sources_fn,
)
from novamind.engines.deep_research.engine import (
    format_search_context as _format_search_context_fn,
)
from novamind.engines.deep_research.errors import EngineInvalidResearchQueryError
from novamind.engines.deep_research.types import (
    EngineResearchParams,
    IterationProgress,
    PlanStep,
    ResearchPlan,
    SearchComplete,
    SearchSource,
    StepType,
    TaskFailed,
    TaskFinding,
)
from novamind.features.deep_research.exceptions import (
    DeepResearchError,
    InvalidResearchQueryError,
    ResearchAccessDeniedError,
    ResearchFailedError,
    ResearchModeNotSupportedError,
    ResearchNotFoundError,
    ResearchRunningError,
    ResearchSpaceAccessDeniedError,
)
from novamind.features.deep_research.models.research_session import (
    ResearchMode,
    ResearchSession,
    ResearchStatus,
)
from novamind.features.deep_research.repository.research_repository import ResearchRepository
from novamind.features.deep_research.schemas.research_schema import (
    ResearchRequest,
)
from novamind.features.deep_research.services.plan_feedback_registry import (
    DECISION_ACCEPTED,
)
from novamind.features.knowledge_space.adapters.retrieval_adapter import HostRetrievalPort
from novamind.features.knowledge_space.services.search_service import SearchService
from novamind.shared.model_config_ports import ModelConfigPort
from novamind.shared.retrieval_port import RetrievalPort
from novamind.shared.utils.time_utils import now_china
from sqlalchemy.ext.asyncio import AsyncSession

# 研究模式参数映射（业务配置，留 feature；与 setting/yaml_config/config.py 重复）
RESEARCH_MODE_CONFIG = {
    ResearchMode.QUICK: {"depth": 2, "iterations": 3},
    ResearchMode.STANDARD: {"depth": 3, "iterations": 5},
    ResearchMode.DEEP: {"depth": 5, "iterations": 7},
}

# 计划规划轮次上限（deer-flow max_plan_iterations 对齐，默认 1：首轮计划可被
# EDIT_PLAN 修订一次，再编辑自动按现计划继续）。消费者是 feature 管线，不入引擎参数。
DEFAULT_MAX_PLAN_ITERATIONS = 1

# 计划确认等待超时（秒）；超时 auto-accept（见 PlanFeedbackRegistry）
PLAN_FEEDBACK_TIMEOUT_SECONDS = 300


def parse_plan_json(plan: dict) -> ResearchPlan | None:
    """DB plan JSON → ResearchPlan（v2 新形状 / v1 旧形状兼容读）。

    - v2：{"version": 2, "title", "thought", "has_enough_context", "steps": [...]}
    - v1（旧）：{"tasks": [{task_id, description, priority}]} → 全 research 步骤映射
    """
    if not isinstance(plan, dict):
        return None
    steps: list[PlanStep] = []
    if plan.get("version") == 2:
        for i, s in enumerate(plan.get("steps") or []):
            if not isinstance(s, dict):
                continue
            raw_type = str(s.get("step_type", "research")).lower()
            steps.append(PlanStep(
                step_id=str(s.get("step_id", f"step_{i + 1}")),
                title=str(s.get("title", "")),
                description=str(s.get("description", "")),
                step_type=StepType.PROCESSING if raw_type == "processing" else StepType.RESEARCH,
                need_search=bool(s.get("need_search", True)),
                execution_res=str(s.get("execution_res", "")),
            ))
        return ResearchPlan(
            title=str(plan.get("title", "")),
            thought=str(plan.get("thought", "")),
            has_enough_context=bool(plan.get("has_enough_context", False)),
            steps=steps,
            iteration=int(plan.get("iteration", 0)),
            background_investigation_results=list(plan.get("background_investigation_results") or []),
        )
    # v1 旧形状
    for i, t in enumerate(plan.get("tasks") or []):
        if not isinstance(t, dict):
            continue
        steps.append(PlanStep(
            step_id=str(t.get("task_id", f"step_{i + 1}")),
            title=str(t.get("title", t.get("description", ""))),
            description=str(t.get("description", "")),
            step_type=StepType.RESEARCH,
            need_search=True,
        ))
    return ResearchPlan(steps=steps) if steps else None


def plan_to_json(plan: ResearchPlan, background_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """ResearchPlan → DB plan JSON v2（execution_res 截 1000 字，background 复用/覆盖）。"""
    return {
        "version": 2,
        "title": plan.title,
        "thought": plan.thought,
        "has_enough_context": plan.has_enough_context,
        "iteration": plan.iteration,
        "background_investigation_results": (
            background_results if background_results is not None
            else plan.background_investigation_results
        ),
        "steps": [
            {
                "step_id": s.step_id,
                "title": s.title,
                "description": s.description,
                "step_type": s.step_type.value if isinstance(s.step_type, StepType) else str(s.step_type),
                "need_search": s.need_search,
                "execution_res": s.execution_res[:1000],
            }
            for s in plan.steps
        ],
    }


def _plan_to_event_data(plan: ResearchPlan) -> dict[str, Any]:
    """ResearchPlan → plan_generated 事件 data 的 plan 部分（不回填执行结果）。"""
    return {
        "title": plan.title,
        "thought": plan.thought,
        "has_enough_context": plan.has_enough_context,
        "iteration": plan.iteration,
        "steps": [
            {
                "step_id": s.step_id,
                "title": s.title,
                "description": s.description,
                "step_type": s.step_type.value if isinstance(s.step_type, StepType) else str(s.step_type),
                "need_search": s.need_search,
            }
            for s in plan.steps
        ],
    }


def plan_iteration_count(ctx: "ResearchContext") -> int:
    """当前计划轮次（ctx.plan 未生成时为 -1，即首轮前的初始值）。"""
    return ctx.plan.iteration if ctx.plan is not None else -1


# 报告风格指令块（deer-flow report_style 对齐；feature 侧枚举知识，预格式化为
# 指令文本注入引擎——str.format 无法条件分支，引擎只接纯字符串）
_STYLE_INSTRUCTIONS: dict[str, str] = {
    "default": "",
    "academic": (
        "Report style: ACADEMIC. Write with the rigor of a peer-reviewed journal "
        "article: precise terminology, methodological transparency, logical argument "
        "structure, complete objectivity, explicit limitations.\n\n"
    ),
    "popular_science": (
        "Report style: POPULAR SCIENCE. Write as an engaging science communicator: "
        "vivid analogies, relatable examples, storytelling techniques; accessible "
        "language without sacrificing accuracy.\n\n"
    ),
    "news": (
        "Report style: NEWS. Write as an investigative journalist: inverted pyramid "
        "structure, authoritative and accessible language, balanced perspectives, "
        "facts first.\n\n"
    ),
}


def _get_style_block(report_style: str) -> str:
    """报告风格 → 指令块（未知值归 default）。"""
    return _STYLE_INSTRUCTIONS.get(report_style, "")


def _format_findings_block(task_findings: list[dict[str, str]] | None) -> str:
    """任务 findings 列表 → reporter prompt 的 findings 块。"""
    if not task_findings:
        return "（无）"
    return "\n".join(
        f"- [{f.get('task_id', '')}] {f.get('finding', '')}" for f in task_findings
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
    # 可插拔数据源扩展（SourcesConfig 归并产物；默认与平铺路径等价）
    enabled_sources: list[str] | None = None
    extra_source_configs: dict[str, dict[str, Any]] | None = None


def _extract_research_params(request) -> ResearchParams:
    """从 ResearchRequest 中提取参数（归并 sources 嵌套段）。

    兼容规则：``sources.internal``/``sources.external`` 非空时覆盖同名平铺字段
    （internal_search/external_search）；``sources.enabled`` 透传为显式源组合；
    ``sources.extra`` 透传为扩展源配置段。旧请求（无 sources）归并结果与历史逐字段一致。
    """
    internal_config = request.internal_search
    external_config = request.external_search
    enabled_sources = None
    extra_source_configs = None
    sources = getattr(request, "sources", None)
    if sources is not None:
        if sources.internal is not None:
            internal_config = sources.internal
        if sources.external is not None:
            external_config = sources.external
        if sources.enabled:
            enabled_sources = list(sources.enabled)
        if sources.extra:
            extra_source_configs = dict(sources.extra)
    return ResearchParams(
        query=request.query,
        research_mode=request.research_mode,
        search_source=request.search_source,
        internal_config=internal_config,
        external_config=external_config,
        llm_config=request.llm,
        retrieval_top_k=internal_config.top_k,
        retrieval_weight=internal_config.vector_weight,
        enabled_sources=enabled_sources,
        extra_source_configs=extra_source_configs,
    )


def _extract_flow_policy(request) -> tuple:
    """从 ResearchRequest 提取流程策略（auto_accepted_plan/背景调查/报告风格）。

    非流式无双向通道，强制 auto_accepted_plan=True（调用方按 stream 与否传值）。
    """
    return (
        bool(getattr(request, "auto_accepted_plan", True)),
        bool(getattr(request, "enable_background_investigation", True)),
        str(getattr(request, "report_style", "default") or "default"),
    )


@dataclass
class ResearchContext:
    """研究管线上下文（贯穿整个流程，替代多方法间的参数传递）"""
    # 流程标识
    research_id: int = 0
    session_id: str = ""
    space_id: int = 0
    user_id: int = 0
    params: ResearchParams | None = None
    mode_config: dict[str, Any] | None = None

    # 流程策略（deer-flow 对齐）
    auto_accepted_plan: bool = True
    enable_background_investigation: bool = True
    report_style: str = "default"

    # ORM 对象
    research: Any | None = None

    # 管线逐步填充
    research_topic: str | None = None
    plan: ResearchPlan | None = None
    background_results: list[dict[str, Any]] | None = None
    tasks: list[dict[str, Any]] | None = None
    search_results: dict[str, Any] | None = None
    report: str | None = None
    stats: dict[str, Any] | None = None

    # 流式检索统计（仅 research_stream 使用）
    all_results: list[dict[str, Any]] | None = None
    task_findings: list[dict[str, str]] | None = None
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
        model_config_service: ModelConfigPort | None = None,
        search_service: SearchService | None = None,
        es_client: Any | None = None,
        notification_port: Any | None = None,
    ):
        self.session = session
        self.research_repo = ResearchRepository(session)
        self._es_client = es_client
        self._model_config_service = model_config_service
        self._search_service = search_service
        self._search_port: RetrievalPort | None = None
        # A-3：web_search_port 按请求 provider 构造（build_web_search_port_for_provider），
        # 在 cleanup() 关闭。每请求一个 DeepResearchService 实例（见 api/dependencies）。
        self._web_search_port: Any | None = None
        # 可插拂数据源：本次请求构造的外部源适配器（可能多个，cleanup 全部关闭）
        self._web_source_adapters: list[Any] = []
        # 研究完成通知端口（独立会话版：流式可能取消回滚，不复用本 session）
        self._notification_port = notification_port

        self.logger = get_logger(__name__)

        # A-2/A-3：核心研究机制（查询分析/任务分解/迭代检索/综合）委托无状态 DeepResearchEngine；
        # prompt 经注入的 PromptManager 实例取模板（批次 2.3 起直用，不再经适配器）。
        from novamind.engines.deep_research import DeepResearchEngine
        from novamind.shared.prompts.prompt_manager import PromptManager

        self._prompt_provider = PromptManager()
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
        """清理外部数据源资源（关闭按请求构造的 web 适配器，含多次构造）"""
        for adapter in self._web_source_adapters:
            try:
                close = getattr(adapter, "close", None)
                if close is not None:
                    await close()
            except Exception as e:
                self.logger.warning("关闭 web 数据源适配器失败", error=str(e))
        self._web_source_adapters.clear()
        # 兼容旧字段（build_web_search_port_for_provider 直构路径已废，保留兜底）
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
        llm_model: str | None
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
        user_id: int | None = None,
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

    async def _resolve_search_llm(self, ctx: ResearchContext) -> tuple:
        """解析迭代检索反思用的 LLM（deer-flow 对齐观察驱动模式）。

        复用请求配置的 llm_model（用户选择什么模型，检索反思就用什么）。
        解析失败（未配置模型）返回 (None, None)——引擎降级为固定 query 循环，
        不让反思层阻断检索本体。
        """
        try:
            llm = await self._get_llm_client(ctx.user_id, ctx.params.llm_config.llm_model)
            return llm, self._prompt_provider
        except DeepResearchError as e:
            self.logger.warning("检索反思 LLM 解析失败，降级固定 query 模式", error=str(e))
            return None, None

    def _enabled_source_types(self, ctx: ResearchContext) -> list[str]:
        """解析启用的数据源类型列表。

        优先 ``request.sources.enabled``（显式指定，未来新源入口）；为空按
        ``search_source`` 预设组合映射：
        INTERNAL→[internal]、EXTERNAL→[external]、HYBRID→[internal, external]。
        """
        explicit = getattr(ctx.params, "enabled_sources", None)
        if explicit:
            return list(explicit)
        search_source = ctx.params.search_source
        if search_source == SearchSource.INTERNAL:
            return ["internal"]
        if search_source == SearchSource.EXTERNAL:
            return ["external"]
        return ["internal", "external"]

    def _build_source_bindings(self, ctx: ResearchContext) -> list[Any]:
        """按启用的数据源类型经注册表构造 ``SearchSourceBinding`` 列表。

        每源一个 ``SearchSourceContext``（租户上下文 + 请求级配置段 + 宿主依赖容器），
        工厂构造绑定实例（不跨请求复用）。注册表 build 抛的中立异常已在工厂内映射为
        feature 异常（DeepResearchError 子类），此处透传。
        """
        from novamind.engines.deep_research.sources import (
            SearchSourceBinding,
            SearchSourceContext,
        )
        from novamind.features.deep_research.adapters.source_registry import source_registry

        deps = {"retrieval_port": self.search_port, "session": self.session, "logger": self.logger}
        internal_cfg = ctx.params.internal_config
        external_cfg = ctx.params.external_config
        bindings = []
        for source_type in self._enabled_source_types(ctx):
            if source_type == "internal":
                config = internal_cfg.model_dump() if hasattr(internal_cfg, "model_dump") else {}
                top_k = internal_cfg.top_k
            elif source_type == "external":
                config = external_cfg.model_dump() if hasattr(external_cfg, "model_dump") else {}
                top_k = external_cfg.max_results
            else:
                # 扩展源：配置段取 sources.extra[source_type]；top_k 优先取配置内
                # 的独立 top_k，缺省回落内部检索 top_k
                config = dict((ctx.params.extra_source_configs or {}).get(source_type, {}))
                top_k = int(config.get("top_k") or internal_cfg.top_k)
            context = SearchSourceContext(
                space_id=ctx.space_id,
                user_id=ctx.user_id,
                config=config,
                deps=deps,
            )
            port = source_registry.build(source_type, context)
            if source_type == "external":
                # 记录 web 适配器供 cleanup（WebSearchSourceAdapter.close 委托底层 port）
                self._web_source_adapters.append(port)
            bindings.append(SearchSourceBinding(source_type=source_type, port=port, top_k=top_k))
        return bindings

    async def research(
        self,
        space_id: int,
        user_id: int,
        request: ResearchRequest,
    ) -> dict[str, Any]:
        """
        执行深度研究（非流式）

        管线（deer-flow 对齐）：create_session → analyze_topic → background
        investigation → analyze_plan（非流式无双向通道，强制 auto-accept，
        has_enough_context=true 时跳过检索）→ execute_search → synthesize。

        Args:
            space_id: 知识空间 ID
            user_id: 用户 ID
            request: 研究请求配置

        Returns:
            研究结果字典
        """
        if request.research_mode not in RESEARCH_MODE_CONFIG:
            raise ResearchModeNotSupportedError(request.research_mode)

        auto_accept, enable_bg, report_style = _extract_flow_policy(request)
        ctx = ResearchContext(
            space_id=space_id,
            user_id=user_id,
            params=_extract_research_params(request),
            mode_config=RESEARCH_MODE_CONFIG[request.research_mode],
            # 非流式 POST 无双向通道，计划确认不可用 → 强制 auto-accept
            auto_accepted_plan=True,
            enable_background_investigation=enable_bg,
            report_style=report_style,
        )

        try:
            await self._create_research_session(ctx)
            # DR-1: 提前触发 search_service 初始化，尽早暴露 ES 配置问题
            if "internal" in self._enabled_source_types(ctx):
                _ = self.search_port
            await self._analyze_and_save_topic(ctx)
            await self._plan_phase(ctx, feedback_registry=None, emit=None)
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
        feedback_registry: Any | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        执行深度研究（流式）

        Yield dict 事件（经 WS 推送，统一 envelope ``{"type": ..., "data": ...}``）。

        事件类型：
        - progress: 进度更新
        - plan_generated: 计划已生成（deer-flow human_feedback 对齐，仅
          auto_accepted_plan=false 且提供 feedback_registry 时挂起等待）
        - content: 报告内容片段
        - error: 错误信息
        - done: 研究完成

        Args:
            feedback_registry: 计划反馈注册表（routes 层构造注入；None=计划
                自动接受，不挂起）
        """
        if request.research_mode not in RESEARCH_MODE_CONFIG:
            raise ResearchModeNotSupportedError(request.research_mode)

        auto_accept, enable_bg, report_style = _extract_flow_policy(request)
        ctx = ResearchContext(
            space_id=space_id,
            user_id=user_id,
            params=_extract_research_params(request),
            mode_config=RESEARCH_MODE_CONFIG[request.research_mode],
            all_results=[],
            task_findings=[],
            auto_accepted_plan=auto_accept,
            enable_background_investigation=enable_bg,
            report_style=report_style,
        )

        try:
            # 0. 创建会话
            await self._create_research_session(ctx)
            # DR-1: 提前触发 search_service 初始化，尽早暴露 ES 配置问题
            if "internal" in self._enabled_source_types(ctx):
                _ = self.search_port

            # 1. 分析查询
            yield self._emit("progress", {
                "status": "analyzing",
                "current_step": "分析查询，提取研究主题",
                "progress_percent": 5.0,
                "completed_tasks": 0,
                "total_tasks": 0,
            })
            await self._analyze_and_save_topic(ctx)

            # 2. 规划阶段（背景调查 + 计划 + 可选确认循环；deer-flow planner/
            #    human_feedback 对齐）。feedback_registry=None 或 auto_accept 时
            #    不挂起，等价旧行为。
            wait_feedback = (
                not ctx.auto_accepted_plan and feedback_registry is not None
            )
            plan_gen = self._plan_phase_stream(
                ctx,
                feedback_registry=feedback_registry if wait_feedback else None,
            )
            async for event in plan_gen:
                yield event

            yield self._emit("progress", {
                "status": "planning",
                "current_step": f"研究主题：{ctx.research_topic}，计划就绪（{len(ctx.tasks or [])} 步）",
                "progress_percent": 20.0,
                "completed_tasks": 0,
                "total_tasks": len(ctx.tasks or []),
            })

            # 3. 逐任务执行检索（消费 DeepResearchEngine.search 事件流，yield 进度事件）
            # A-3：流式与非流式共用引擎迭代循环（按任务去重+充分性+catch-and-continue），
            # 消除原 research_stream 内联重复循环。单任务失败 → TaskFailed（catch-and-continue），
            # 与非流式行为统一（原流式此处无 per-task try/except，单任务失败会中止整个研究）。
            # deer-flow 对齐：注入 llm_client + prompt_provider 启用观察驱动模式
            # （每轮反思充分性 + query 演化 + 跨任务 finding 注入）；LLM 未配置时引擎
            # 自动降级固定 query 循环。
            total_steps = len(ctx.tasks) * ctx.mode_config["iterations"]
            task_desc_by_id = {
                str(t.get("task_id", "")): t.get("description", "")
                for t in ctx.tasks
            }
            engine_params = self._build_engine_params(ctx)
            sources = self._build_source_bindings(ctx)
            reflect_llm, reflect_provider = await self._resolve_search_llm(ctx)

            async for event in self._engine.search(
                sources=sources,
                tasks=ctx.tasks,
                params=engine_params,
                logger=self.logger,
                llm_client=reflect_llm,
                prompt_provider=reflect_provider,
            ):
                if isinstance(event, IterationProgress):
                    task_query = event.current_query or task_desc_by_id.get(event.task_id, "")
                    step_desc = (
                        f"检索源[{','.join(event.source_types) or '无'}]：{task_query[:50]}"
                    )
                    yield self._emit("progress", {
                        "status": "searching",
                        "current_step": step_desc,
                        "progress_percent": 20.0 + (event.step_count / total_steps) * 60.0,
                        "completed_tasks": event.step_count,
                        "total_tasks": total_steps,
                        "current_query": task_query,
                    })
                elif isinstance(event, TaskFinding):
                    # finding 已在引擎内注入后续任务 prompt；此处仅记录
                    self.logger.debug(
                        "研究任务 finding 已产出",
                        task_id=event.task_id,
                        finding_len=len(event.finding),
                    )
                elif isinstance(event, TaskFailed):
                    # 引擎已 log；feature 仅记录，catch-and-continue（与非流式统一）
                    self.logger.warning(
                        "研究任务检索失败（catch-and-continue）",
                        task_id=event.task_id,
                        error=event.error,
                    )
                elif isinstance(event, SearchComplete):
                    ctx.all_results = event.all_results
                    ctx.task_findings = event.task_findings
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
                ctx.task_findings = []

            # 4. 流式综合报告
            yield self._emit("progress", {
                "status": "synthesizing",
                "current_step": "综合信息生成报告",
                "progress_percent": 85.0,
                "completed_tasks": total_steps,
                "total_tasks": total_steps,
            })

            full_report = ""
            context_str = self._format_search_context(ctx.all_results)
            key_sources = ctx.search_results["summary"].get("key_sources", [])
            citations = _extract_citations_fn(ctx.all_results)
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
                report_style=ctx.report_style,
                task_findings=ctx.task_findings,
            )

            # WS 端不走 SSE 心跳包装：直接消费 LLM 原始 chunk 流，每个 chunk 包成 content 事件。
            # 过渡 SSE 端点（route 层 _stream_sse）由 dict→SSE 帧转换，不再依赖 SSE 心跳注释。
            async for chunk in raw_stream:
                full_report += chunk
                yield self._emit("content", {"chunk": chunk})

            # 5. 持久化并完成
            elapsed_seconds = int(time.time() - ctx.start_time)
            stats = {
                "elapsed_seconds": elapsed_seconds,
                "internal_searches": ctx.search_results.get("internal_count", 0),
                "external_searches": ctx.search_results.get("external_count", 0),
                "total_results": len(ctx.all_results),
            }
            await self.research_repo.update_search_results(ctx.research_id, ctx.all_results)
            await self.research_repo.complete_research(
                ctx.research_id, full_report, stats, key_sources, citations=citations
            )
            await self.session.commit()

            # commit 后通知发起用户（流式路径：唯一主动提醒渠道，前端无研究历史轮询）
            await self._notify_research_done(ctx, elapsed_seconds)

            yield self._emit("done", {
                "session_id": ctx.session_id,
                "final_report": full_report,
                "stats": stats,
                "sources": key_sources,
                "citations": citations,
            })

        except EngineInvalidResearchQueryError as e:
            # E2：引擎级查询错映射为 feature 异常，避免落 generic 分支丢具体信息
            yield self._emit("error", {
                "message": str(e),
                "session_id": ctx.session_id,
            })
            return
        except (asyncio.CancelledError, GeneratorExit):
            # 客户端断连（WS close）→ run_stream_to_ws aclose 触发；回滚事务，
            # 研究记录若已创建则标记 CANCELLED（用独立 recovery 会话避免污染原事务）
            research_id = ctx.research_id if "ctx" in locals() else 0
            session_id = ctx.session_id if "ctx" in locals() else ""
            self.logger.info("深度研究被客户端取消", research_id=research_id, session_id=session_id)
            try:
                await self.session.rollback()
            except Exception as rollback_err:
                self.logger.warning("取消时事务回滚失败", error=str(rollback_err))
            if research_id > 0:
                try:
                    from novamind.core.database.database import get_db_session
                    from sqlalchemy import select
                    async with get_db_session() as recovery_session:
                        # 先查询当前状态，避免覆盖已 COMMIT 的 COMPLETED 状态
                        result = await recovery_session.execute(
                            select(ResearchSession.status).where(ResearchSession.id == research_id)
                        )
                        current_status = result.scalar_one_or_none()
                        if current_status is not None and current_status == ResearchStatus.COMPLETED:
                            self.logger.warning(
                                "研究已处于 COMPLETED 状态，跳过 CANCELLED 标记",
                                research_id=research_id,
                                session_id=session_id,
                            )
                        else:
                            recovery_repo = ResearchRepository(recovery_session)
                            research = await recovery_repo.get_by_id(research_id)
                            if research:
                                research.mark_cancelled(reason="客户端断连")
                                await recovery_session.commit()
                except Exception as commit_err:
                    self.logger.error(
                        "标记研究取消时提交异常，需手动恢复",
                        research_id=research_id,
                        session_id=session_id,
                        recovery_error=str(commit_err),
                    )
            raise
        except DeepResearchError as e:
            await self._handle_research_error(ctx, e)
            yield self._emit("error", {"message": str(e), "session_id": ctx.session_id})
            return
        except Exception as e:
            await self._handle_research_error(ctx, e)
            yield self._emit("error", {"message": "研究执行失败，请稍后重试", "session_id": ctx.session_id})
            return

    # ==================== 私有方法 ====================

    def _emit(self, event_type: str, data: dict) -> dict:
        """构造统一事件 envelope（WS 推送用，取代 SSE 帧）"""
        return envelope(event_type, data)

    async def _analyze_query(self, query: str, user_id: int = None, llm_model: str = None) -> str:
        """分析查询，提取研究主题（薄委托 DeepResearchEngine.analyze_query）。

        feature 入口 sanitize（抛 InvalidResearchQueryError），引擎接已 sanitize 的 query。
        """
        safe_query = _sanitize_user_input(query)
        llm = await self._get_llm_client(user_id, llm_model)
        return await self._engine.analyze_query(llm, self._prompt_provider, safe_query)

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

    async def _plan_phase(
        self,
        ctx: ResearchContext,
        *,
        feedback_registry: Any | None,
        emit: Any | None,
    ) -> None:
        """规划阶段（deer-flow planner + human_feedback 对齐）。

        流程：背景调查（可关）→ analyze_plan → 可选计划确认循环（EDIT_PLAN 携
        feedback 重规划，iteration < DEFAULT_MAX_PLAN_ITERATIONS 才允许）→
        has_enough_context=true 时跳过检索（steps 置空）→ 持久化 plan JSON v2 +
        tasks 旧形状（详情接口兼容）。

        Args:
            ctx: 研究上下文
            feedback_registry: PlanFeedbackRegistry（None=不等待反馈，直接继续）
            emit: 事件发射函数（None=非流式静默）
        """
        depth = ctx.mode_config["depth"]
        llm = await self._get_llm_client(ctx.user_id, ctx.params.llm_config.llm_model)
        max_plan_iterations = DEFAULT_MAX_PLAN_ITERATIONS

        # 1. 背景调查（deer-flow background_investigator：单轮检索不调 LLM，失败降级空）
        ctx.background_results = []
        if ctx.enable_background_investigation:
            engine_params = self._build_engine_params(ctx)
            sources = self._build_source_bindings(ctx)
            bg_query = ctx.research_topic or ctx.params.query
            ctx.background_results = await self._engine.background_investigation(
                sources=sources,
                query=bg_query,
                params=engine_params,
            )
            self.logger.info(
                "背景调查完成",
                session_id=ctx.session_id,
                results_count=len(ctx.background_results),
            )

        # 2. 规划 + 可选确认循环
        feedback = ""
        while True:
            plan = await self._engine.analyze_plan(
                llm, self._prompt_provider,
                query=ctx.params.query,
                topic=ctx.research_topic or ctx.params.query,
                background_results=ctx.background_results,
                depth=depth,
                iteration=plan_iteration_count(ctx),
                feedback=feedback,
            )
            ctx.plan = plan
            await self._save_plan(ctx)

            has_enough = plan.has_enough_context or not plan.steps
            if has_enough or feedback_registry is None or emit is None:
                break  # 自动接受（或非流式/无事件通道）

            # 3. human_feedback：发计划事件并挂起等待（deer-flow 计划确认）
            emit("plan_generated", {
                "session_id": ctx.session_id,
                "plan": _plan_to_event_data(plan),
                "wait_feedback": True,
                "feedback_timeout_seconds": PLAN_FEEDBACK_TIMEOUT_SECONDS,
            })
            feedback_registry.register()
            decision, feedback = await feedback_registry.wait(timeout=PLAN_FEEDBACK_TIMEOUT_SECONDS)
            feedback_registry.clear()
            if decision == DECISION_ACCEPTED:
                break
            # EDIT_PLAN：超上限则按现计划继续（deer-flow max_plan_iterations 熔断）
            if plan_iteration_count(ctx) >= max_plan_iterations:
                self.logger.info(
                    "计划修订达上限，按当前计划继续",
                    session_id=ctx.session_id,
                    iteration=plan_iteration_count(ctx),
                )
                emit("progress", {
                    "status": "planning",
                    "current_step": "计划修订次数已达上限，按当前计划执行",
                    "progress_percent": 20.0,
                    "completed_tasks": 0,
                    "total_tasks": len(plan.steps),
                })
                break
            emit("progress", {
                "status": "planning",
                "current_step": "正在根据反馈修订计划",
                "progress_percent": 15.0,
                "completed_tasks": 0,
                "total_tasks": len(plan.steps),
            })

        # 4. has_enough_context：背景已足够 → 清空检索步骤，直接进报告
        if ctx.plan.has_enough_context and ctx.plan.steps:
            self.logger.info(
                "planner 判定背景信息已足够，跳过检索",
                session_id=ctx.session_id,
            )
            ctx.plan.steps = []
            await self._save_plan(ctx)

        # 5. tasks 旧形状同步（详情接口 research_tasks 兼容 + 检索循环消费）
        ctx.tasks = [
            {
                "task_id": s.step_id,
                "title": s.title,
                "description": s.description,
                "step_type": s.step_type.value if isinstance(s.step_type, StepType) else str(s.step_type),
                "need_search": s.need_search,
            }
            for s in ctx.plan.steps
        ]

    async def _save_plan(self, ctx: ResearchContext) -> None:
        """持久化 plan JSON v2。"""
        await self.research_repo.update_plan(
            ctx.research_id,
            plan_to_json(ctx.plan, background_results=ctx.background_results),
        )
        await self.session.flush()

    async def _plan_phase_stream(
        self,
        ctx: ResearchContext,
        *,
        feedback_registry: Any | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式版规划阶段：包装 _plan_phase，把 progress/plan_generated 事件透出。

        _plan_phase 的 emit 回调不能直接 yield（普通函数 vs 生成器），故用队列桥接：
        emit 把事件放进队列，本生成器逐个 yield；_plan_phase 返回后冲刷残余事件。
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def emit(event_type: str, data: dict) -> None:
            queue.put_nowait((event_type, data))

        plan_task = loop.create_task(
            self._plan_phase(ctx, feedback_registry=feedback_registry, emit=emit)
        )
        get_task: asyncio.Task | None = None
        try:
            while True:
                # done 回调尚未实现：轮询任务完成态 + 带超时取队列，避免死等
                get_task = loop.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {plan_task, get_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if get_task in done:
                    event_type, data = get_task.result()
                    yield self._emit(event_type, data)
                if plan_task in done:
                    # 冲刷队列中残余事件
                    while not queue.empty():
                        event_type, data = queue.get_nowait()
                        yield self._emit(event_type, data)
                    # 抛出规划阶段异常（如有）
                    plan_task.result()
                    break
                if plan_task.done():
                    # 任务已完但本轮 wait 只醒了 get_task：下轮循环会走 plan_task in done 分支
                    continue
        finally:
            if not plan_task.done():
                plan_task.cancel()
            if get_task is not None and not get_task.done():
                get_task.cancel()

    async def _execute_research_search(self, ctx: ResearchContext) -> None:
        """执行迭代检索（薄委托 DeepResearchEngine.search 事件流）。

        A-3：可复用迭代循环（按任务去重+充分性+catch-and-continue）已迁入引擎，
        feature 仅消费事件并在 SearchComplete 时填充 ctx.search_results。TaskStarted/
        IterationProgress/TaskFailed/TaskFinding 在非流式路径下静默（引擎内部已 log）。
        deer-flow 对齐：注入 llm_client + prompt_provider 启用观察驱动模式（query 演化
        + 充分性反思 + 跨任务 finding）；LLM 未配置时引擎自动降级固定 query 循环。
        """
        engine_params = self._build_engine_params(ctx)
        sources = self._build_source_bindings(ctx)
        reflect_llm, reflect_provider = await self._resolve_search_llm(ctx)

        async for event in self._engine.search(
            sources=sources,
            tasks=ctx.tasks,
            params=engine_params,
            logger=self.logger,
            llm_client=reflect_llm,
            prompt_provider=reflect_provider,
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
            report_style=ctx.report_style,
            task_findings=ctx.task_findings,
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

        # 持久化搜索结果 + citations（deer-flow Key Citations 对齐）
        all_results = ctx.search_results.get("results", [])
        await self.research_repo.update_search_results(ctx.research_id, all_results)
        key_sources = self._extract_key_sources(all_results)
        citations = _extract_citations_fn(all_results)
        await self.research_repo.complete_research(
            ctx.research_id, ctx.report, ctx.stats, key_sources, citations=citations
        )
        await self.session.commit()

        self.logger.info(
            "深度研究完成",
            session_id=ctx.session_id,
            elapsed_seconds=elapsed_seconds,
        )
        # commit 后通知发起用户（非流式路径）
        await self._notify_research_done(ctx, elapsed_seconds)

    async def _notify_research_done(self, ctx: ResearchContext, elapsed_seconds: int) -> None:
        """研究完成通知发起用户（commit 后调用；失败静默不影响主流程）。"""
        if self._notification_port is None:
            return
        topic = ctx.research_topic or ctx.params.query
        try:
            await self._notification_port.send(
                user_id=ctx.user_id,
                type="research_done",
                title=f"深度研究「{topic}」已完成",
                content=f"研究耗时 {elapsed_seconds} 秒，报告已生成，点击查看完整内容。",
                link=f"/home/workspace/research/{ctx.space_id}/history",
                extra_data={
                    "session_id": ctx.session_id,
                    "space_id": ctx.space_id,
                    "research_topic": topic,
                    "elapsed_seconds": elapsed_seconds,
                },
            )
        except Exception as e:
            self.logger.warning("研究完成通知发送失败", session_id=ctx.session_id, error=str(e))

    def _build_research_result(self, ctx: ResearchContext) -> dict[str, Any]:
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

    def _extract_key_sources(self, results: list[dict[str, Any]]) -> list[str]:
        """提取关键来源（委托 engines/deep_research 纯函数）。"""
        return _extract_key_sources_fn(results)

    def _format_search_context(self, results: list[dict[str, Any]]) -> str:
        """格式化检索结果为上下文（委托 engines/deep_research 纯函数，内部清理防注入）。"""
        return _format_search_context_fn(results)

    async def _synthesize_report(
        self,
        query: str,
        research_topic: str,
        search_results: dict[str, Any],
        max_tokens: int,
        temperature: float,
        top_p: float,
        user_id: int = None,
        llm_model: str = None,
        report_style: str = "default",
        task_findings: list[dict[str, str]] | None = None,
    ) -> tuple:
        """综合信息生成报告（非流式，薄委托 DeepResearchEngine.synthesize_report）。

        feature 入口 sanitize query/topic；引擎自 results 格式化 context。
        ``report_style``/``task_findings`` 预格式化为 style_block/findings_block 注入。
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
            style_block=_get_style_block(report_style),
            findings_block=_format_findings_block(task_findings),
        )

    async def _synthesize_report_stream(
        self,
        query: str,
        research_topic: str,
        context: str,
        key_sources: list[str],
        max_tokens: int,
        temperature: float,
        top_p: float,
        user_id: int = None,
        llm_model: str = None,
        report_style: str = "default",
        task_findings: list[dict[str, str]] | None = None,
    ) -> AsyncGenerator[str, None]:
        """综合信息生成报告（流式，薄委托 DeepResearchEngine.synthesize_report_stream）。

        feature 入口 sanitize query/topic（topic sanitize 失败降级原始值）；context 由
        调用方预格式化（stream 路径在调用前已格式化），引擎直接消费。
        ``report_style``/``task_findings`` 预格式化为 style_block/findings_block 注入。
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
            style_block=_get_style_block(report_style),
            findings_block=_format_findings_block(task_findings),
        ):
            yield chunk
