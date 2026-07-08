"""
模块初始化

知识空间模块的启动初始化
"""

from fastapi import FastAPI

from src.core.middleware.base_exception_handler import register_module_exceptions
from src.core.middleware.structured_logging import get_logger
from src.features.knowledge_space.api.exceptions import (
    KnowledgeSpaceError,
    # 空间相关
    SpaceNotFoundError,
    SpaceAlreadyExistsError,
    SpaceAccessDeniedError,
    SpaceLimitExceededError,
    # 成员相关
    MemberNotFoundError,
    MemberAlreadyExistsError,
    InviteExpiredError,
    InviteInvalidError,
    CannotRemoveLastAdminError,
    CannotModifySelfRoleError,
    # 知识库相关
    KnowledgeBaseNotFoundError,
    KnowledgeBaseAlreadyExistsError,
    KnowledgeBaseAccessDeniedError,
    KnowledgeBaseArchivedError,
    KnowledgeBaseLimitExceededError,
    # 文档相关
    DocumentNotFoundError,
    DocumentAlreadyExistsError,
    DocumentAlreadyProcessingError,
    DocumentProcessingError,
    DocumentInvalidTypeError,
    DocumentSizeExceededError,
    DocumentCountExceededError,
    # 检索相关
    SearchError,
    EmbeddingError,
    InvalidSearchModeError,
    InvalidSearchWeightError,
    RerankError,
    QuestionGenerationError,
    # 通用
    UserNotFoundError,
    InvalidParameterError,
    InvalidDocumentStatusError,
)


logger = get_logger(__name__)


async def init_knowledge_space_components(app: FastAPI) -> None:
    """
    初始化知识空间模块组件

    Args:
        app: FastAPI 应用实例
    """
    logger.info("初始化知识空间模块...")
    # Elasticsearch 检索服务按需创建，无需在此初始化
    logger.info("知识空间模块初始化完成")


def setup_knowledge_space_exception_handlers(app: FastAPI) -> None:
    """注册知识空间模块的异常处理器"""
    register_module_exceptions(app, status_map={
        # 空间相关
        SpaceNotFoundError: 404,
        SpaceAlreadyExistsError: 409,
        SpaceAccessDeniedError: 403,
        SpaceLimitExceededError: 429,
        # 成员相关
        MemberNotFoundError: 404,
        MemberAlreadyExistsError: 409,
        InviteExpiredError: 410,
        InviteInvalidError: 400,
        CannotRemoveLastAdminError: 403,
        CannotModifySelfRoleError: 403,
        # 知识库相关
        KnowledgeBaseNotFoundError: 404,
        KnowledgeBaseAlreadyExistsError: 409,
        KnowledgeBaseAccessDeniedError: 403,
        KnowledgeBaseArchivedError: 403,
        KnowledgeBaseLimitExceededError: 429,
        # 文档相关
        DocumentNotFoundError: 404,
        DocumentAlreadyExistsError: 409,
        DocumentAlreadyProcessingError: 409,
        DocumentProcessingError: 400,
        DocumentInvalidTypeError: 400,
        DocumentSizeExceededError: 400,
        DocumentCountExceededError: 400,
        # 检索相关
        SearchError: 400,
        EmbeddingError: 400,
        InvalidSearchModeError: 400,
        InvalidSearchWeightError: 400,
        RerankError: 400,
        QuestionGenerationError: 400,
        # 通用
        UserNotFoundError: 404,
        InvalidParameterError: 400,
        InvalidDocumentStatusError: 422,
        # 兜底
        KnowledgeSpaceError: 500,
    })
