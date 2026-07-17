from abc import abstractmethod, ABC
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, AsyncGenerator
import asyncio

import httpx

# 代理控制哨兵：表示「从环境变量继承代理」（httpx 默认行为）。
# 与显式 None / ""（禁用代理）区分开，避免把「未配置」和「显式禁用」混为一谈。
PROXY_INHERIT: Any = object()


def build_openai_http_client(
    timeout: int,
    max_connections: int,
    proxy: Any = PROXY_INHERIT,
) -> httpx.AsyncClient:
    """构建传给 OpenAI SDK 的 httpx.AsyncClient，支持显式代理控制。

    proxy 语义：
      - PROXY_INHERIT（默认）：从环境变量继承代理（HTTP_PROXY / HTTPS_PROXY / ALL_PROXY
        等）。保持与未传入 http_client 时一致的默认行为，避免影响依赖环境代理的存量配置。
      - None 或 ""：显式禁用代理，设 trust_env=False，不读取环境代理。用于直连国内服务商
        （如阿里云 DashScope）时绕开为访问境外端点而配置的本地代理。
      - str（代理 URL）：使用指定代理。

    Args:
        timeout: 请求超时（秒）。
        max_connections: 最大连接数。
        proxy: 代理配置，见上方语义说明。

    Returns:
        配置好代理语义的 httpx.AsyncClient。
    """
    client_kwargs: Dict[str, Any] = {
        "timeout": httpx.Timeout(timeout, connect=10.0),
        "limits": httpx.Limits(max_connections=max_connections),
    }
    if proxy is PROXY_INHERIT:
        # 继承环境变量：不设置 proxy / trust_env，沿用 httpx 默认。
        pass
    elif proxy in (None, ""):
        # 显式禁用代理：不再读取 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY 等环境变量。
        client_kwargs["trust_env"] = False
    else:
        # 使用指定代理 URL。
        client_kwargs["proxy"] = proxy
    return httpx.AsyncClient(**client_kwargs)


@dataclass
class StreamChunk:
    """流式输出统一块——thinking 模式适配层（中转站）的核心类型

    将 Qwen 的 reasoning_content / content 两种字段统一为
    type="reasoning" 或 type="content" 的 StreamChunk，
    上层代码无需关心底层模型是否开启 thinking。
    """
    type: str   # "content" | "reasoning"
    text: str


@dataclass
class LLMResponse:
    """非流式 LLM 结构化响应"""
    content: str
    reasoning: str | None = None


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
    tool_calls: List[ToolCall] | None
    finish_reason: str  # "stop" | "tool_calls"
    usage: Dict[str, int] | None = None
    reasoning: str | None = None


class BaseLLM(ABC):
    """
    LLM 客户端基类

    约束所有 LLM 协议实现的统一接口规范。
    每种协议（OpenAI/Anthropic/Transformers）独立实现此类。
    """

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
        response_format: Optional[Dict[str, Any]] = None,
        enable_thinking: bool = False,
    ) -> str:
        """
        生成文本

        Args:
            prompt: 提示词（字符串或消息列表）
            max_tokens: 最大生成 token 数
            temperature: 温度参数
            top_p: top_p 参数
            response_format: 响应格式约束（如 {"type": "json_object"}），不支持时忽略

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
        """
        支持工具调用的文本生成

        Args:
            prompt: 提示词（字符串或消息列表）
            tools: OpenAI function calling 格式的工具列表
            max_tokens: 最大生成 token 数
            temperature: 温度参数
            top_p: top_p 参数
            tool_choice: 工具选择策略，"auto"/"none"/"required"

        Returns:
            LLMResponseWithTools: 包含 content、tool_calls、finish_reason
        """
        raise NotImplementedError("此 LLM 后端不支持工具调用")

    # ==================== Thinking 模式适配层（中转站） ====================

    async def generate_text_structured(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        response_format: Optional[Dict[str, Any]] = None,
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
    async def generate_embedding(self, text: str) -> List[float]:
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
        self, texts: list[str], batch_size: int = 20
    ) -> list[list[float]]:
        """
        批量生成文本的嵌入向量

        Args:
            texts: 输入文本列表
            batch_size: 批次大小

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
        import httpx
        async with self._get_lock():
            if self._http_client is None:
                self._http_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout, connect=10.0),
                    limits=httpx.Limits(max_connections=10),
                )
        return self._http_client

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
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
