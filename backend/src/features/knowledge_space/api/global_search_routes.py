"""全局检索路由：跨空间消费侧检索入口（门户/顶栏搜索直达）。"""

from fastapi import APIRouter, Body, Depends, Request
from novamind.features.knowledge_space.api.dependencies import (
    get_audit_service,
    get_current_user_id,
    get_global_search_service,
)
from novamind.features.knowledge_space.schemas.search_schema import (
    GlobalSearchRequest,
    GlobalSearchResponse,
)
from novamind.features.knowledge_space.services.audit_service import AuditService
from novamind.features.knowledge_space.services.global_search_service import (
    GlobalSearchService,
)

router = APIRouter(tags=["全局检索"])


@router.post(
    "",
    response_model=GlobalSearchResponse,
    summary="跨空间全局检索",
    description="""
跨空间全局检索：一次查询搜索当前用户可访问的全部空间（活跃成员空间 ∪ 公开空间）
下的全部活跃知识库，各库结果经 RRF 融合排序。

**检索范围**：无需指定空间/知识库；权限链与空间内检索一致（成员或 PUBLIC，
成员的文档级隐藏清单逐空间生效）。

**模式回退**（逐库自动，无需干预）：
- 未启用问题生成的库：`question_*` / `all_*` 降级对应 `content_*`
- 空间未配置 embedding（或模型不可用）的库：向量/混合模式降级 BM25

**容错**：单库检索失败不炸全局，进 `skipped_kbs` 返回；参与库数量超
`knowledge_base.retrieval.global_search_max_kbs` 上限的库截断并注明 `fan_out_limit`。

**LLM 回答**：`llm.enabled=true` 时对合并后 Top5 单次生成（`answer` 字段）。
""",
)
async def global_search(
    request: Request,
    data: GlobalSearchRequest = Body(...),
    user_id: int = Depends(get_current_user_id),
    service: GlobalSearchService = Depends(get_global_search_service),
    audit_service: AuditService = Depends(get_audit_service),
):
    """跨空间全局检索。

    URL: POST /api/v1/search

    请求体示例:
    ```json
    {
        "query": "跨空间的入职流程说明",
        "search_mode": "content_hybrid",
        "top_k": 10,
        "llm": {"enabled": true}
    }
    ```
    """
    result = await service.global_search(user_id=user_id, request=data)

    # 审计逐空间落账（有命中的空间各一条；运营区「最近提问」对全局检索可见）
    space_counts = result.pop("space_result_counts", {})
    algorithm = result["search_mode"].split("_")[-1]
    for space_id, count in space_counts.items():
        await audit_service.log_search(
            space_id=space_id,
            user_id=user_id,
            query=data.query,
            search_type=algorithm,
            result_count=count,
            request=request,
        )

    return GlobalSearchResponse(**result)
