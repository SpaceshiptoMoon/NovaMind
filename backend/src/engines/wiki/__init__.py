"""Wiki 纯函数引擎：互链注入/候选去重/句柄表/slug 规范化/分类法。

通用模块（engines 层）——纯数据转换，无 ORM/存储/session 依赖；prompt 经
shared 中央注册表。Wiki 的持久化（四表 ORM/仓储）、ES 同步、任务编排、
API 全部在 features/knowledge_space（业务层连接）。
"""
from novamind.engines.wiki.dedup import (
    DEDUP_CANDIDATE_SCORE_FLOOR,
    DEDUP_CORPUS_HARD_LIMIT,
    DedupCandidate,
    dedup_pair_score,
)
from novamind.engines.wiki.handles import HandleTable
from novamind.engines.wiki.slug import normalize_slug

__all__ = [
    "DEDUP_CANDIDATE_SCORE_FLOOR",
    "DEDUP_CORPUS_HARD_LIMIT",
    "DedupCandidate",
    "HandleTable",
    "dedup_pair_score",
    "normalize_slug",
]
