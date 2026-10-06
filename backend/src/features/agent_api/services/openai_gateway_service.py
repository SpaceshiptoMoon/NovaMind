"""OpenAI 兼容网关服务：模型清单 + chat/completions 编排。

网关把用户已配置的 LLM（ModelConfigService 公共面）以 OpenAI 协议对外暴露。
职责边界：
- 错误翻译收敛于此：ModelProviderError → OpenAI 错误信封（HTTP 语义归 feature 层）；
- 能力协商与工作台同语义（resolve_capabilities），失败方向安全；
- 直连已配模型名，不做别名映射。
"""
from __future__ import annotations

import time
import traceback
import uuid
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.ai_models.base_model import BaseLLM, LLMCapabilities, resolve_capabilities
from novamind.shared.ai_models.errors import (
    ModelProviderError,
    ModelQuotaError,
    ModelRateLimitError,
    translate_provider_error,
)
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# OpenAI 错误 type 惯例值（SDK 据此决定重试策略与错误归类）
_TYPE_INVALID_REQUEST = "invalid_request_error"
_TYPE_RATE_LIMIT = "rate_limit_error"
_TYPE_API_ERROR = "api_error"


def provider_error_to_openai(exc: ModelProviderError) -> tuple[int, dict]:
    """ModelProviderError → (HTTP 状态码, OpenAI 错误信封)。

    映射依据官方语义：429→rate_limit_error（SDK 自动退避重试）、
    额度类→insufficient_quota（OpenAI 同款 code）、5xx→api_error、
    其余 4xx→invalid_request_error。
    """
    status = exc.status_code
    if isinstance(exc, ModelRateLimitError):
        err_type, code = _TYPE_RATE_LIMIT, "rate_limit_exceeded"
        status = 429
    elif isinstance(exc, ModelQuotaError):
        err_type, code = _TYPE_INVALID_REQUEST, "insufficient_quota"
        if status is None:
            status = 400
    elif status is not None and status >= 500:
        err_type, code = _TYPE_API_ERROR, "provider_error"
    else:
        err_type, code = _TYPE_INVALID_REQUEST, "provider_error"
        if status is None:
            status = 502
    return status, {
        "error": {
            "message": exc.message,
            "type": err_type,
            "param": None,
            "code": code,
        }
    }


def _normalize_usage(usage: dict[str, int] | None) -> dict[str, int]:
    """内部 usage 键 → OpenAI usage 键（prompt/completion/total_tokens）。

    上游键名两套并存：内部客户端装 input_tokens/output_tokens（Anthropic
    惯例），OpenAICompatibleLLM 部分路径装 prompt_tokens/completion_tokens
    （OpenAI 惯例）——两套都认，缺省补 0。
    """
    if not usage:
        return {}
    return {
        "prompt_tokens": usage.get(
            "input_tokens", usage.get("prompt_tokens", 0)
        ),
        "completion_tokens": usage.get(
            "output_tokens", usage.get("completion_tokens", 0)
        ),
        "total_tokens": usage.get("total_tokens", 0),
    }


def _tool_calls_to_openai(tool_calls: list) -> list[dict]:
    """内部 ToolCall → OpenAI message.tool_calls 形状。"""
    return [
        {
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.name, "arguments": tc.arguments},
        }
        for tc in tool_calls
    ]


class GatewayRequestError(Exception):
    """网关请求级错误（客户端问题：模型不存在/能力不满足/参数不合法）。

    携带 OpenAI 错误信封所需字段，路由层据此返回 HTTP 错误响应。
    """

    def __init__(self, status_code: int, message: str, err_type: str, code: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.err_type = err_type
        self.code = code

    def to_body(self) -> dict:
        return {
            "error": {
                "message": self.message,
                "type": self.err_type,
                "param": None,
                "code": self.code,
            }
        }


class OpenAiGatewayService:
    """OpenAI 兼容网关编排服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _resolve_llm_client(
        self, user_id: int, model: str
    ) -> tuple[BaseLLM, LLMCapabilities]:
        """按模型名解析客户端 + 能力协商（网关所有调用的公共前置）。

        Raises:
            GatewayRequestError: 模型配置不存在（404 model_not_found）。
        """
        from novamind.features.user.services.model_config_service import ModelConfigService

        try:
            client = await ModelConfigService(self.session).get_llm_client_by_model(
                user_id, model
            )
        except Exception as e:
            from novamind.features.user.exceptions import ModelConfigNotFoundError

            if isinstance(e, ModelConfigNotFoundError):
                raise GatewayRequestError(
                    404,
                    f"模型 {model} 未配置或不可用——请在 NovaMind 模型配置页添加后重试",
                    _TYPE_INVALID_REQUEST,
                    "model_not_found",
                ) from e
            raise
        return client, resolve_capabilities(client)

    @staticmethod
    def _negotiate(
        client_caps: LLMCapabilities,
        tools: list[dict] | None,
        enable_thinking: bool,
        model: str,
    ) -> tuple[list[dict] | None, bool]:
        """能力协商裁决：tools 不支持显式报错，thinking 不支持静默关闭。

        tools 静默剥离 = 外部客户端期待 tool_calls 却永远等不到（错误结果）；
        thinking 静默关闭 = 纯能力缺失退化（安全方向）——与工作台同语义。

        Raises:
            GatewayRequestError: 请求 tools 但模型不支持（400）。
        """
        if tools and not client_caps.tools:
            raise GatewayRequestError(
                400,
                f"模型 {model} 不支持工具调用（function calling）——请移除 tools 参数或更换模型",
                _TYPE_INVALID_REQUEST,
                "tools_not_supported",
            )
        return tools, enable_thinking and client_caps.thinking

    async def list_models(self, user_id: int) -> dict:
        """列出当前用户已配置的 LLM 模型（OpenAI /v1/models 响应形状）。

        同名模型多协议配置时按模型名去重（created_at 取最早）。

        Returns:
            {"object": "list", "data": [{"id", "object", "created", "owned_by"}]}
        """
        from novamind.features.user.services.model_config_service import ModelConfigService

        configs = await ModelConfigService(self.session).list_configs(user_id, "llm")
        seen: dict[str, int] = {}
        for item in configs.items:
            created = int(item.created_at.timestamp()) if item.created_at else 0
            if item.model not in seen or created < seen[item.model]:
                seen[item.model] = created
        data = [
            {"id": model, "object": "model", "created": created, "owned_by": "novamind"}
            for model, created in sorted(seen.items())
        ]
        return {"object": "list", "data": data}

    async def create_chat_completion(self, user_id: int, req) -> dict:
        """非流式 chat completion：client 解析 → 协商 → 调用 → OpenAI 响应组装。

        Raises:
            GatewayRequestError: 模型不存在/能力不满足（客户端错误）。
            ModelProviderError: 上游模型调用失败（路由层转 OpenAI 错误）。
        """
        messages = [m.to_openai_dict() for m in req.messages]
        client, caps = await self._resolve_llm_client(user_id, req.model)
        tools, enable_thinking = self._negotiate(
            caps, req.tools, req.enable_thinking, req.model
        )

        call_kwargs: dict[str, Any] = {
            "max_tokens": req.max_tokens if req.max_tokens is not None else 4096,
            "temperature": req.temperature if req.temperature is not None else 0.7,
            "top_p": req.top_p if req.top_p is not None else 0.8,
            "enable_thinking": enable_thinking,
        }

        started = time.perf_counter()
        try:
            if tools:
                result = await client.generate_with_tools(
                    messages, tools=tools, tool_choice=req.tool_choice or "auto",
                    **call_kwargs,
                )
                message: dict[str, Any] = {"role": "assistant", "content": result.content}
                if result.reasoning:
                    message["reasoning_content"] = result.reasoning
                if result.tool_calls:
                    message["tool_calls"] = _tool_calls_to_openai(result.tool_calls)
                finish_reason = result.finish_reason
                usage = _normalize_usage(result.usage)
            else:
                response = await client.generate_text_structured(messages, **call_kwargs)
                message = {"role": "assistant", "content": response.content}
                if response.reasoning:
                    message["reasoning_content"] = response.reasoning
                # usage/finish_reason 如实透传（LLMResponse 可选携带，纯文本
                # 委托路径缺失时保持 OpenAI 惯例缺省）
                finish_reason = response.finish_reason or "stop"
                usage = _normalize_usage(response.usage)
        except ModelProviderError:
            raise
        except NotImplementedError as e:
            raise GatewayRequestError(
                400,
                f"模型 {req.model} 的协议实现不支持此调用方式（流式工具/structured 缺失）",
                _TYPE_INVALID_REQUEST,
                "not_implemented",
            ) from e
        except Exception as e:
            translated = translate_provider_error(e, model=req.model)
            if isinstance(translated, ModelProviderError):
                raise translated from e
            raise
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "网关 chat completion 完成",
            user_id=user_id, model=req.model, stream=False,
            finish_reason=finish_reason, duration_ms=duration_ms,
        )

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": usage,
        }

    # ==================== 流式（stream=true） ====================

    async def prepare_stream(self, user_id: int, req):
        """流式前置：所有验证在响应头发出前完成（200 定格后无法再改 HTTP 状态码）。

        Returns:
            dict 上下文（client/messages/参数），供 stream_chat_completion 闭包消费。

        Raises:
            GatewayRequestError / ModelProviderError: 经路由边界转 HTTP 错误。
        """
        messages = [m.to_openai_dict() for m in req.messages]
        client, caps = await self._resolve_llm_client(user_id, req.model)
        tools, enable_thinking = self._negotiate(
            caps, req.tools, req.enable_thinking, req.model
        )
        # 流式工具需要协议实现覆写 generate_with_tools_stream（如 Ollama 未实现），
        # 落到基类默认实现会对非空 tools 抛 NotImplementedError——SSE 已 200 定格，
        # 只能 yield error 事件。在 prepare 阶段 type 级预检，还来得及改状态码。
        # duck-typing 客户端（测试桩）无该方法属性时视为已实现（跳过预检）。
        if tools and getattr(type(client), "generate_with_tools_stream", None) is (
            BaseLLM.generate_with_tools_stream
        ):
            raise GatewayRequestError(
                400,
                f"模型 {req.model} 的协议不支持流式工具调用——请改用 stream=false",
                _TYPE_INVALID_REQUEST,
                "streaming_tools_not_supported",
            )
        return {
            "user_id": user_id,
            "model": req.model,
            "client": client,
            "messages": messages,
            "tools": tools,
            "tool_choice": req.tool_choice or "auto",
            "enable_thinking": enable_thinking,
            "max_tokens": req.max_tokens if req.max_tokens is not None else 4096,
            "temperature": req.temperature if req.temperature is not None else 0.7,
            "top_p": req.top_p if req.top_p is not None else 0.8,
        }

    @staticmethod
    def _sse(payload: dict) -> str:
        """单条 SSE 数据帧。"""
        import json

        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _chunk(
        model: str,
        delta: dict,
        finish_reason: str | None = None,
        usage: dict | None = None,
        chunk_id: str | None = None,
    ) -> dict:
        """构造 OpenAI chat.completion.chunk 形状。

        chunk_id：OpenAI 官方语义同一流内所有 chunk 共享同一 id，缺失时退化为
        每帧新 id（兼容旧调用方）。
        """
        chunk: dict[str, Any] = {
            "id": chunk_id or f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {"index": 0, "delta": delta, "finish_reason": finish_reason}
            ],
        }
        if usage is not None:
            chunk["usage"] = usage
        return chunk

    async def stream_chat_completion(self, ctx: dict):
        """SSE 事件流：内部 ToolStreamEvent/StreamChunk → OpenAI chunk 帧 + [DONE]。

        流中异常转 data: {"error": ...}（OpenAI 流式错误惯例）——200 已定格，
        不再抛 HTTP。reasoning 映射 delta.reasoning_content（DeepSeek/Qwen 惯例）。
        """
        client = ctx["client"]
        model = ctx["model"]
        # OpenAI 官方语义：同一流内所有 chunk 共享同一 id
        stream_id = f"chatcmpl-{uuid.uuid4().hex}"
        call_kwargs: dict[str, Any] = {
            "max_tokens": ctx["max_tokens"],
            "temperature": ctx["temperature"],
            "top_p": ctx["top_p"],
            "enable_thinking": ctx["enable_thinking"],
        }
        try:
            yield self._sse(self._chunk(model, {"role": "assistant", "content": ""}, chunk_id=stream_id))
            finish_reason = "stop"
            final_usage: dict = {}
            emitted_tool_calls = False
            if ctx["tools"]:
                async for event in client.generate_with_tools_stream(
                    ctx["messages"], tools=ctx["tools"],
                    tool_choice=ctx["tool_choice"], **call_kwargs,
                ):
                    if event.type == "content":
                        if event.content:
                            yield self._sse(self._chunk(model, {"content": event.content}, chunk_id=stream_id))
                    elif event.type == "reasoning":
                        if event.content:
                            yield self._sse(
                                self._chunk(model, {"reasoning_content": event.content}, chunk_id=stream_id)
                            )
                    elif event.type == "tool_call_start":
                        emitted_tool_calls = True
                        yield self._sse(self._chunk(model, {"tool_calls": [{
                            "index": 0, "id": event.tool_call_id, "type": "function",
                            "function": {"name": event.tool_name, "arguments": ""},
                        }]}, chunk_id=stream_id))
                    elif event.type == "tool_call_args":
                        yield self._sse(self._chunk(model, {"tool_calls": [{
                            "index": 0, "id": event.tool_call_id, "type": "function",
                            "function": {"arguments": event.tool_arguments_delta},
                        }]}, chunk_id=stream_id))
                    elif event.type == "done":
                        finish_reason = event.finish_reason or "stop"
                        if event.usage:
                            final_usage = _normalize_usage(event.usage)
                # OpenAI 语义：流末帧 finish_reason=tool_calls 表示"执行工具后
                # 回传结果"。部分上游（DashScope 兼容层）在工具场景也回 stop，
                # agent 框架据 finish_reason 判断是否执行工具——产出过 tool_call
                # 增量即归一化为 tool_calls；上游显式给出其他值（如 length 截断）
                # 则尊重上游。
                if emitted_tool_calls and finish_reason == "stop":
                    finish_reason = "tool_calls"
            else:
                async for chunk in client.generate_text_stream_structured(
                    ctx["messages"], **call_kwargs
                ):
                    if chunk.type == "reasoning" and chunk.text:
                        yield self._sse(self._chunk(model, {"reasoning_content": chunk.text}, chunk_id=stream_id))
                    elif chunk.type == "content" and chunk.text:
                        yield self._sse(self._chunk(model, {"content": chunk.text}, chunk_id=stream_id))
        except ModelProviderError as e:
            _, body = provider_error_to_openai(e)
            yield self._sse(body)
            yield "data: [DONE]\n\n"
            return
        except Exception as e:
            translated = translate_provider_error(e, model=model)
            if isinstance(translated, ModelProviderError):
                _, body = provider_error_to_openai(translated)
                yield self._sse(body)
                yield "data: [DONE]\n\n"
                return
            logger.error(
                "网关流式未归类异常", model=model, error=str(e),
                exc_info=traceback.format_exc(),
            )
            yield self._sse({
                "error": {"message": "服务器内部错误", "type": _TYPE_API_ERROR,
                          "param": None, "code": "internal_error"},
            })
            yield "data: [DONE]\n\n"
            return
        yield self._sse(self._chunk(model, {}, finish_reason=finish_reason, usage=final_usage, chunk_id=stream_id))
        yield "data: [DONE]\n\n"
