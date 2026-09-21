"""技能广场管理员设置持久化（原 skill/api/dependencies JSON IO 归位 service 层）。

LLM 审查开关/模型名存 features/skill/data/admin_settings.json；
未配置的字段回落 YAML ``skill_marketplace.*`` 段（get_config_value 字典路径）。
"""
from __future__ import annotations

import json
import pathlib

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

_SETTINGS_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "admin_settings.json"


def read_settings() -> dict:
    """从 JSON 文件读取设置"""
    if _SETTINGS_FILE.exists():
        try:
            return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("读取技能审查设置失败", error=str(e))
    return {}


def write_settings(data: dict) -> None:
    """写入 JSON 设置文件"""
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def get_llm_review_enabled() -> bool:
    """LLM 审查开关：持久化文件优先，缺省回落 YAML。"""
    from novamind.setting.yaml_config import get_config_value

    settings = read_settings()
    if "llm_review_enabled" in settings:
        return bool(settings["llm_review_enabled"])
    return bool(get_config_value("skill_marketplace.llm_review_enabled") or False)


async def get_llm_review_model() -> str | None:
    """LLM 审查模型名：持久化文件优先，缺省回落 YAML。"""
    from novamind.setting.yaml_config import get_config_value

    settings = read_settings()
    if settings.get("llm_review_model"):
        return settings["llm_review_model"]
    return get_config_value("skill_marketplace.llm_review_model") or None


async def update_llm_review_settings(enabled: bool, model: str | None) -> None:
    """管理员更新 LLM 审查设置。"""
    settings = read_settings()
    settings["llm_review_enabled"] = enabled
    settings["llm_review_model"] = model
    write_settings(settings)


__all__ = [
    "read_settings",
    "write_settings",
    "get_llm_review_enabled",
    "get_llm_review_model",
    "update_llm_review_settings",
]
