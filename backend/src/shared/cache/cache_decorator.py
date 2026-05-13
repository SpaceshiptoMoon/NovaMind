"""
缓存装饰器

提供便捷的函数结果缓存功能
"""

import asyncio
import hashlib
import json
import inspect
from functools import wraps
from typing import Any, Callable, Optional, List

from src.shared.cache.redis_client import get_redis_client
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


def generate_cache_key(prefix: str, *args, **kwargs) -> str:
    """
    生成缓存键

    :param prefix: 键前缀
    :param args: 函数位置参数
    :param kwargs: 函数关键字参数
    :return: 缓存键
    """
    # 创建参数序列化字符串
    try:
        args_str = json.dumps(args, ensure_ascii=False, default=str)
        kwargs_str = json.dumps(sorted(kwargs.items()), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        # 如果无法序列化，使用字符串表示
        args_str = str(args)
        kwargs_str = str(sorted(kwargs.items()))

    # 生成哈希
    content = f"{prefix}:{args_str}:{kwargs_str}"
    hash_obj = hashlib.sha256(content.encode('utf-8'))
    return f"cache:{hash_obj.hexdigest()}"


def cache_result(
    expire_seconds: int = 3600,
    cache_key_prefix: Optional[str] = None,
    cache_key_func: Optional[Callable] = None,
    ignore_args: Optional[List[int]] = None,
    ignore_kwargs: Optional[List[str]] = None,
    skip_cache_func: Optional[Callable] = None,
):
    """
    缓存函数结果的装饰器

    :param expire_seconds: 过期时间（秒）
    :param cache_key_prefix: 自定义缓存键前缀
    :param cache_key_func: 自定义缓存键生成函数，签名为 (args, kwargs) -> str
    :param ignore_args: 忽略的位置参数索引列表
    :param ignore_kwargs: 忽略的关键字参数名列表
    :param skip_cache_func: 判断是否跳过缓存的函数，签名为 (result) -> bool
    """
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 生成缓存键
            if cache_key_func:
                cache_key = cache_key_func(args, kwargs)
            else:
                prefix = cache_key_prefix or f"func:{func.__name__}"

                # 过滤掉不需要的参数
                filtered_args = args
                if ignore_args:
                    filtered_args = tuple(
                        arg for i, arg in enumerate(args)
                        if i not in ignore_args
                    )

                filtered_kwargs = kwargs
                if ignore_kwargs:
                    filtered_kwargs = {
                        k: v for k, v in kwargs.items()
                        if k not in ignore_kwargs
                    }

                cache_key = generate_cache_key(prefix, *filtered_args, **filtered_kwargs)

            # 尝试从缓存获取
            try:
                redis_client = await get_redis_client()
                cached_result = await redis_client.get(cache_key)

                if cached_result is not None:
                    logger.debug(f"缓存命中: {cache_key}")
                    return cached_result
            except Exception as e:
                logger.warning(f"读取缓存失败，将继续执行函数: {e}")
                cached_result = None

            # 缓存未命中，执行函数
            logger.debug(f"缓存未命中: {cache_key}")
            result = await func(*args, **kwargs)

            # 检查是否应该缓存结果
            if skip_cache_func and skip_cache_func(result):
                logger.debug(f"跳过缓存: {cache_key}")
                return result

            # 存入缓存
            try:
                redis_client = await get_redis_client()
                await redis_client.set(cache_key, result, expire=expire_seconds)
            except Exception as e:
                logger.warning(f"写入缓存失败: {e}")

            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            """同步函数包装器"""
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # 已有事件循环运行中，在独立线程中创建新循环
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, async_wrapper(*args, **kwargs))
                    return future.result()
            else:
                # 无运行中的事件循环，安全使用 asyncio.run
                return asyncio.run(async_wrapper(*args, **kwargs))

        # 根据函数类型返回适当的包装器
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def invalidate_cache(*cache_keys: str):
    """
    失效缓存的装饰器

    在函数执行后删除指定的缓存键

    :param cache_keys: 要失效的缓存键（可以是模式，如 "user:*"）
    """
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 先执行函数
            result = await func(*args, **kwargs)

            # 失效缓存
            try:
                redis_client = await get_redis_client()

                for key_pattern in cache_keys:
                    try:
                        formatted_key = key_pattern.format(**kwargs)
                    except (KeyError, IndexError):
                        formatted_key = key_pattern

                    if '*' in formatted_key:
                        deleted = await redis_client.delete_by_pattern(formatted_key)
                        logger.debug(f"批量删除缓存: {formatted_key}, 数量: {deleted}")
                    else:
                        await redis_client.delete(formatted_key)
                        logger.debug(f"删除缓存: {formatted_key}")

            except Exception as e:
                logger.warning(f"失效缓存失败: {e}")

            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            """同步函数包装器，安全处理事件循环"""
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, async_wrapper(*args, **kwargs))
                    return future.result()
            else:
                return asyncio.run(async_wrapper(*args, **kwargs))

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
