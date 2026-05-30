"""
技能广场 API 异常 — 兼容层
异常类定义在模块顶层 src/features/skill/exceptions.py
"""
from src.features.skill.exceptions import (  # noqa: F401
    SkillError,
    SkillNotFoundError,
    SkillAlreadyExistsError,
    SkillNotPublishedError,
    SkillAccessDeniedError,
    SkillAlreadyInstalledError,
    SkillNotInstalledError,
    InvalidSkillFormatError,
    SkillReviewRejectedError,
    SkillFileSizeExceededError,
)
