"""
检索路由

统一的检索接口，支持多种检索策略和检索目标
使用加权 RRF 融合混合检索结果
"""

from typing import Annotated
from fastapi import APIRouter, Depends, Request, Body, Path

from novamind.setting.yaml_config import get_config
from novamind.features.knowledge_space.schemas.search_schema import (
    SearchRequest,
    SearchResponse,
    SearchModesResponse,
    KnowledgeBaseModelConfigResponse,
    SEARCH_MODES,
)
from novamind.features.knowledge_space.api.dependencies import (
    get_search_service,
    get_audit_service,
    get_current_user_id,
    validate_space_access,
)
from novamind.features.knowledge_space.api.exceptions import KnowledgeBaseNotFoundError
from novamind.features.knowledge_space.services.search_service import SearchService
from novamind.features.knowledge_space.services.audit_service import AuditService
from novamind.features.user.api.dependencies import get_model_config_service
from novamind.features.user.services.model_config_service import ModelConfigService

from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBaseStatus

router = APIRouter(tags=["知识检索"])


async def _validate_active_kb(kb_id: int, space_id: int, search_service: SearchService):
    """验证知识库属于指定空间且状态为活跃"""
    kb = await search_service.get_knowledge_base(kb_id)
    if not kb or kb.space_id != space_id or kb.status != KnowledgeBaseStatus.ACTIVE:
        raise KnowledgeBaseNotFoundError(kb_id)
    return kb


# TODO: 未来考虑将 kb_id 从请求体参数移到 URL 路径参数（如 /search/{kb_id}），
# 以更好地符合 RESTful 设计规范。当前保持请求体传参以兼容现有客户端。


@router.post(
    "",
    response_model=SearchResponse,
    summary="统一检索接口",
    description="""
统一检索接口，支持多种检索模式。

**注意**: kb_id 参数会校验是否属于当前 space_id 指定的空间，且知识库必须为活跃状态（status=1）。
如果 kb_id 不属于该空间或知识库未激活，将返回 404 错误。

**检索模式 (search_mode)**:
格式: `{target}_{algorithm}`

| 模式 | 说明 | 需要问题生成 |
|-----|------|------------|
| `content_bm25` | 内容全文检索 | 否 |
| `content_vector` | 内容向量检索 | 否 |
| `content_hybrid` | 内容混合检索（默认） | 否 |
| `question_bm25` | 问题全文检索 | 是 |
| `question_vector` | 问题向量检索 | 是 |
| `question_hybrid` | 问题混合检索 | 是 |
| `all_bm25` | 全字段全文检索 | 是 |
| `all_vector` | 全字段向量检索 | 是 |
| `all_hybrid` | 全字段全算法融合 | 是 |

**推荐**:
- 默认使用 `content_hybrid` 进行内容混合检索
- 启用问题生成后，使用 `all_hybrid` 获得最强召回效果
""",
)
async def search(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    data: Annotated[SearchRequest, Body(...)],
    user_id: int = Depends(get_current_user_id),
    validated: tuple = Depends(validate_space_access),
    search_service: SearchService = Depends(get_search_service),
    audit_service: AuditService = Depends(get_audit_service),
):
    """
    统一检索接口

    URL: POST /api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/search

    请求体示例:
    ```json
    {
        "query": "如何使用 FastAPI",
        "search_mode": "content_hybrid",
        "top_k": 10,
        "weights": {
            "vector_weight": 0.7,
            "bm25_weight": 0.3,
            "content_weight": 0.6,
            "question_weight": 0.4,
            "rrf_k": 60
        }
    }
    ```
    """
    # 执行检索
    space, _ = validated

    # 验证 kb_id 属于当前空间
    await _validate_active_kb(kb_id, space_id, search_service)

    result = await search_service.search(
        space_id=space_id,
        kb_id=kb_id,
        user_id=user_id,
        request=data,
    )

    # 记录审计日志（提取算法类型用于审计分类）
    search_mode_str = data.search_mode.value if hasattr(data.search_mode, "value") else str(data.search_mode)
    # search_mode 格式为 "{target}_{algorithm}"，提取最后一段作为算法类型
    algorithm_type = search_mode_str.split("_")[-1] if "_" in search_mode_str else search_mode_str
    await audit_service.log_search(
        space_id=space_id,
        user_id=user_id,
        query=data.query,
        search_type=algorithm_type,
        result_count=len(result["results"]),
        request=request,
    )

    # 权重与阈值统一回显用户入参（不依赖检索模式），便于客户端确认实际生效配置
    weights = data.weights
    return SearchResponse(
        results=result["results"],
        total=len(result["results"]),
        query=data.query,
        search_mode=result["search_mode"],
        original_mode=result.get("original_mode"),
        mode_fallback=result.get("mode_fallback", False),
        top_k=data.top_k,
        vector_weight=weights.vector_weight if weights else None,
        bm25_weight=weights.bm25_weight if weights else None,
        content_weight=weights.content_weight if weights else None,
        question_weight=weights.question_weight if weights else None,
        rrf_k=weights.rrf_k if weights else None,
        score_threshold=data.score_threshold,
        elapsed_ms=result.get("elapsed_ms"),
        cached=result.get("cached", False),
        answer=result.get("answer"),
        answer_model=result.get("answer_model"),
        answer_elapsed_ms=result.get("answer_elapsed_ms"),
        rewritten_queries=result.get("rewritten_queries"),
    )


@router.get(
    "/modes",
    response_model=SearchModesResponse,
    summary="获取可用检索模式",
    description="获取当前知识库支持的检索模式列表。kb_id 会校验是否属于当前 space_id 且知识库为活跃状态。",
)
async def get_search_modes(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    validated: tuple = Depends(validate_space_access),
    search_service: SearchService = Depends(get_search_service),
):
    """
    获取可用检索模式

    URL: GET /api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/search/modes
    """
    # 获取知识库配置
    space, _ = validated

    # 验证 kb_id 属于当前空间并获取 KB
    kb = await _validate_active_kb(kb_id, space_id, search_service)

    # 获取知识库可用的检索模式
    available_modes = await search_service.get_available_modes(
        kb_id=kb_id,
    )

    text_modes = [
        mode for mode in SEARCH_MODES
        if mode["mode"] in available_modes
    ]

    return {
        "modes": text_modes,
        "total": len(text_modes),
    }


@router.get(
    "/model-config",
    response_model=KnowledgeBaseModelConfigResponse,
    summary="获取知识库模型配置",
    description="获取当前知识库使用的 Embedding 模型配置，以及用户可用的 LLM、Rerank 模型列表。",
)
async def get_model_config(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    user_id: int = Depends(get_current_user_id),
    validated: tuple = Depends(validate_space_access),
    search_service: SearchService = Depends(get_search_service),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
):
    """
    获取知识库模型配置

    URL: GET /api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/search/model-config

    返回:
    - embedding_model: 知识库使用的 Embedding 模型名称
    - embedding_dimension: 向量维度
    - default_llm_model: 默认 LLM 模型（全局配置）
    - default_rerank_model: 默认 Rerank 模型（全局配置）
    - available_embedding_models: 用户可用的 Embedding 模型列表
    - available_llm_models: 用户可用的 LLM 模型列表
    - available_rerank_models: 用户可用的 Rerank 模型列表
    """
    # 验证空间访问权限
    space, _ = validated

    # 验证 kb_id 属于当前空间
    await _validate_active_kb(kb_id, space_id, search_service)

    # 获取全局配置
    config = get_config()

    # 获取空间的 Embedding 模型（空间级别统一管理）
    embedding_model = space.embedding_model
    embedding_dimension = space.embedding_dimension

    # 如果维度未配置，使用 Elasticsearch 默认维度
    if not embedding_dimension:
        embedding_dimension = config.elasticsearch.default_embedding_dim

    # 获取用户可用的模型列表
    available_embedding_models = await model_config_service.list_available_models(
        user_id=user_id,
        model_type="embedding",
    )
    available_llm_models = await model_config_service.list_available_models(
        user_id=user_id,
        model_type="llm",
    )
    available_rerank_models = await model_config_service.list_available_models(
        user_id=user_id,
        model_type="rerank",
    )

    # 从数据库获取用户默认模型名称
    default_llm_model = await model_config_service.get_user_default_model_name(user_id, "llm")
    default_rerank_model = await model_config_service.get_user_default_model_name(user_id, "rerank")

    return KnowledgeBaseModelConfigResponse(
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        default_llm_model=default_llm_model,
        default_rerank_model=default_rerank_model,
        available_embedding_models=available_embedding_models,
        available_llm_models=available_llm_models,
        available_rerank_models=available_rerank_models,
    )
