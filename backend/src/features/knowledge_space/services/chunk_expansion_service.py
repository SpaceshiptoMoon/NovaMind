"""检索期上下文扩展服务：句子窗口扩窗 + 父子分块回带（SearchService 宿主层后处理）。

只对携带扩展元数据（expansion_type / chunk_role）的命中生效，存量 chunk 零成本直通。
权限不变量：扩窗取的是与命中同文档的邻居、回带取的是与命中同文档的父块——两者都与
已通过文档权限过滤（或 bypass 重放）的命中同属一个 document_id，结构上不存在跨文档
数据进入结果的通路，无需重放 hidden_doc_ids 过滤。

失败方向安全：任何扩展失败（邻居拉取失败/父块缺失/元数据残缺）都保留原子块文本继续
返回——能力缺失（不扩展）优于错误结果（丢内容/抛错打断检索）。
"""
from novamind.core.middleware.structured_logging import get_logger

# 扩窗单文档拉取上限：get_document_chunks 分页参数，防超长文档整文档进内存。
# 句窗口每命中最多取 (2*window+1) 条、同文档多命中区间并集后仍远小于此上限。
WINDOW_DOC_CHUNK_FETCH_LIMIT = 500
# 每侧扩窗句数防御上限（与 SplittingConfig.window_size 的 le=10 一致；元数据
# 来自已索引 chunk，防御历史/手写脏值）。
MAX_WINDOW_SIZE = 10

logger = get_logger(__name__)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """合并重叠或相邻的索引区间（含端点闭区间）。"""
    merged: list[tuple[int, int]] = []
    for lo, hi in sorted(ranges):
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


async def expand_search_results(es_client, space_id: int, results: list[dict]) -> list[dict]:
    """按命中 chunk 的扩展元数据做检索期上下文扩展，原列表就地替换 content。

    句子窗口：命中子块 content 替换为 chunk_index±window 邻居拼接文本；
    父子分块：命中子块 content 替换为父块全文。两种扩展都把原子块文本保留进
    ``metadata.expansion.retrieved_content`` 供溯源，并打 ``metadata.expansion``
    幂等标记（重复进入跳过）。同文档多命中的重叠窗口合并为一个区间并剔除
    被吞并的低分命中（结果数不膨胀）。

    Args:
        es_client: ElasticsearchClient 实例（get_document_chunks / get_chunk）。
        space_id: 空间 ID（决定目标索引）。
        results: 检索结果 dict 列表（引擎 enrich 后形状），就地修改并返回。

    Returns:
        扩展后的结果列表；无扩展元数据/全部失败时原样返回。整体兜底：扩展
        异常记日志后返回当前结果，不打断检索主流程。
    """
    if not results:
        return results
    try:
        return await _expand_inner(es_client, space_id, results)
    except Exception as exc:
        logger.warning(
            "检索期上下文扩展失败，保留原始命中返回",
            space_id=space_id, error=str(exc),
        )
        return results


async def _expand_inner(es_client, space_id: int, results: list[dict]) -> list[dict]:
    """扩展主逻辑（expand_search_results 的兜底内层）。"""
    window_hits: dict[int, list[dict]] = {}
    parent_hits: list[dict] = []
    seen_chunk_ids: set[str] = set()
    for r in results:
        meta = r.get("metadata") or {}
        if meta.get("expansion"):
            continue  # 幂等护栏：已扩展（引擎缓存复入/重复调用）跳过
        # 同 chunk_id 多份命中（sub_query 双路重复召回等脏入参的防御纵深）：
        # 只扩展第一份，其余保持原始形态——两份独立 dict 骗不过对象级幂等标记。
        cid = r.get("chunk_id")
        if cid and cid in seen_chunk_ids:
            continue
        if cid:
            seen_chunk_ids.add(cid)
        if meta.get("expansion_type") == "sentence_window":
            window_hits.setdefault(r.get("document_id"), []).append(r)
        elif meta.get("chunk_role") == "child" and meta.get("parent_chunk_id"):
            parent_hits.append(r)
    if not window_hits and not parent_hits:
        return results  # 存量 chunk 零成本直通

    # —— 句子窗口：按文档分组，区间并集合并，单次拉邻居 ——
    for doc_id, hits in window_hits.items():
        if doc_id is None:
            continue
        window_sizes = [
            h["metadata"].get("expansion_window_size") for h in hits
            if isinstance(h["metadata"].get("expansion_window_size"), int)
        ]
        window_size = min(window_sizes) if window_sizes else 0
        if window_size <= 0:
            continue  # window_size=0 = 不扩窗（合法配置）
        window_size = min(window_size, MAX_WINDOW_SIZE)
        chunks_by_index = await _fetch_doc_chunks_by_index(es_client, space_id, doc_id)
        if not chunks_by_index:
            continue  # 拉取失败/文档已清 → 保留原子块文本
        # 每个命中独立计算窗口；窗口重叠/相邻的命中合并为一个结果（保留最高
        # 分），被吞并命中的窗口区间**并入**保留命中的区间——低分命中周围
        # 的邻居同样是高分命中上下文的一部分，丢弃会造成窗口缺口。
        hits_sorted = sorted(hits, key=lambda h: h.get("score") or 0.0, reverse=True)
        merged_ranges: list[tuple[int, int]] = []
        surviving: list[dict] = []
        merged_out: set[int] = set()
        for hit in hits_sorted:
            idx = hit.get("chunk_index")
            if not isinstance(idx, int):
                continue
            lo, hi = idx - window_size, idx + window_size
            touching = [
                (mlo, mhi) for mlo, mhi in merged_ranges
                if lo <= mhi + 1 and mlo - 1 <= hi
            ]
            if touching:
                merged_out.add(id(hit))  # 窗口与已保留命中重叠 → 被吞并
                for mlo, mhi in touching:
                    merged_ranges.remove((mlo, mhi))
                merged_ranges.append(
                    (min(lo, *(mlo for mlo, _ in touching)),
                     max(hi, *(mhi for _, mhi in touching)))
                )
                merged_ranges.sort()
                continue
            merged_ranges.append((lo, hi))
            surviving.append(hit)
        if merged_out:
            results[:] = [r for r in results if id(r) not in merged_out]
        # 命中句融入窗口区间的阅读序（chunk_index 升序拼接），命中句不是
        # 「窗口头部」——前邻居排在命中句之前，否则窗口跨命中两侧时阅读序断裂。
        for hit in surviving:
            idx = hit["chunk_index"]
            lo, hi = _hit_range(hit, merged_ranges)
            window_text = "\n".join(
                chunks_by_index[i]["content"]
                for i in sorted(chunks_by_index)
                if lo <= i <= hi
            )
            original = hit.get("content") or ""
            if not window_text.strip():
                continue  # 邻居全缺 → 无扩展价值，保留原样
            hit["metadata"]["expansion"] = {
                "type": "sentence_window",
                "retrieved_content": original,
                "window_chunk_range": [lo, hi],
            }
            hit["content"] = window_text

    # —— 父子分块：按 parent_chunk_id 回带父块全文 ——
    for hit in parent_hits:
        parent = await es_client.get_chunk(space_id, hit["metadata"]["parent_chunk_id"])
        if not parent or not (parent.get("content") or "").strip():
            continue  # 父块缺失 → 保留子块原文（能力缺失方向）
        original = hit.get("content") or ""
        hit["metadata"]["expansion"] = {
            "type": "parent_child",
            "retrieved_content": original,
            "parent_chunk_id": hit["metadata"]["parent_chunk_id"],
        }
        hit["content"] = parent["content"]

    return results


def _hit_range(hit: dict, merged_ranges: list[tuple[int, int]]) -> list[int]:
    """取命中自身所在的合并区间（无匹配时退化为单点区间）。"""
    idx = hit.get("chunk_index")
    if not isinstance(idx, int):
        return [0, 0]
    for lo, hi in merged_ranges:
        if lo <= idx <= hi:
            return [lo, hi]
    return [idx, idx]


async def _fetch_doc_chunks_by_index(
    es_client, space_id: int, document_id: int,
) -> dict[int, dict]:
    """按 chunk_index 建索引拉取文档全部分块；失败返回空 dict（调用方降级不扩展）。"""
    try:
        doc = await es_client.get_document_chunks(
            space_id, document_id, 0, WINDOW_DOC_CHUNK_FETCH_LIMIT,
        )
    except Exception as exc:
        logger.warning(
            "扩窗拉取文档分块失败",
            space_id=space_id, document_id=document_id, error=str(exc),
        )
        return {}
    return {
        c["chunk_index"]: c
        for c in doc.get("items", [])
        if isinstance(c.get("chunk_index"), int) and (c.get("content") or "").strip()
    }
