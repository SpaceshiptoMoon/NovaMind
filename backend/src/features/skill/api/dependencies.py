"""
技能广场依赖注入
"""

from fastapi import Depends
from novamind.core.database.database import get_db
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.agent.services.agent_service import AgentService
from novamind.features.knowledge_space.api.dependencies import get_current_user_id
from novamind.features.skill.services.admin_settings_store import (
    get_llm_review_enabled,
    get_llm_review_model,
)
from novamind.features.skill.services.skill_checker import SkillSecurityChecker
from novamind.features.skill.services.skill_marketplace_service import SkillMarketplaceService
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.ai_models.base_model import BaseLLM
from novamind.shared.prompts.prompt_manager import PromptManager
from novamind.shared.storage.client_factory import get_minio_client
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)



async def _get_review_llm_client(
    user_id: int,
    model_config_service: ModelConfigService,
) -> BaseLLM | None:
    """获取审查用的 LLM 客户端

    管理员指定了审查模型时，按初始管理员账号（YAML ``admin.username``）取
    凭证构建 client —— ``admin/models`` 列出的就是该账号的模型配置；回退到
    用户默认模型时才使用传入的 ``user_id``。
    """
    model_name = await get_llm_review_model()
    if model_name:
        owner_id = await _get_review_model_owner_id()
        if owner_id is None:
            return None
        return await model_config_service.get_llm_client_by_model(owner_id, model_name)
    model_name = await model_config_service.get_user_default_model_name(user_id, "llm")
    if not model_name:
        return None
    return await model_config_service.get_llm_client_by_model(user_id, model_name)


async def _get_review_model_owner_id() -> int | None:
    """解析审查模型凭证归属用户：初始管理员（YAML admin.username）"""
    from novamind.setting.yaml_config.loader import get_config

    admin_username = get_config().admin.username
    from novamind.core.database.database import get_session_factory
    from novamind.features.user.repository.user_repository import UserRepository

    session_factory = get_session_factory()
    async with session_factory() as db:
        admin = await UserRepository(db).get_user_by_username(admin_username)
        return admin.id if admin else None


def get_model_config_service(db: AsyncSession = Depends(get_db)) -> ModelConfigService:
    return ModelConfigService(db)


async def get_skill_service(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
) -> SkillMarketplaceService:
    minio = await get_minio_client()

    # 条件注入 LLM 审查：端口 prompt_provider + logger 始终注入（默认无 LLM 时
    # check_llm 直接返回 None，行为不变；LLM 启用时经端口取 prompt 与记日志）
    enabled = await get_llm_review_enabled()
    llm_client = await _get_review_llm_client(user_id, model_config_service) if enabled else None
    checker = SkillSecurityChecker(
        llm_client=llm_client,
        prompt_provider=PromptManager(),
        logger=get_logger("skill.security_checker").bind(),
    )

    agent_service = AgentService(db)

    service = SkillMarketplaceService(
        db=db,
        minio_client=minio,
        security_checker=checker,
        model_config_service=model_config_service,
        agent_service=agent_service,
    )
    yield service
    await service.cleanup()


async def update_llm_review_settings(enabled: bool, model: str | None = None) -> None:
    """管理员更新 LLM 审查设置（委托 service 层持久化）"""
    from novamind.features.skill.services.admin_settings_store import (
        update_llm_review_settings as _store_update,
    )

    await _store_update(enabled, model)


async def get_llm_review_settings() -> dict:
    """获取当前审查设置"""
    enabled = await get_llm_review_enabled()
    model_name = await get_llm_review_model()
    return {
        "llm_review_enabled": enabled,
        "llm_review_model": model_name,
    }
