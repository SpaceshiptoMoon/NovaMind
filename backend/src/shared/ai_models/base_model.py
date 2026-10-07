"""AI 模型基类定义：BaseLLM / BaseEmbedding / BaseRerank + 响应数据结构（StreamChunk / LLMResponse / ToolCall）。跨 LLM provider 统一抽象层。"""
import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class LLMCapabilities:
    """LLM 客户端生效能力集——调用侧协商的唯一依据。

    Attributes:
        tools: 是否支持工具调用（generate_with_tools 可用）。
        thinking: 是否支持思考模式（enable_thinking 参数有意义）。
    """

    tools: bool = False
    thinking: bool = False


def resolve_capabilities(llm: object) -> LLMCapabilities:
    """解析 LLM 实例的生效能力：客户端类默认 ← quirks 用户声明覆盖。

    duck-typing：不约束入参类型，任何带 capabilities/quirks 属性的对象均可
    （含测试桩）。quirks 中 supports_tools/supports_thinking 为 None（未声明）
    时不覆盖；显式声明（含 False）优先于类默认——声明 False 的语义是
    「该端点实测不支持」，即使协议本身支持。

    本函数放 base_model 而非 llm/quirks：base_model 引用 llm 包会经包初始化
    与 llm/__init__ 的 base_model import 撞环（LLMCapabilities 属接口层概念，
    归属基类模块；LLMQuirks 经 getattr 访问，无需 import）。

    Args:
        llm: LLM 客户端实例（BaseLLM 子类或行为兼容的测试桩）。

    Returns:
        生效能力集；实例缺 capabilities/quirks 属性时落全 False 兜底。
    """
    caps = getattr(llm, "capabilities", None)
    base = caps if isinstance(caps, LLMCapabilities) else LLMCapabilities()
    quirks = getattr(llm, "quirks", None)
    if quirks is None:
        return base
    overrides = {
        "tools": getattr(quirks, "supports_tools", None),
        "thinking": getattr(quirks, "supports_thinking", None),
    }
    resolved = {
        name: value if value is not None else getattr(base, name)
        for name, value in overrides.items()
    }
    return LLMCapabilities(**resolved)


def build_openai_http_client(
    timeout: int,
    max_connections: int,
) -> httpx.AsyncClient:
    """构建传给 OpenAI SDK 的 httpx.AsyncClient。

    Args:
        timeout: 请求超时（秒）。
        max_connections: 最大连接数。

    Returns:
        配置好超时与连接数的 httpx.AsyncClient（代理沿用 httpx 默认环境行为）。
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=10.0),
        limits=httpx.Limits(max_connections=max_connections),
    )


@dataclass
class StreamChunk:
    """流式输出统一块——thinking 模式适配层（中转站）的核心类型

    将 Qwen 的 reasoning_content / content 两种字段统一为
    type="reasoning" 或 type="content" 的 StreamChunk，
    上层代码无需关心底层模型是否开启 thinking。

    finish_reason 为可选结束标记：流末由驱动产出（OpenAI 兼容/Anthropic 流式
    结构化路径），缺失时消费方按 "stop" 兜底——截断语义（length）不丢。
    """
    type: str   # "content" | "reasoning" | "finish"
    text: str
    finish_reason: str | None = None


@dataclass
class LLMResponse:
    """非流式 LLM 结构化响应

    usage/finish_reason 为可选项：上游返回时填充（OpenAI 兼容非流式路径），
    纯文本委托路径（generate_text 只回 str）保持缺省——消费方按「缺失=上游
    未提供」处理，不猜值。
    """
    content: str
    reasoning: str | None = None
    usage: dict[str, int] | None = None
    finish_reason: str | None = None


@dataclass
class ToolCall:
    """LLM 工具调用"""
    id: str
    name: str
    arguments: str  # JSON 字符串


@dataclass
class LLMResponseWithTools:
    """LLM 带工具调用的响应"""
    content: str | None
    tool_calls: list[ToolCall] | None
    finish_reason: str  # "stop" | "tool_calls"
    usage: dict[str, int] | None = None
    reasoning: str | None = None


@dataclass
class ToolStreamEvent:
    """带工具调用的流式事件

    将底层 LLM（如 OpenAI 兼容）流式响应中的 content 增量、tool_call 增量、
    usage、finish_reason 统一为事件流。AgentLLM 等上层消费此事件流并翻译为
    自有的 StreamChunk，从而避免上层对具体 LLM 实现类（OpenAICompatibleLLM）
    做 isinstance 判断或访问其私有属性（_get_semaphore/client）。

    type 取值：
      - "content": 文本内容增量（content 字段）
      - "tool_call_start": 工具调用开始（tool_call_id, tool_name）
      - "tool_call_args": 工具参数增量（tool_call_id, tool_arguments_delta）
      - "tool_call_end": 一个工具调用完成（tool_call_id, tool_name, tool_arguments_delta 全量）
      - "done": 全部完成（usage, finish_reason）
    """
    type: str
    content: str = ""
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments_delta: str = ""
    usage: dict[str, int] | None = None
    finish_reason: str | None = None


class BaseLLM(ABC):
    """
    LLM 客户端基类

    约束所有 LLM 协议实现的统一接口规范。
    每种协议（OpenAI/Anthropic/Transformers）独立实现此类。
    """

    # 协议能力默认值：声明该协议实现类原生支持的能力面，调用侧经
    # resolve_capabilities 协商（quirks 用户声明可覆盖）。默认全 False，
    # 支持的子类覆写——新能力上线前保持保守声明，避免运行时炸 NotImplementedError。
    capabilities: LLMCapabilities = LLMCapabilities(tools=False, thinking=False)

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        timeout: int = 60,
        max_retries: int = 3,
        max_concurrent: int = 10,
        **kwargs,
    ):
        """初始化公共客户端字段与并发上限（Semaphore 延迟到事件循环内创建）。"""
        self.api_key = api_key
        self.base_url = base_url
        self.model = model_name
        self.timeout = timeout
        self.max_retries = max_retries
        self._semaphore = None
        self._max_concurrent = max_concurrent

    def _get_semaphore(self) -> asyncio.Semaphore:
        """延迟创建 Semaphore，确保在事件循环内初始化"""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
        return self._semaphore

    @abstractmethod
    async def generate_text(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        response_format: dict[str, Any] | None = None,
        enable_thinking: bool = False,
    ) -> str:
        """
        生成文本

        Args:
            prompt: 提示词（字符串或消息列表）
            max_tokens: 最大生成 token 数
            temperature: 温度参数
            top_p: top_p 参数
            response_format: 响应格式约束（如 {"type": "json_object"}），不支持时忽略。
                当前各实现生效情况：openai_compatible 透传给服务商生效；
                anthropic/ollama/transformers 收参但静默丢弃（约束退化为纯提示词）。
                调用方不应假设约束一定生效，JSON 输出须配提取容错
                （见 shared/utils/llm_response 与 shared/ai_models/llm/json_mode）。

        Returns:
            生成的文本
        """
        pass

    @abstractmethod
    async def generate_text_stream(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        enable_thinking: bool = False,
    ) -> AsyncGenerator[str, None]:
        """
        流式生成文本

        Args:
            prompt: 提示词（字符串或消息列表）
            max_tokens: 最大生成 token 数
            temperature: 温度参数
            top_p: top_p 参数

        Yields:
            str: 生成的文本片段
        """
        pass

    async def close(self) -> None:
        """
        关闭客户端连接，清理资源

        子类可覆盖此方法以实现特定的清理逻辑
        """
        pass

    async def generate_with_tools(
        self,
        prompt: str | list,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.8,
        tool_choice: str = "auto",
        enable_thinking: bool = False,
    ) -> "LLMResponseWithTools":
        """支持工具调用的文本生成

        Args:
            prompt: 提示词（字符串或消息列表）
            tools: OpenAI function calling 格式的工具列表
            max_tokens: 最大生成 token 数
            temperature: 温度参数
            top_p: top_p 参数
            tool_choice: 工具选择策略，"auto"/"none"/"required"

        Returns:
            LLMResponseWithTools: 包含 content、tool_calls、finish_reason

        Raises:
            NotImplementedError: 传入非空工具但后端未实现工具调用。
        """
        if not tools:
            # 纯文本路径委托 generate_text：无工具时任何协议都应可用，
            # 上层（agent_engine 无工具路径）统一走本方法，不因协议缺工具
            # 实现而炸（历史：Transformers/Ollama 纯文本对话报「不支持工具调用」）。
            content = await self.generate_text(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                enable_thinking=enable_thinking,
            )
            return LLMResponseWithTools(content=content, tool_calls=None, finish_reason="stop")
        raise NotImplementedError("此 LLM 后端不支持工具调用")

    async def generate_with_tools_stream(
        self,
        prompt: str | list,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.8,
        tool_choice: str = "auto",
        enable_thinking: bool = False,
    ) -> AsyncGenerator[ToolStreamEvent, None]:
        """支持工具调用的流式生成。

        无工具时委托 generate_text_stream（任何协议都应可用的纯文本流式路径）；
        有工具时默认不支持（抛 NotImplementedError），支持原生流式工具调用的
        后端（如 OpenAICompatibleLLM）覆盖此方法。上层（AgentLLM）捕获
        NotImplementedError 后降级为非流式。
        """
        if not tools:
            async for chunk in self.generate_text_stream(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                enable_thinking=enable_thinking,
            ):
                yield ToolStreamEvent(type="content", content=chunk)
            yield ToolStreamEvent(type="done", finish_reason="stop")
            return
        raise NotImplementedError("此 LLM 后端不支持流式工具调用")

    # ==================== Thinking 模式适配层（中转站） ====================

    async def generate_text_structured(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        response_format: dict[str, Any] | None = None,
        enable_thinking: bool = False,
    ) -> "LLMResponse":
        """非流式结构化生成——默认委托给 generate_text()

        子类（如 OpenAICompatibleLLM）可覆盖以提取 reasoning_content。
        """
        content = await self.generate_text(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            response_format=response_format,
            enable_thinking=enable_thinking,
        )
        return LLMResponse(content=content)

    async def generate_text_stream_structured(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        enable_thinking: bool = False,
    ) -> AsyncGenerator["StreamChunk", None]:
        """流式结构化生成——默认委托给 generate_text_stream()

        将纯文本块封装为 StreamChunk(type="content")，
        子类（如 OpenAICompatibleLLM）可覆盖以分离 reasoning/content。
        """
        async for chunk in self.generate_text_stream(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            enable_thinking=enable_thinking,
        ):
            yield StreamChunk(type="content", text=chunk)


class BaseEmbedding(ABC):
    """
    Embedding 客户端基类

    约束所有 Embedding 协议实现的统一接口规范。
    每种协议（OpenAI/Local/Transformers）独立实现此类。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        expected_dimension: int | None = None,
        timeout: int = 60,
        max_retries: int = 3,
        max_concurrent: int = 5,
        **kwargs,
    ):
        """初始化公共客户端字段、可选期望维度与并发上限（同步原语延迟到事件循环内创建）。"""
        self.api_key = api_key
        self.base_url = base_url
        self.model = model_name
        self.expected_dimension = expected_dimension
        self.timeout = timeout
        self.max_retries = max_retries
        self._semaphore = None
        self._max_concurrent = max_concurrent
        self._http_client_lock = None

    def _get_lock(self) -> asyncio.Lock:
        """延迟创建 Lock，确保在事件循环内初始化"""
        if self._http_client_lock is None:
            self._http_client_lock = asyncio.Lock()
        return self._http_client_lock

    def _get_semaphore(self) -> asyncio.Semaphore:
        """延迟创建 Semaphore，确保在事件循环内初始化"""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
        return self._semaphore

    @abstractmethod
    async def generate_embedding(self, text: str) -> list[float]:
        """
        生成单个文本的嵌入向量

        Args:
            text: 输入文本

        Returns:
            嵌入向量
        """
        pass

    @abstractmethod
    async def generate_embeddings_batch(
        self, texts: list[str], batch_size: int | None = None
    ) -> list[list[float]]:
        """
        批量生成文本的嵌入向量

        Args:
            texts: 输入文本列表
            batch_size: 批次大小；None 时使用客户端构造器配置的默认批次

        Returns:
            嵌入向量列表
        """
        pass

    async def close(self) -> None:
        """
        关闭客户端连接，清理资源

        子类可覆盖此方法以实现特定的清理逻辑
        """
        pass


class BaseRerank(ABC):
    """
    Rerank 客户端基类

    约束所有 Rerank 服务商实现的统一接口规范。
    每个服务商独立实现此类，确保调用方式一致。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        timeout: int = 30,
        max_retries: int = 3,
        max_concurrent: int = 5,
    ):
        """初始化公共客户端字段与并发上限（HTTP 客户端与锁延迟到事件循环内创建）。"""
        self.api_key = api_key
        self.base_url = base_url
        self.model = model_name
        self.timeout = timeout
        self.max_retries = max_retries
        self._semaphore = None
        self._max_concurrent = max_concurrent
        self._http_client = None
        self._http_client_lock = None

    def _get_lock(self) -> asyncio.Lock:
        """延迟创建 Lock，确保在事件循环内初始化"""
        if self._http_client_lock is None:
            self._http_client_lock = asyncio.Lock()
        return self._http_client_lock

    def _get_semaphore(self) -> asyncio.Semaphore:
        """延迟创建 Semaphore，确保在事件循环内初始化"""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
        return self._semaphore

    async def _get_http_client(self):
        """获取 HTTP 客户端（延迟初始化，子类共享）"""
        async with self._get_lock():
            if self._http_client is None:
                self._http_client = build_openai_http_client(
                    timeout=self.timeout,
                    max_connections=10,
                )
        return self._http_client

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """
        对文档列表进行重排序

        Args:
            query: 查询文本
            documents: 待排序的文档文本列表
            top_k: 返回前 K 个结果

        Returns:
            统一返回格式: [{"index": int, "relevance_score": float}, ...]
            - index: 原始 documents 列表中的索引
            - relevance_score: 相关性分数（注意：不同实现返回的分数范围可能不同，
              API 服务通常返回 0-1 归一化分数，CrossEncoder 本地模型返回原始分数）

        Raises:
            RerankError: 重排序调用失败时抛出
        """
        pass

    async def close(self) -> None:
        """关闭客户端连接，清理资源"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
