"""文档级检索权限过滤（kb-ops backlog：permission_boundary 的检索侧地基）。

语义：SpaceMember.custom_permissions.documents.hidden_doc_ids 列出对该成员
不可见的文档 ID；检索结果在宿主侧（SearchService）剔除这些文档的 chunk。
引擎保持「不做权限校验」的端口边界（R4）；缓存键已按 user_id 分段（引擎
_get_search_cache_key 预留），过滤不会串用户。

设计取舍：过滤做在结果层而非 ES 查询层——hidden 清单可短会话缓存、引擎
零改动、权限语义集中在宿主；top_k 截断在过滤前发生，意味着隐藏文档的
chunk 会占掉名额（边缘情况：全被隐藏时可能空结果）——可接受（安全方向：
宁可少给不给错）。
"""
from __future__ import annotations

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# custom_permissions.documents 下新增的键（与 SpaceAccessChecker.CAPABILITY_KEYS
# 的能力型键并存；文档 ID 清单型，语义不同故单独维护）
HIDDEN_DOC_IDS_KEY = "hidden_doc_ids"


def extract_hidden_doc_ids(custom_permissions: dict | None) -> list[int]:
    """从 custom_permissions 提取 hidden_doc_ids（容错：坏类型剔除，bool 是
    int 子类须显式排除——True/False 不是合法文档 ID）。"""
    if not custom_permissions or not isinstance(custom_permissions, dict):
        return []
    docs = custom_permissions.get("documents")
    if not docs or not isinstance(docs, dict):
        return []
    raw = docs.get(HIDDEN_DOC_IDS_KEY)
    if not isinstance(raw, list):
        return []
    return [
        int(x) for x in raw
        if isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0
    ]


def filter_results_by_permission(
    results: list[dict[str, Any]],
    hidden_doc_ids: list[int],
) -> list[dict[str, Any]]:
    """按隐藏文档清单剔除检索结果（就地语义的纯函数版本，返回新列表）。"""
    if not hidden_doc_ids or not results:
        return results
    hidden = set(hidden_doc_ids)
    return [r for r in results if r.get("document_id") not in hidden]


async def get_hidden_doc_ids_for_member(
    session,
    *,
    space_id: int,
    user_id: int,
) -> list[int]:
    """查成员的隐藏文档清单（无成员行/无 custom_permissions 返回空 = 全可见）。

    短会话调用（请求级 session 传入）；公开空间匿名访问（无成员行）不限制
    ——文档级权限只作用于显式成员。
    """
    from sqlalchemy import and_, select

    from novamind.features.knowledge_space.models.space_member import (
        MemberStatus,
        SpaceMember,
    )

    row = (await session.execute(
        select(SpaceMember.custom_permissions).where(and_(
            SpaceMember.space_id == space_id,
            SpaceMember.user_id == user_id,
            SpaceMember.status == MemberStatus.ACTIVE,
        ))
    )).scalar_one_or_none()
    if row is None:
        return []
    return extract_hidden_doc_ids(row)


async def apply_document_permission_filter(
    session,
    *,
    space_id: int,
    user_id: int,
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """检索结果过滤入口：查清单 → 剔除。清单为空零成本返回原列表。"""
    try:
        hidden = await get_hidden_doc_ids_for_member(
            session, space_id=space_id, user_id=user_id,
        )
    except Exception as e:
        # 失败方向安全：查不到权限清单时不过滤（宽松方向），并告警——
        # 权限系统故障不应表现为检索全空
        logger.warning(
            "文档权限清单查询失败（本次不过滤）",
            space_id=space_id, user_id=user_id, error=str(e),
        )
        return results
    filtered = filter_results_by_permission(results, hidden)
    if len(filtered) != len(results):
        logger.info(
            "文档级权限过滤生效",
            space_id=space_id, user_id=user_id,
            before=len(results), after=len(filtered),
        )
    return filtered
