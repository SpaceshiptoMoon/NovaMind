"""
健康检查模块

提供多种健康检查端点
- /health - 基础健康检查
- /health/detailed - 详细组件状态
- /health/ready - Kubernetes 就绪检查
- /health/live - Kubernetes 存活检查
"""

import asyncio
from typing import Dict, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.utils.time_utils import now_china
from novamind.shared.clients import (
    get_elasticsearch_client,
    get_minio_client,
)
from novamind.shared.cache.redis_client import get_redis_client

logger = get_logger(__name__)
router = APIRouter(tags=["健康检查"])

# 健康检查默认超时时间（秒）
_HEALTH_CHECK_TIMEOUT = 3.0


async def _check_with_timeout(coro, timeout: float = _HEALTH_CHECK_TIMEOUT):
    """为协程添加超时保护，防止外部服务响应慢阻塞健康检查

    返回值：
    - 协程的实际返回值（成功时）
    - None（超时时）
    - 其他异常直接上抛
    """
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        return None


def _get_config():
    """延迟加载配置，避免启动时的循环导入"""
    from novamind.setting.yaml_config import get_config
    return get_config()


def _get_engine():
    """延迟加载数据库引擎"""
    from novamind.core.database.database import get_engine
    return get_engine()


async def _check_db_component(engine) -> dict:
    """检查数据库连接"""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"type": "mysql"}


async def _check_redis_component() -> dict:
    """检查 Redis 连接"""
    redis_client = await get_redis_client()
    await redis_client.redis_client.ping()
    return {}


async def _check_es_component() -> dict:
    """检查 Elasticsearch 连接"""
    es_client = await get_elasticsearch_client()
    if not await es_client.ping():
        raise Exception("无法连接")
    return {}


async def _check_minio_component(config) -> dict:
    """检查 MinIO 连接与 bucket"""
    minio_client = await get_minio_client()
    bucket_exists = await minio_client.bucket_exists(config.minio.bucket_name)
    if not bucket_exists:
        raise Exception("bucket 不存在")
    return {"bucket_exists": True}


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    基础健康检查

    Returns:
        服务状态
    """
    config = _get_config()
    return {
        "status": "healthy",
        "timestamp": now_china().isoformat(),
        "service": "novamind-backend",
        "version": config.project.version,
    }


@router.get("/health/detailed")
async def detailed_health_check() -> Dict[str, Any]:
    """
    详细健康检查

    检查所有依赖服务的状态
    """
    config = _get_config()
    engine = _get_engine()
    is_production = config.environment == "production"

    # 健康状态优先级：unhealthy(2) > degraded(1) > healthy(0)
    _priority = {"healthy": 0, "degraded": 1, "unhealthy": 2}
    overall_status = "healthy"

    health_status = {
        "status": "healthy",
        "timestamp": now_china().isoformat(),
        "service": "novamind-backend",
        "version": config.project.version,
        "components": {},
    }

    # 组件检查定义：(名称, 检查协程, 是否关键依赖)
    checks = [
        ("database", _check_db_component(engine), True),
        ("redis", _check_redis_component(), False),
        ("elasticsearch", _check_es_component(), True),
        ("minio", _check_minio_component(config), False),
    ]

    for name, coro, is_critical in checks:
        try:
            result = await _check_with_timeout(coro)
            if result is None:
                raise TimeoutError(f"{name} 健康检查超时")
            health_status["components"][name] = {"status": "healthy", **(result or {})}
        except Exception as e:
            new_status = "unhealthy" if is_critical else "degraded"
            if _priority[new_status] > _priority[overall_status]:
                overall_status = new_status
            health_status["components"][name] = {
                "status": "unhealthy",
                "error": str(e) if not is_production else "连接失败",
            }
            log_func = logger.error if is_critical else logger.warning
            log_func(f"{name} 健康检查失败", error=str(e))

    health_status["status"] = overall_status

    if health_status["status"] == "unhealthy":
        return JSONResponse(content=health_status, status_code=503)
    return health_status


@router.get("/health/ready")
async def readiness_check() -> Dict[str, Any]:
    """
    就绪检查（Kubernetes）

    检查服务是否准备好接收流量
    只检查关键依赖
    """
    engine = _get_engine()
    try:
        # 只检查关键依赖：数据库
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        logger.error("就绪检查失败", error=str(e))
        return JSONResponse(content={"status": "not_ready"}, status_code=503)


@router.get("/health/live")
async def liveness_check() -> Dict[str, Any]:
    """
    存活检查（Kubernetes）

    检查服务是否存活
    不检查任何依赖
    """
    return {"status": "alive"}


@router.get("/")
async def root_info() -> Dict[str, Any]:
    """
    根路径信息
    """
    config = _get_config()
    return {
        "message": "智能知识库系统 API",
        "version": config.project.version,
        "status": "running",
        "docs": "/docs",
        "health": "/health",
    }
