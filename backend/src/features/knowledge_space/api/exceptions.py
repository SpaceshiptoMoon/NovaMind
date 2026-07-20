"""
自定义异常

定义知识空间模块的异常类
"""

from typing import Optional, List, ClassVar

from novamind.core.middleware.base_exception_handler import BaseAPIError


class KnowledgeSpaceError(BaseAPIError):
    """知识空间模块基础异常"""

    def __init__(self, message: str, code: str = "UNKNOWN_ERROR"):
        super().__init__(message=message, code=code)


# ==================== 空间相关异常 ====================

class SpaceNotFoundError(KnowledgeSpaceError):
    """空间不存在"""
    _serializable_attrs: ClassVar[List[str]] = ["space_id"]

    def __init__(self, space_id: int):
        super().__init__(
            message=f"知识空间 {space_id} 不存在",
            code="SPACE_NOT_FOUND",
        )
        self.space_id = space_id


class SpaceAlreadyExistsError(KnowledgeSpaceError):
    """空间已存在"""
    _serializable_attrs: ClassVar[List[str]] = ["name"]

    def __init__(self, name: str):
        super().__init__(
            message=f"知识空间 '{name}' 已存在",
            code="SPACE_ALREADY_EXISTS",
        )
        self.name = name


class SpaceAccessDeniedError(KnowledgeSpaceError):
    """空间访问被拒绝"""
    _serializable_attrs: ClassVar[List[str]] = ["space_id", "reason"]

    def __init__(self, space_id: int, user_id: int, reason: str = "无权访问"):
        super().__init__(
            message=f"无权访问空间 {space_id}: {reason}",
            code="SPACE_ACCESS_DENIED",
        )
        self.space_id = space_id
        self.user_id = user_id
        self.reason = reason


class SpaceLimitExceededError(KnowledgeSpaceError):
    """空间数量限制"""
    _serializable_attrs: ClassVar[List[str]] = ["limit"]

    def __init__(self, limit: int):
        super().__init__(
            message=f"已达到空间数量上限 ({limit})",
            code="SPACE_LIMIT_EXCEEDED",
        )
        self.limit = limit


# ==================== 成员相关异常 ====================

class MemberNotFoundError(KnowledgeSpaceError):
    """成员不存在"""
    _serializable_attrs: ClassVar[List[str]] = ["space_id", "user_id"]

    def __init__(self, space_id: int, user_id: int):
        super().__init__(
            message=f"用户 {user_id} 不是空间 {space_id} 的成员",
            code="MEMBER_NOT_FOUND",
        )
        self.space_id = space_id
        self.user_id = user_id


class MemberAlreadyExistsError(KnowledgeSpaceError):
    """成员已存在"""
    _serializable_attrs: ClassVar[List[str]] = ["space_id", "user_id"]

    def __init__(self, space_id: int, user_id: int):
        super().__init__(
            message=f"用户 {user_id} 已是空间 {space_id} 的成员",
            code="MEMBER_ALREADY_EXISTS",
        )
        self.space_id = space_id
        self.user_id = user_id


class InviteExpiredError(KnowledgeSpaceError):
    """邀请已过期"""

    def __init__(self):
        super().__init__(
            message="邀请已过期",
            code="INVITE_EXPIRED",
        )


class InviteInvalidError(KnowledgeSpaceError):
    """邀请无效"""

    def __init__(self):
        super().__init__(
            message="邀请无效",
            code="INVITE_INVALID",
        )


class CannotRemoveLastAdminError(KnowledgeSpaceError):
    """不能移除最后一个管理员"""

    def __init__(self):
        super().__init__(
            message="不能移除最后一个管理员",
            code="CANNOT_REMOVE_LAST_ADMIN",
        )


class CannotModifySelfRoleError(KnowledgeSpaceError):
    """不能修改自己的角色"""

    def __init__(self):
        super().__init__(
            message="不能修改自己的角色",
            code="CANNOT_MODIFY_SELF_ROLE",
        )


# ==================== 知识库相关异常 ====================

class KnowledgeBaseNotFoundError(KnowledgeSpaceError):
    """知识库不存在"""
    _serializable_attrs: ClassVar[List[str]] = ["kb_id"]

    def __init__(self, kb_id: int):
        super().__init__(
            message=f"知识库 {kb_id} 不存在",
            code="KNOWLEDGE_BASE_NOT_FOUND",
        )
        self.kb_id = kb_id


class KnowledgeBaseAlreadyExistsError(KnowledgeSpaceError):
    """知识库已存在"""
    _serializable_attrs: ClassVar[List[str]] = ["name"]

    def __init__(self, name: str):
        super().__init__(
            message=f"知识库 '{name}' 已存在",
            code="KNOWLEDGE_BASE_ALREADY_EXISTS",
        )
        self.name = name


class KnowledgeBaseAccessDeniedError(KnowledgeSpaceError):
    """知识库访问被拒绝"""
    _serializable_attrs: ClassVar[List[str]] = ["kb_id", "user_id", "reason"]

    def __init__(self, kb_id: int, user_id: int, reason: str = "无权访问"):
        super().__init__(
            message=f"用户 {user_id} 无权访问知识库 {kb_id}: {reason}",
            code="KNOWLEDGE_BASE_ACCESS_DENIED",
        )
        self.kb_id = kb_id
        self.user_id = user_id
        self.reason = reason


class KnowledgeBaseArchivedError(KnowledgeSpaceError):
    """知识库已归档，禁止写操作"""
    http_status_code: ClassVar[int] = 403
    _serializable_attrs: ClassVar[List[str]] = ["kb_id"]

    def __init__(self, kb_id: int):
        super().__init__(
            message=f"知识库 {kb_id} 已归档，无法执行此操作。请先激活知识库后再试。",
            code="KNOWLEDGE_BASE_ARCHIVED",
        )
        self.kb_id = kb_id


class KnowledgeBaseLimitExceededError(KnowledgeSpaceError):
    """知识库数量限制"""
    _serializable_attrs: ClassVar[List[str]] = ["limit"]

    def __init__(self, limit: int):
        super().__init__(
            message=f"已达到知识库数量上限 ({limit})",
            code="KNOWLEDGE_BASE_LIMIT_EXCEEDED",
        )
        self.limit = limit


# ==================== 文档相关异常 ====================

class DocumentNotFoundError(KnowledgeSpaceError):
    """文档不存在"""
    _serializable_attrs: ClassVar[List[str]] = ["document_id"]

    def __init__(self, document_id: int):
        super().__init__(
            message=f"文档 {document_id} 不存在",
            code="DOCUMENT_NOT_FOUND",
        )
        self.document_id = document_id


class DocumentAlreadyExistsError(KnowledgeSpaceError):
    """文档已存在"""
    _serializable_attrs: ClassVar[List[str]] = ["filename"]

    def __init__(self, filename: str):
        super().__init__(
            message=f"文档 '{filename}' 已存在",
            code="DOCUMENT_ALREADY_EXISTS",
        )
        self.filename = filename


class DocumentProcessingError(KnowledgeSpaceError):
    """文档处理错误"""
    _serializable_attrs: ClassVar[List[str]] = ["document_id", "error_message"]

    def __init__(self, document_id: int, error_message: str):
        super().__init__(
            message=f"文档 {document_id} 处理失败: {error_message}",
            code="DOCUMENT_PROCESSING_ERROR",
        )
        self.document_id = document_id
        self.error_message = error_message


class LocalASRBusyError(Exception):
    """本地 ASR 正在转写其它音频，当前任务需延后重试。

    这不是错误，而是拥塞信号——arq worker 捕获后应延迟重入队，
    释放 Worker 槽位给其它非音频任务。
    """

    def __init__(self, document_id: int, message: str = ""):
        self.document_id = document_id
        self.message = message or f"本地 ASR 忙碌，文档 {document_id} 延后重试"
        super().__init__(self.message)


class DocumentInvalidTypeError(KnowledgeSpaceError):
    """文档类型不支持"""
    _serializable_attrs: ClassVar[List[str]] = ["file_type", "allowed"]

    def __init__(self, file_type: str = "", allowed: Optional[List[str]] = None, ext: Optional[str] = None):
        normalized_type = (ext if ext is not None else file_type) or ""
        allowed = allowed or []

        message = f"不支持的文件类型: {normalized_type or '[empty]'}"
        if normalized_type in {".doc", "doc"}:
            message += "。当前支持 .doc，系统会在上传后自动转换为 .docx"
        if allowed:
            message += f"。当前支持: {', '.join(allowed)}"

        super().__init__(
            message=message,
            code="DOCUMENT_INVALID_TYPE",
        )
        self.file_type = normalized_type
        self.allowed = allowed


class DocumentConversionError(KnowledgeSpaceError):
    """文档转换失败"""
    _serializable_attrs: ClassVar[List[str]] = ["file_type"]

    def __init__(self, message: str, file_type: str = "doc"):
        super().__init__(
            message=message,
            code="DOCUMENT_CONVERSION_FAILED",
        )
        self.file_type = file_type


class DocumentSizeExceededError(KnowledgeSpaceError):
    """文档大小超限"""
    _serializable_attrs: ClassVar[List[str]] = ["size", "limit"]

    def __init__(self, size: int, limit: int):
        super().__init__(
            message=f"文档大小 ({size} bytes) 超过限制 ({limit} bytes)",
            code="DOCUMENT_SIZE_EXCEEDED",
        )
        self.size = size
        self.limit = limit


class DocumentCountExceededError(KnowledgeSpaceError):
    """文件数量超限"""
    _serializable_attrs: ClassVar[List[str]] = ["count", "limit"]

    def __init__(self, count: int, limit: int):
        super().__init__(
            message=f"文件数量 ({count}) 超过限制 ({limit})",
            code="DOCUMENT_COUNT_EXCEEDED",
        )
        self.count = count
        self.limit = limit


class DocumentAlreadyProcessingError(KnowledgeSpaceError):
    """文档正在处理中，不允许重复触发"""
    _serializable_attrs: ClassVar[List[str]] = ["document_id"]

    def __init__(self, document_id: int):
        super().__init__(
            message=f"文档 {document_id} 正在处理中，请等待处理完成后再操作",
            code="DOCUMENT_ALREADY_PROCESSING",
        )
        self.document_id = document_id


# ==================== 检索相关异常 ====================

class SearchError(KnowledgeSpaceError):
    """检索错误"""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="SEARCH_ERROR",
        )


class EmbeddingError(KnowledgeSpaceError):
    """向量化错误"""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="EMBEDDING_ERROR",
        )


class InvalidSearchModeError(KnowledgeSpaceError):
    """检索模式不可用"""
    _serializable_attrs: ClassVar[List[str]] = ["mode", "available_modes"]

    def __init__(
        self,
        mode: str,
        available_modes: List[str],
        reason: str = ""
    ):
        self.mode = mode
        self.available_modes = available_modes
        message = f"检索模式 '{mode}' 不可用"
        if reason:
            message += f"。{reason}"
        message += f"。可用模式: {', '.join(available_modes)}"
        super().__init__(
            message=message,
            code="INVALID_SEARCH_MODE",
        )


class InvalidSearchWeightError(KnowledgeSpaceError):
    """检索权重校验失败"""
    _serializable_attrs: ClassVar[List[str]] = ["weights"]

    def __init__(self, reason: str, **weights: float):
        self.weights = weights
        super().__init__(
            message=reason,
            code="INVALID_SEARCH_WEIGHT",
        )


class RerankError(KnowledgeSpaceError):
    """Rerank 重排序错误"""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="RERANK_ERROR",
        )


class QuestionGenerationError(KnowledgeSpaceError):
    """问题生成错误"""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="QUESTION_GENERATION_ERROR",
        )


# ==================== 通用异常 ====================

class UserNotFoundError(KnowledgeSpaceError):
    """用户不存在"""
    _serializable_attrs: ClassVar[List[str]] = ["email"]

    def __init__(self, email: str):
        super().__init__(
            message=f"邮箱 {email} 对应的用户不存在",
            code="USER_NOT_FOUND",
        )
        self.email = email


class InvalidParameterError(KnowledgeSpaceError):
    """参数无效"""
    _serializable_attrs: ClassVar[List[str]] = ["field"]

    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(
            message=message,
            code="INVALID_PARAMETER",
        )
        self.field = field


class InvalidDocumentStatusError(KnowledgeSpaceError):
    """无效的文档状态参数"""

    def __init__(self, status: str):
        super().__init__(
            message=f"无效的文档状态: {status}",
            code="INVALID_DOCUMENT_STATUS",
        )


__all__ = [
    "KnowledgeSpaceError",
    "SpaceNotFoundError",
    "SpaceAlreadyExistsError",
    "SpaceAccessDeniedError",
    "SpaceLimitExceededError",
    "MemberNotFoundError",
    "MemberAlreadyExistsError",
    "InviteExpiredError",
    "InviteInvalidError",
    "CannotRemoveLastAdminError",
    "CannotModifySelfRoleError",
    "KnowledgeBaseNotFoundError",
    "KnowledgeBaseAlreadyExistsError",
    "KnowledgeBaseAccessDeniedError",
    "KnowledgeBaseArchivedError",
    "KnowledgeBaseLimitExceededError",
    "DocumentNotFoundError",
    "DocumentAlreadyExistsError",
    "DocumentProcessingError",
    "DocumentInvalidTypeError",
    "DocumentSizeExceededError",
    "DocumentCountExceededError",
    "DocumentAlreadyProcessingError",
    "SearchError",
    "EmbeddingError",
    "InvalidSearchModeError",
    "InvalidSearchWeightError",
    "RerankError",
    "QuestionGenerationError",
    "UserNotFoundError",
    "InvalidParameterError",
    "InvalidDocumentStatusError",
]
