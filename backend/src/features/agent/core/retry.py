"""
Agent 重试工具

为 LLM 调用提供 jittered exponential backoff 重试机制，
区分瞬时错误（重试）和不可恢复错误（立即抛出）。
"""
import asyncio
import random
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# context overflow 特征字符串
_CONTEXT_OVERFLOW_PATTERNS = (
    "context_length_exceeded",
    "maximum context length",
    "context window",
    "too many tokens",
    "reduce the length",
    "token limit",
)


class ContextOverflowError(Exception):
    """LLM 因 token 超限拒绝请求，应触发压缩而非重试"""


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter_max: float = 0.5


def _is_retryable_error(exc: Exception) -> bool:
    """判断异常是否可重试"""
    status_code = getattr(exc, "status_code", None)

    # openai / httpx 瞬时错误
    if status_code in (429, 500, 502, 503):
        return True

    # 连接 / 超时类
    exc_type = type(exc).__name__
    if exc_type in (
        "ConnectError", "TimeoutException",
        "ConnectionError", "TimeoutError",
        "APITimeoutError", "APIConnectionError",
    ):
        return True

    return False


def _is_context_overflow(exc: Exception) -> bool:
    """判断是否为上下文溢出错误"""
    msg = str(exc).lower()
    return any(p in msg for p in _CONTEXT_OVERFLOW_PATTERNS)


def _is_non_retryable(exc: Exception) -> bool:
    """判断是否为明确不可重试的错误"""
    status_code = getattr(exc, "status_code", None)
    if status_code in (401, 403):
        return True

    exc_type = type(exc).__name__
    if exc_type in ("AuthenticationError", "BadRequestError", "ValueError"):
        return True

    return False


async def retry_llm_call(
    coro_factory: Callable[[], Coroutine],
    config: RetryConfig | None = None,
) -> Any:
    """带 jittered backoff 的重试包装

    Args:
        coro_factory: 零参异步 callable，每次重试调用一次
        config: 重试配置

    Returns:
        coro_factory 的返回值

    Raises:
        ContextOverflowError: token 超限，调用方应触发压缩
        Exception: 不可重试错误或重试耗尽后的最后一次异常
    """
    cfg = config or RetryConfig()
    last_exc: Exception | None = None

    for attempt in range(1, cfg.max_retries + 1):
        try:
            return await coro_factory()
        except Exception as exc:
            last_exc = exc

            if _is_context_overflow(exc):
                raise ContextOverflowError(str(exc)) from exc

            if _is_non_retryable(exc):
                raise

            if not _is_retryable_error(exc):
                raise

            if attempt >= cfg.max_retries:
                raise

            delay = min(cfg.base_delay * (2 ** (attempt - 1)), cfg.max_delay)
            jitter = random.uniform(0, cfg.jitter_max)
            total_delay = delay + jitter

            logger.warning(
                "LLM 调用失败，准备重试",
                attempt=attempt,
                max_retries=cfg.max_retries,
                delay=f"{total_delay:.1f}s",
                error=str(exc)[:200],
            )
            await asyncio.sleep(total_delay)

    raise last_exc  # 不应到达，但类型安全
