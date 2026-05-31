"""
技能广场依赖注入
"""
import json
import pathlib
from typing import Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.database import get_db
from src.shared.clients import get_minio_client
from src.shared.ai_models.base_model import BaseLLM
from src.features.user.services.model_config_service import ModelConfigService
from src.features.skill.services.skill_marketplace_service import SkillMarketplaceService
from src.features.skill.services.skill_checker import SkillSecurityChecker
from src.features.knowledge_space.api.dependencies import get_current_user_id
from src.setting.yaml_config.loader import get_config_value
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# 设置文件路径
_SETTINGS_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "admin_settings.json"


def _read_settings() -> dict:
    """从 JSON 文件读取设置"""
    if _SETTINGS_FILE.exists():
        try:
            return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("读取技能审查设置失败", error=str(e))
    return {}


def _write_settings(data: dict) -> None:
    """写入 JSON 设置文件"""
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def _get_llm_review_enabled() -> bool:
    """读取 LLM 审查开关，优先从持久化文件读取"""
    settings = _read_settings()
    if "llm_review_enabled" in settings:
        return bool(settings["llm_review_enabled"])
    return bool(get_config_value("skill_marketplace.llm_review_enabled") or False)


async def _get_llm_review_model() -> Optional[str]:
    """读取 LLM 审查模型名称，优先从持久化文件读取"""
    settings = _read_settings()
    if settings.get("llm_review_model"):
        return settings["llm_review_model"]
    return get_config_value("skill_marketplace.llm_review_model") or None


async def _get_review_llm_client(
    user_id: int,
    model_config_service: ModelConfigService,
) -> Optional[BaseLLM]:
    """获取审查用的 LLM 客户端"""
    model_name = await _get_llm_review_model()
    if not model_name:
        model_name = await model_config_service.get_user_default_model_name(user_id, "llm")
    if not model_name:
        return None
    return await model_config_service.get_llm_client_by_model(user_id, model_name)


def _get_model_config_service(db: AsyncSession = Depends(get_db)) -> ModelConfigService:
    return ModelConfigService(db)


async def get_skill_service(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    model_config_service: ModelConfigService = Depends(_get_model_config_service),
) -> SkillMarketplaceService:
    minio = await get_minio_client()

    # 条件注入 LLM 审查
    enabled = await _get_llm_review_enabled()
    llm_client = await _get_review_llm_client(user_id, model_config_service) if enabled else None
    checker = SkillSecurityChecker(llm_client=llm_client)

    service = SkillMarketplaceService(db=db, minio_client=minio, security_checker=checker)
    yield service
    await service.cleanup()


async def update_llm_review_settings(enabled: bool, model: Optional[str] = None) -> None:
    """管理员更新 LLM 审查设置"""
    settings = _read_settings()
    settings["llm_review_enabled"] = enabled
    settings["llm_review_model"] = model
    _write_settings(settings)


async def get_llm_review_settings() -> dict:
    """获取当前审查设置"""
    enabled = await _get_llm_review_enabled()
    model_name = await _get_llm_review_model()
    return {
        "llm_review_enabled": enabled,
        "llm_review_model": model_name,
    }
