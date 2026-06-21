"""
ClawMate 依赖注入
"""

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.user.api.auth import get_current_user
from src.core.database.database import get_db
from src.features.user.services.model_config_service import ModelConfigService
from src.features.clawmate.core.session_manager import SessionManager
from src.features.clawmate.core.file_operations import FileOperations
from src.features.clawmate.core.environment import LocalEnvironment


def get_session_manager(request: Request) -> SessionManager:
    """从 app.state 获取 SessionManager 单例"""
    return request.app.state.clawmate_session_manager


def get_clawmate_engine(request: Request):
    """从 app.state 获取 ClawMate AgentEngine 单例"""
    return request.app.state.clawmate_engine


async def get_user_environment(
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_session_manager),
) -> LocalEnvironment:
    """获取当前用户的环境（必须已初始化，否则抛异常）"""
    user_id = current_user["id"]
    env = manager.get(user_id)
    if env is None:
        from src.features.clawmate.api.exceptions import SessionNotInitializedError
        raise SessionNotInitializedError()
    return env


def get_file_operations(
    env: LocalEnvironment = Depends(get_user_environment),
) -> FileOperations:
    """获取文件操作实例"""
    return FileOperations(env)


async def get_model_config_service(
    db: AsyncSession = Depends(get_db),
) -> ModelConfigService:
    """获取模型配置服务"""
    return ModelConfigService(db)


async def get_chat_service(
    session_manager: SessionManager = Depends(get_session_manager),
    engine=Depends(get_clawmate_engine),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
):
    """获取 ClawMateChatService（per-request）"""
    from src.features.clawmate.core.chat_service import ClawMateChatService
    return ClawMateChatService(
        session_manager=session_manager,
        agent_engine=engine,
        model_config_service=model_config_service,
    )
