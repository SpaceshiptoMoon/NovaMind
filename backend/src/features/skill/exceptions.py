"""
技能广场模块异常定义

异常类放在模块顶层，供 API 层、服务层、仓储层共同使用，
避免仓储层反向依赖 API 层（违反 DDD 分层原则）。
"""
from typing import ClassVar, List

from src.core.middleware.base_exception_handler import BaseAPIError


class SkillError(BaseAPIError):
    """技能广场模块基础异常"""

    def __init__(self, message: str, code: str = "SKILL_ERROR"):
        super().__init__(message=message, code=code)


class SkillNotFoundError(SkillError):
    """技能不存在"""
    
    _serializable_attrs: ClassVar[List[str]] = ["skill_id"]

    def __init__(self, skill_id: int):
        super().__init__(
            message=f"技能 {skill_id} 不存在",
            code="SKILL_NOT_FOUND",
        )
        self.skill_id = skill_id


class SkillAlreadyExistsError(SkillError):
    """技能名称已存在"""
    _serializable_attrs: ClassVar[List[str]] = ["name"]

    def __init__(self, name: str):
        super().__init__(
            message=f"技能 '{name}' 已存在",
            code="SKILL_ALREADY_EXISTS",
        )
        self.name = name


class SkillNotPublishedError(SkillError):
    """技能未发布，无法安装"""
    _serializable_attrs: ClassVar[List[str]] = ["skill_id"]

    def __init__(self, skill_id: int):
        super().__init__(
            message=f"技能 {skill_id} 未发布，无法安装",
            code="SKILL_NOT_PUBLISHED",
        )
        self.skill_id = skill_id


class SkillAccessDeniedError(SkillError):
    """技能访问被拒绝"""
    _serializable_attrs: ClassVar[List[str]] = ["skill_id"]

    def __init__(self, skill_id: int):
        super().__init__(
            message=f"无权操作技能 {skill_id}",
            code="SKILL_ACCESS_DENIED",
        )
        self.skill_id = skill_id


class SkillAlreadyInstalledError(SkillError):
    """技能已安装到该 Agent"""
    _serializable_attrs: ClassVar[List[str]] = ["skill_id", "agent_id"]

    def __init__(self, skill_id: int, agent_id: int):
        super().__init__(
            message=f"技能 {skill_id} 已安装到 Agent {agent_id}",
            code="SKILL_ALREADY_INSTALLED",
        )
        self.skill_id = skill_id
        self.agent_id = agent_id


class SkillNotInstalledError(SkillError):
    """技能未安装到该 Agent"""
    _serializable_attrs: ClassVar[List[str]] = ["skill_id", "agent_id"]

    def __init__(self, skill_id: int, agent_id: int):
        super().__init__(
            message=f"技能 {skill_id} 未安装到 Agent {agent_id}",
            code="SKILL_NOT_INSTALLED",
        )
        self.skill_id = skill_id
        self.agent_id = agent_id


class InvalidSkillFormatError(SkillError):
    """SKILL.md 格式无效"""
    _serializable_attrs: ClassVar[List[str]] = ["reason"]

    def __init__(self, reason: str):
        super().__init__(
            message=f"SKILL.md 格式无效: {reason}",
            code="INVALID_SKILL_FORMAT",
        )
        self.reason = reason


class SkillReviewRejectedError(SkillError):
    """技能安全审查未通过"""
    _serializable_attrs: ClassVar[List[str]] = ["reason"]

    def __init__(self, reason: str):
        super().__init__(
            message=f"技能安全审查未通过: {reason}",
            code="SKILL_REVIEW_REJECTED",
        )
        self.reason = reason


class SkillFileSizeExceededError(SkillError):
    """技能 ZIP 文件大小超限"""

    def __init__(self, max_size_mb: int):
        super().__init__(
            message=f"ZIP 文件大小超过限制 ({max_size_mb}MB)",
            code="SKILL_FILE_SIZE_EXCEEDED",
        )
