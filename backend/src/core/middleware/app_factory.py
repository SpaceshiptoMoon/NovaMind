"""
应用工厂模块
负责创建和配置FastAPI应用实例
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from novamind.setting.yaml_config import get_config
from .structured_logging import setup_structured_logging, get_logger
from .startup_manager import AppLifespanManager
from .router_manager import RouterManager
from .trace_middleware import TraceIDMiddleware
from .exceptions import setup_exception_handlers
from .rate_limit import get_limiter, rate_limit_exceeded_handler
from novamind.core.security.config_validator import validate_security_config
from novamind.core.compat.starlette_multipart_patch import apply_starlette_multipart_patch


def create_app() -> FastAPI:
    """
    创建并配置FastAPI应用实例
    """
    # 设置结构化日志
    setup_structured_logging()
    apply_starlette_multipart_patch()

    # 加载配置
    config = get_config()

    # 安全配置检查（生产环境必须通过）
    is_secure, security_issues = validate_security_config(config)
    if not is_secure:
        raise RuntimeError(
            "生产环境安全配置检查失败，请修复上述安全问题后重试。\n"
            "如需开发环境运行，请设置 ENVIRONMENT=development"
        )

    # 初始化路由管理器
    router_manager = RouterManager()

    # 创建应用生命周期管理器
    lifespan_manager = AppLifespanManager()

    # 创建FastAPI应用（生产环境禁用 API 文档端点）
    is_production = config.environment == "production"
    app = FastAPI(
        title=config.project.name,
        version=config.project.version,
        description=config.project.description,
        lifespan=lifespan_manager.lifespan,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
    )

    # 设置异常处理器（包含所有模块的异常注册）
    setup_exception_handlers(app)

    # 配置速率限制
    app.state.limiter = get_limiter()
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    # 添加中间件（注意：中间件的顺序很重要）
    _add_middleware(app, config)

    # 注册路由
    _register_routes(app, router_manager)

    return app


def _add_middleware(app: FastAPI, config):
    """
    添加中间件

    注意：FastAPI 中间件执行顺序与添加顺序相反
    最后添加的中间件最先执行
    """
    # 1. Trace ID 中间件（最后添加，最先执行）
    app.add_middleware(TraceIDMiddleware)

    # 2. CORS 中间件
    cors_origins = _get_cors_origins(config)

    # 安全检查：通配符与 credentials 组合不安全
    # 默认禁用 credentials，仅在配置了具体域名时才考虑启用
    allow_credentials = False
    if cors_origins and "*" not in cors_origins:
        allow_credentials = True
    elif "*" in cors_origins:
        # 记录警告日志
        get_logger(__name__).warning(
            "CORS 配置警告: allow_origins 包含通配符 '*'，已禁用 credentials。"
            "生产环境请配置具体的允许域名。"
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-Request-ID",
            "X-Space-ID",
            "Accept",
            "Origin",
        ],
        expose_headers=["X-Request-ID", "X-Trace-ID"],
        max_age=600,
    )


def _register_routes(app: FastAPI, router_manager: RouterManager):
    """注册所有路由"""
    for router, prefix, tags in router_manager.get_all_routers():
        app.include_router(router, prefix=prefix, tags=tags)


def _get_cors_origins(config):
    """从配置获取CORS允许的域名"""
    cors_origins = getattr(config, "cors_origins", [])
    if isinstance(cors_origins, str):
        if cors_origins == "*":
            # 通配符保持原样，但 credentials 会被禁用
            return ["*"]
        # 支持逗号分隔的域名列表
        cors_origins = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]
    return cors_origins
