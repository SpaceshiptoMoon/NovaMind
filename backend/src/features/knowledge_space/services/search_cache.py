"""检索缓存旁路失效入口：无检索引擎在场的写路径统一走这里。

双路径分工：请求内已持有 RetrievalEngine 时走引擎的
``invalidate_kb_search_cache``（经 cache_port 注入，可测）；删除/打标/
生命周期/wiki 同步/解析任务等旁路场景拿不到引擎实例，走本模块。键前缀
由 engines/rag 的 ``kb_search_cache_prefix`` 派生（键格式唯一权威出处），
本模块不持有任何键格式知识。

失败语义：只告警不抛出——失效失败的旧值存活至 TTL 过期（检索缓存全部
带 TTL，这是脏读上限），属于"能力缺失"而非"错误结果"，不得阻断调用方
的写操作。
"""
from novamind.engines.rag.retrieval_engine import kb_search_cache_prefix
from novamind.shared.cache.helpers import invalidate_matching
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


async def invalidate_kb_search_cache(kb_id: int) -> int:
    """失效单个知识库的全部检索缓存（含用户维度变体键）。

    Args:
        kb_id: 知识库 ID。

    Returns:
        实际删除的键数量。缓存层故障同样返回 0（无键可删与故障不可据此
        区分，故障细节由 helpers 层告警）；调用方需要区分时监听告警日志。
    """
    deleted = await invalidate_matching(f"{kb_search_cache_prefix(kb_id)}*")
    if deleted:
        logger.debug("知识库检索缓存已清理", kb_id=kb_id, deleted=deleted)
    return deleted
