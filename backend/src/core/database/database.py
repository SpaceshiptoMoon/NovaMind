import asyncio
import threading
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlparse, urlunparse

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from src.setting.yaml_config import get_config
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# 延迟初始化：避免模块导入时就创建连接
_engine = None
_session_factory = None
_async_engine_lock: Optional[asyncio.Lock] = None
_engine_lock = threading.Lock()  # 同步函数使用的线程锁


def _get_async_lock() -> asyncio.Lock:
    """获取异步锁（延迟初始化）"""
    global _async_engine_lock
    if _async_engine_lock is None:
        _async_engine_lock = asyncio.Lock()
    return _async_engine_lock

# 同步驱动 → 异步驱动映射
ASYNC_DRIVER_MAP = {
    "postgresql": "postgresql+asyncpg",
    "mysql": "mysql+aiomysql",
    "sqlite": "sqlite+aiosqlite",
}


def _build_db_url(config) -> str:
    """
    构造异步数据库 URL

    自动将同步驱动 URL 转换为异步驱动 URL。
    如果 URL 已包含异步驱动前缀，则直接返回。

    Args:
        config: 应用配置对象

    Returns:
        异步数据库连接 URL
    """
    db_url = config.database.url
    parsed = urlparse(db_url)

    # 已包含已知异步驱动的 URL 直接返回（如 mysql+aiomysql://）
    async_schemes = set(ASYNC_DRIVER_MAP.values())
    if parsed.scheme in async_schemes:
        return db_url

    # 同步驱动转异步
    async_scheme = ASYNC_DRIVER_MAP.get(parsed.scheme, parsed.scheme)
    return urlunparse(parsed._replace(scheme=async_scheme))


def get_engine():
    """
    获取数据库引擎（延迟初始化，线程安全双重检查锁定）

    Returns:
        AsyncEngine 实例
    """
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                config = get_config()
                db_url = _build_db_url(config)

                # SSL 配置
                connect_args = {}
                ssl_enabled = getattr(config.database, 'ssl', False)
                if ssl_enabled:
                    connect_args["ssl"] = True

                _engine = create_async_engine(
                    db_url,
                    echo=False,
                    future=True,
                    pool_size=config.database.pool_size,
                    max_overflow=config.database.max_overflow,
                    pool_timeout=config.database.pool_timeout,
                    pool_recycle=config.database.pool_recycle,
                    pool_pre_ping=config.database.pool_pre_ping,
                    connect_args=connect_args,
                )
                logger.info("数据库引擎已初始化")
    return _engine


def get_session_factory():
    """
    获取 Session 工厂（延迟初始化，线程安全双重检查锁定）

    Returns:
        async_sessionmaker 实例
    """
    global _session_factory
    if _session_factory is None:
        with _engine_lock:
            if _session_factory is None:
                _session_factory = async_sessionmaker(
                    bind=get_engine(),
                    class_=AsyncSession,
                    autocommit=False,
                    autoflush=False,
                    expire_on_commit=False,
                )
    return _session_factory


@asynccontextmanager
async def get_db_session():
    """
    获取数据库会话（自动提交/回滚的上下文管理器）

    正常退出时自动提交，异常时自动回滚。

    SSE 流式场景下客户端断开连接触发 CancelledError，
    此时 MySQL 连接已失效，commit/rollback 都会失败，
    需静默处理以避免未捕获异常污染日志。
    """
    import asyncio
    from sqlalchemy.exc import InterfaceError

    async with get_session_factory()() as session:
        # ── 异常路径：回滚并继续向上抛出 ──
        try:
            yield session
        except asyncio.CancelledError:
            try:
                await session.rollback()
            except Exception:
                pass
            raise
        except Exception:
            try:
                await session.rollback()
            except Exception:
                pass
            raise

        # ── 正常路径：提交事务 ──
        try:
            await session.commit()
        except (InterfaceError, asyncio.CancelledError):
            # 连接已断开（SSE 客户端断开、网络中断等），无法提交，静默跳过
            pass


async def get_db():
    """
    获取数据库会话（FastAPI Depends 用）

    复用 get_db_session()，包装为 async generator 以兼容 FastAPI 依赖注入。
    """
    async with get_db_session() as session:
        yield session


# ====== 引擎清理函数 ======
async def dispose_engine():
    """清理数据库引擎，释放连接池资源"""
    global _engine, _session_factory
    async with _get_async_lock():
        engine_to_dispose = _engine
        _engine = None
        _session_factory = None
    if engine_to_dispose is not None:
        await engine_to_dispose.dispose()
        logger.info("数据库引擎已清理")
