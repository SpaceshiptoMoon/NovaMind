"""
异常处理模块
包含全局异常处理器和自定义异常
使用结构化日志记录（包含堆栈信息）
"""

from fastapi import FastAPI

from src.core.middleware.structured_logging import get_logger
from src.core.middleware.base_exception_handler import (
    BaseAPIError,
    global_exception_handler,
    validation_exception_handler,
    setup_global_exception_handlers,
)
from src.features.user.api.startup import setup_user_exception_handlers
from src.features.qa.api.startup import setup_qa_exception_handlers
from src.features.knowledge_space.api.startup import (
    setup_knowledge_space_exception_handlers,
)
from src.features.deep_research.api.exception_handlers import (
    setup_deep_research_exception_handlers,
)
from src.features.evaluation.api.exception_handlers import (
    setup_evaluation_exception_handlers,
)
from src.features.skill.api.exception_handlers import (
    setup_skill_exception_handlers,
)
from src.features.app.api.exception_handlers import (
    setup_app_exception_handlers,
)
from src.features.agent.api.exception_handlers import (
    setup_agent_exception_handlers,
)
from src.features.notification.api.exception_handlers import (
    setup_notification_exception_handlers,
)

logger = get_logger(__name__)


def setup_exception_handlers(app: FastAPI):
    """
    设置异常处理器

    各模块的 setup 函数为同步操作（注册异常处理器无需 async）。
    """

    # 用户模块异常处理器
    setup_user_exception_handlers(app)

    # QA 模块异常处理器
    setup_qa_exception_handlers(app)

    # 知识空间异常处理器
    setup_knowledge_space_exception_handlers(app)

    # 深度研究异常处理器
    setup_deep_research_exception_handlers(app)

    # 测评模块异常处理器
    setup_evaluation_exception_handlers(app)

    # 技能广场异常处理器
    setup_skill_exception_handlers(app)

    # 应用中心异常处理器
    setup_app_exception_handlers(app)

    # Agent 模块异常处理器
    setup_agent_exception_handlers(app)

    # 通知模块异常处理器
    setup_notification_exception_handlers(app)

    # 注册全局异常处理器（包含 Exception 兜底和 RequestValidationError）
    setup_global_exception_handlers(app)

    logger.info("异常处理器设置完成")
