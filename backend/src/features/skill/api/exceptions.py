"""
技能广场 API 异常 — 兼容层
异常类定义在模块顶层 src/features/skill/exceptions.py
"""
from novamind.features.skill.exceptions import (  # noqa: F401
    InvalidSkillFormatError,
    SkillAccessDeniedError,
    SkillAlreadyExistsError,
    SkillAlreadyInstalledError,
    SkillError,
    SkillFileSizeExceededError,
    SkillNotFoundError,
    SkillNotInstalledError,
    SkillNotPublishedError,
    SkillReviewRejectedError,
    SkillTargetAgentNotFoundError,
)
