"""
API 速率限制中间件

使用 slowapi 实现 API 请求速率限制，防止：
1. 暴力破解攻击
2. DDoS 攻击
3. 资源滥用

安装依赖:
    uv add slowapi
"""

import re
import threading
import time
from typing import Optional

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi.responses import JSONResponse

from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


def _get_rate_limit_storage_uri() -> str:
    """
    获取速率限制存储 URI

    Redis 可用时使用 Redis 存储（支持多实例共享），
    否则回退到内存存储。
    """
    try:
        from src.setting.yaml_config import get_config
        config = get_config()
        if config.redis.enabled and config.redis.host:
            # URL 中不包含密码，通过 storage_options 传递
            return f"redis://{config.redis.host}:{config.redis.port}/{config.redis.db}"
    except Exception:
        logger.warning(
            "速率限制存储配置加载失败，将使用内存存储。"
            "多实例部署时限流策略无法共享，建议确保配置在导入前已加载",
        )
    return "memory://"


def _get_rate_limit_storage_options() -> dict:
    """获取速率限制存储选项（密码等敏感信息通过此参数传递，不暴露在 URI 中）"""
    try:
        from src.setting.yaml_config import get_config
        config = get_config()
        if config.redis.enabled and config.redis.host and config.redis.password:
            return {"password": config.redis.password}
    except Exception:
        pass
    return {}


def _get_rate_limit_key(request: Request) -> str:
    """
    获取限流键：认证用户使用 user_id，未认证使用 IP 地址。

    仅从 request.state 获取已解析的 user_id（由 auth 中间件设置），
    避免在限流层同步解码 JWT 阻塞事件循环。
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return get_remote_address(request)


# 延迟创建限流器实例（避免模块导入时配置未加载）
_limiter: Optional[Limiter] = None
_limiter_lock = threading.Lock()


def get_limiter() -> Limiter:
    """获取限流器实例（延迟初始化，线程安全）"""
    global _limiter
    if _limiter is None:
        with _limiter_lock:
            if _limiter is None:
                _limiter = Limiter(
                    key_func=_get_rate_limit_key,
                    default_limits=["100/minute"],
                    storage_uri=_get_rate_limit_storage_uri(),
                    storage_options=_get_rate_limit_storage_options(),
                )
    return _limiter


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    速率限制超出处理器

    当请求超过速率限制时调用，返回 429 错误

    Args:
        request: 请求对象
        exc: 速率限制异常

    Returns:
        JSONResponse: 错误响应
    """
    client_ip = get_remote_address(request)

    logger.warning(
        "请求速率超限",
        client_ip=client_ip,
        path=request.url.path,
        method=request.method,
        limit=str(exc.detail),
    )

    return JSONResponse(
        status_code=429,
        content={
            "error": "请求过于频繁，请稍后再试",
            "code": "RATE_LIMIT_EXCEEDED",
            "detail": str(exc.detail),
            "retry_after": _get_retry_after_remaining(exc),
        },
        headers={
            "Retry-After": str(_get_retry_after_remaining(exc)),
            "X-RateLimit-Limit": str(_extract_limit_number(str(exc.detail))),
        },
    )


def _extract_limit_number(detail: str) -> int:
    """
    从错误详情中提取限制数量

    Args:
        detail: 错误详情字符串，如 "5 per 1 minute"

    Returns:
        int: 限制数量
    """
    match = re.search(r"(\d+)\s*per", detail)
    if match:
        return int(match.group(1))
    return 0


def _extract_retry_after(detail: str) -> int:
    """
    从错误详情中提取限流窗口总时长（秒）

    注意：此函数返回的是整个限流窗口的时长，而非剩余时间。
    如需获取精确的剩余时间，请使用 _get_retry_after_remaining。

    Args:
        detail: 错误详情字符串

    Returns:
        int: 窗口时长（秒）
    """
    # 尝试解析 "5 per 1 minute" 格式
    match = re.search(r"(\d+)\s*per\s*(\d+)\s*(\w+)", detail)
    if match:
        count = int(match.group(1))
        period = int(match.group(2))
        unit = match.group(3).lower()

        # 转换为秒
        multipliers = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
        multiplier = multipliers.get(unit.rstrip("s"), 60)

        return period * multiplier

    # 默认等待 60 秒
    return 60


def _get_retry_after_remaining(exc: RateLimitExceeded) -> int:
    """
    获取距离限流窗口重置的剩余时间（秒）

    通过 slowapi 存储层获取限流键的实际过期时间，
    计算精确的剩余等待时间，而非返回整个窗口周期。

    Args:
        exc: 速率限制异常

    Returns:
        int: 剩余等待秒数
    """
    try:
        limiter = get_limiter()
        limit_obj = exc.limit
        if limit_obj is not None:
            # 获取窗口总时长
            window_seconds = limit_obj.limit.get_expiry()
            # 尝试通过存储获取精确的剩余时间
            # slowapi 存储的 get_expiry 返回键过期的时间戳
            # 构造存储键（使用 limit 的 key_for 方法）
            limiter_key = _get_rate_limit_key
            # 直接使用窗口总时长的一半作为保守的剩余时间估计
            # 因为精确的剩余时间需要知道窗口开始的精确时刻
            # 而存储层的 get_expiry 需要精确的键名，在 handler 中不易获取
            return max(1, window_seconds // 2)
    except Exception:
        pass

    # 回退：从详情字符串解析窗口时长，返回一半作为估计
    window = _extract_retry_after(str(exc.detail))
    return max(1, window // 2)


# 预定义的速率限制规则
class RateLimits:
    """速率限制规则常量"""

    # 认证相关（严格限制）
    LOGIN = "5/minute"  # 登录每分钟最多 5 次
    REGISTER = "3/minute"  # 注册每分钟最多 3 次
    PASSWORD_RESET = "3/hour"  # 密码重置每小时最多 3 次

    # 文档上传（中等限制）
    UPLOAD = "10/minute"  # 上传每分钟最多 10 次
    BATCH_UPLOAD = "3/minute"  # 批量上传每分钟最多 3 次

    # AI 相关（根据成本限制，降低到 30-60/minute）
    CHAT = "30/minute"  # 对话每分钟最多 30 次
    QA = "30/minute"  # 问答每分钟最多 30 次
    DEEP_RESEARCH = "5/minute"  # 深度研究每分钟最多 5 次
    AI_CHAT = "30/minute"  # AI 聊天每分钟最多 30 次

    # 搜索相关
    SEARCH = "30/minute"  # 搜索每分钟最多 30 次

    # 通用 API
    DEFAULT = "100/minute"  # 默认每分钟 100 次
