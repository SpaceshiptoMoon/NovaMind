"""
请求追踪中间件
为每个请求生成和传播 trace_id，支持分布式追踪
使用纯 ASGI 实现，避免 BaseHTTPMiddleware 导致的 SSE 流式响应缓冲问题
"""
import hashlib
import time
import uuid

from starlette.types import ASGIApp, Receive, Scope, Send, Message

from .structured_logging import get_logger, LoggingMiddleware

logger = get_logger(__name__)


class TraceIDMiddleware:
    """
    Trace ID 中间件（纯 ASGI 实现）

    功能：
    1. 为每个请求生成唯一的 trace_id
    2. 支持从请求头接收外部 trace_id（分布式追踪）
    3. 将 trace_id 注入到日志上下文
    4. 请求结束后清理上下文

    使用纯 ASGI 中间件而非 BaseHTTPMiddleware，
    避免 SSE 流式响应被缓冲的问题。
    """

    # 请求头中 trace_id 的键名
    TRACE_ID_HEADER = b"x-trace-id"
    TRACE_ID_HEADER_STR = "X-Trace-ID"
    X_REQUEST_ID_HEADER = b"x-request-id"
    X_REQUEST_ID_HEADER_STR = "X-Request-ID"

    # 跳过日志记录的路径前缀（支持路径参数匹配）
    SKIP_PATH_PREFIXES = ["/health", "/metrics", "/favicon.ico"]

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        ASGI 中间件入口

        Args:
            scope: ASGI scope 字典
            receive: ASGI receive 可调用对象
            send: ASGI send 可调用对象
        """
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # 从 scope 中提取 headers
        headers = dict(scope.get("headers", []))

        # 生成或获取 trace_id
        trace_id = self._get_or_generate_trace_id(headers)

        # 将 trace_id 注入到 scope state 中
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["trace_id"] = trace_id

        # 绑定 trace_id 到日志上下文
        LoggingMiddleware.bind_context(trace_id=trace_id)

        # 提取请求路径和方法
        path = scope.get("path", "")
        method = scope.get("method", "")
        should_log = self._should_log_request(path)

        start_time = time.time()

        if should_log:
            logger.info(
                "请求开始",
                endpoint=path,
                method=method,
            )

        async def send_with_trace_id(message: Message) -> None:
            """在响应头中注入 trace_id"""
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append(
                    (self.TRACE_ID_HEADER, trace_id.encode())
                )
                message["headers"] = headers

                # 记录请求完成
                if should_log:
                    duration_ms = (time.time() - start_time) * 1000
                    status_code = message.get("status", 0)
                    logger.info(
                        "请求完成",
                        endpoint=path,
                        method=method,
                        status=status_code,
                        duration_ms=f"{duration_ms:.2f}",
                    )
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace_id)
        except Exception as e:
            # 记录未处理的异常
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                "请求处理异常",
                endpoint=path,
                method=method,
                duration_ms=f"{duration_ms:.2f}",
                error_type=type(e).__name__,
                error_message=str(e),
            )
            raise
        finally:
            # 清理上下文（只解绑实际绑定的键）
            LoggingMiddleware.unbind_context("trace_id")
            # user_id 通过 bind_user_context 绑定，如果存在则解绑
            LoggingMiddleware.unbind_context("user_id")

    def _get_or_generate_trace_id(self, headers: dict) -> str:
        """
        获取或生成 trace_id

        优先级：
        1. 请求头中的 X-Trace-ID
        2. 请求头中的 X-Request-ID
        3. 生成新的 trace_id

        Args:
            headers: 请求头字典（bytes key）

        Returns:
            trace_id 字符串
        """
        # 尝试从请求头获取 trace_id
        trace_id = headers.get(self.TRACE_ID_HEADER)
        if trace_id:
            return trace_id.decode() if isinstance(trace_id, bytes) else trace_id

        # 尝试从请求头获取 request_id
        request_id = headers.get(self.X_REQUEST_ID_HEADER)
        if request_id:
            return request_id.decode() if isinstance(request_id, bytes) else request_id

        # 生成新的 trace_id
        return f"trace-{uuid.uuid4().hex[:16]}"

    def _should_log_request(self, path: str) -> bool:
        """
        判断是否应该记录该请求

        支持路径参数匹配（前缀匹配），
        如 /health 匹配 /health、/health/check 等。

        Args:
            path: 请求路径

        Returns:
            是否记录该请求
        """
        for skip_prefix in self.SKIP_PATH_PREFIXES:
            if path == skip_prefix or path.startswith(skip_prefix + "/"):
                return False
        return True


def get_trace_id(request) -> str:
    """
    从请求中获取 trace_id

    Args:
        request: HTTP 请求对象

    Returns:
        trace_id 字符串
    """
    return getattr(request.state, "trace_id", "no-trace")


def bind_user_context(user_id: str | int | None = None) -> None:
    """
    绑定用户上下文到日志

    Args:
        user_id: 用户 ID（如果提供）
    """
    if user_id is not None:
        # 使用哈希匿名化用户 ID，避免短 ID 暴露完整值
        user_id_str = str(user_id)
        anonymous_id = f"u-{hashlib.sha256(user_id_str.encode()).hexdigest()[:12]}"
        LoggingMiddleware.bind_context(user_id=anonymous_id)
