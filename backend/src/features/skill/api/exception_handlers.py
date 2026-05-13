"""
技能广场异常处理器
"""
from fastapi import FastAPI

from src.core.middleware.base_exception_handler import register_module_exceptions
from src.features.skill.exceptions import (
    SkillError,
    SkillNotFoundError,
    SkillAlreadyExistsError,
    SkillNotPublishedError,
    SkillAccessDeniedError,
    SkillAlreadyInstalledError,
    SkillNotInstalledError,
    InvalidSkillFormatError,
    SkillReviewRejectedError,
)


def setup_skill_exception_handlers(app: FastAPI) -> None:
    """注册技能广场异常处理器"""
    register_module_exceptions(app, status_map={
        SkillNotFoundError: 404,
        SkillAlreadyExistsError: 409,
        SkillNotPublishedError: 400,
        SkillAccessDeniedError: 403,
        SkillAlreadyInstalledError: 409,
        SkillNotInstalledError: 404,
        InvalidSkillFormatError: 422,
        SkillReviewRejectedError: 422,
        SkillError: 500,
    })
