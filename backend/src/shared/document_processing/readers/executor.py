"""
共享线程池执行器

为文档读取器提供统一的线程池资源管理
避免每个 reader 独立创建线程池导致的资源浪费
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# 全局共享线程池
# 默认 4 个工作线程，足够处理大多数文档读取场景
_shared_executor: Optional[ThreadPoolExecutor] = None


def get_shared_executor(max_workers: int = 4) -> ThreadPoolExecutor:
    """
    获取共享线程池执行器

    Args:
        max_workers: 最大工作线程数，默认 4

    Returns:
        ThreadPoolExecutor 实例
    """
    global _shared_executor
    if _shared_executor is None:
        _shared_executor = ThreadPoolExecutor(max_workers=max_workers)
        logger.info("共享线程池已初始化", max_workers=max_workers)
    return _shared_executor


async def run_in_executor(func, *args):
    """
    在共享线程池中执行同步函数

    Args:
        func: 要执行的同步函数
        *args: 函数参数

    Returns:
        函数执行结果
    """
    loop = asyncio.get_running_loop()
    executor = get_shared_executor()
    return await loop.run_in_executor(executor, func, *args)


def shutdown_executor():
    """
    关闭共享线程池（应用关闭时调用）
    """
    global _shared_executor
    if _shared_executor is not None:
        _shared_executor.shutdown(wait=True)
        _shared_executor = None
        logger.info("共享线程池已关闭")
