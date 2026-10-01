"""内容矛盾检测（kb-ops D）：同 KB 高相似 chunk 对 → LLM 判定语义矛盾 → 建议队列。

设计要点（计划 §D 验收 + 安全硬规则）：
- 候选对保守：同 KB 内 chunk 文本字符 3-gram 相似度落在「相似但非重复」
  阈值带（0.55~0.9）才成对——低于下限不相关，高于上限大概率是重复/改写；
- LLM 判定只在候选对上跑（成本受控），矛盾判定失败/不确定 = 不建建议
  （宁漏勿误——误报矛盾会浪费人工裁决时间）；
- accept 的动作仅是「通知两位文档 owner 人工对齐」，平台永不自动改写/删除；
- cron 低频（每周）+ 手动触发端点；单 KB 每轮建议数上限（防刷屏）。

判定与复用：字符 3-gram 相似度复用 query_reformulate_detector.char_trigram_similarity
（同一实现，口径统一）。
"""
from __future__ import annotations

from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_ops.services.query_reformulate_detector import (
    char_trigram_similarity,
    normalize_query,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# 候选对相似度带（归一化文本字符 3-gram Jaccard）
# 下限 0.55：低于此基本不相关，LLM 判定浪费；
# 上限 0.99：完全相同（1.0）是重复而非矛盾；「高度相似+关键差异」（v2 抄 v1
# 改个数字，实测可达 0.98）是矛盾最高发形态——上限尽量放宽交给 LLM 判定，
# 成本由 MAX_SUGGESTIONS_PER_RUN 与 MAX_CHUNKS_PER_RUN 双闸控制。
SIMILARITY_BAND_LOW = 0.55
SIMILARITY_BAND_HIGH = 0.99
# 每轮检测的 chunk 采样上限与建议上限（成本/刷屏双闸）
MAX_CHUNKS_PER_RUN = 100
MAX_SUGGESTIONS_PER_RUN = 5
# chunk 最短长度（太短无法判定语义矛盾）
MIN_CHUNK_LENGTH = 80

CONTRADICTION_PROMPT_KEY = "kb_ops_contradiction_check"


async def detect_contradictions(
    session: AsyncSession,
    *,
    space_id: int,
    kb_id: int,
    user_id: int,
    max_suggestions: int = MAX_SUGGESTIONS_PER_RUN,
) -> list[dict[str, Any]]:
    """对 KB 做一轮矛盾检测：采样 chunks → 候选对 → LLM 判定 → 建议落库。

    Returns:
        建议列表 [{suggestion_id, doc_a, doc_b, chunk_a, chunk_b, reason}]。
    """
    from novamind.features.knowledge_ops.repository.suggestion_repository import (
        SUGGESTION_CONTRADICTION,
        SuggestionRepository,
    )
    from novamind.features.knowledge_space.api.dependencies import (
        get_elasticsearch_client,
    )

    es_client = await get_elasticsearch_client()
    index_name = es_client.generate_index_name(space_id)
    try:
        result = await es_client.es_client.search(
            index=index_name,
            query={"bool": {"filter": [
                {"term": {"kb_id": kb_id}},
                {"bool": {"must_not": [{"terms": {"lifecycle_status": ["superseded", "archived"]}}]}},
            ]}},
            size=MAX_CHUNKS_PER_RUN,
            _source=["content", "document_id"],
        )
    except Exception as e:
        logger.warning("矛盾检测 chunk 拉取失败", kb_id=kb_id, error=str(e))
        return []

    chunks = [
        {
            "chunk_id": h["_id"],
            "document_id": h["_source"].get("document_id"),
            "text": h["_source"].get("content", ""),
        }
        for h in result.get("hits", {}).get("hits", [])
        if len(h["_source"].get("content", "")) >= MIN_CHUNK_LENGTH
    ]
    if len(chunks) < 2:
        return []

    # 候选对（阈值带内，同文档内不对——同文档自相矛盾另算，v1 只查跨文档）
    candidates: list[tuple[dict, dict, float]] = []
    norms = [(c, normalize_query(c["text"])) for c in chunks]
    for i in range(len(norms)):
        for j in range(i + 1, len(norms)):
            ca, na = norms[i]
            cb, nb = norms[j]
            if ca["document_id"] == cb["document_id"]:
                continue
            sim = char_trigram_similarity(na, nb)
            if SIMILARITY_BAND_LOW <= sim <= SIMILARITY_BAND_HIGH:
                candidates.append((ca, cb, sim))
    # 相似度高的对优先判定（最可能真矛盾的先占建议名额）
    candidates.sort(key=lambda x: -x[2])

    llm_client = await _resolve_llm(session, user_id)
    suggestions: list[dict[str, Any]] = []
    repo = SuggestionRepository(session)
    for ca, cb, sim in candidates:
        if len(suggestions) >= max_suggestions:
            break
        verdict = await _llm_check_contradiction(llm_client, ca["text"], cb["text"])
        if not verdict:
            continue
        created = await repo.upsert_open_suggestion(
            space_id=space_id,
            kb_id=kb_id,
            suggestion_type=SUGGESTION_CONTRADICTION,
            old_doc_id=ca["document_id"],
            new_doc_id=cb["document_id"],
            score=int(sim * 10000),
            reason=verdict,
        )
        if created is not None:
            suggestions.append({
                "suggestion_id": created.id,
                "doc_a": ca["document_id"],
                "doc_b": cb["document_id"],
                "chunk_a": ca["chunk_id"],
                "chunk_b": cb["chunk_id"],
                "similarity": round(sim, 4),
                "reason": verdict,
            })

    if suggestions:
        await session.commit()
        logger.info("矛盾检测完成", kb_id=kb_id, suggestions=len(suggestions))
    return suggestions


async def _resolve_llm(session: AsyncSession, user_id: int):
    """解析用户默认 LLM 客户端（公共面）。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    mcs = ModelConfigService(session)
    model_name = await mcs.get_user_default_model_name(user_id, "llm")
    if not model_name:
        raise RuntimeError(f"用户 {user_id} 未配置默认 LLM 模型")
    return await mcs.get_llm_client_by_model(user_id=user_id, model=model_name)


async def _llm_check_contradiction(llm_client, text_a: str, text_b: str) -> str | None:
    """LLM 判定两段内容是否语义矛盾。矛盾返回判定理由；非矛盾/失败返回 None（宁漏勿误）。"""
    import json
    import re

    prompt = (
        "判断以下两段知识库内容是否存在语义矛盾（同一事实给出不一致的表述，"
        "如数字、流程、结论冲突）。仅基于文本本身判断，不要引入外部知识。\n\n"
        f"内容 A：\n{text_a[:800]}\n\n内容 B：\n{text_b[:800]}\n\n"
        '只输出 JSON：{"contradiction": true/false, "reason": "简短说明"}'
    )
    try:
        response = await llm_client.generate_text(prompt=prompt, max_tokens=300)
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.strip(), flags=re.MULTILINE)
        data = json.loads(cleaned)
        if isinstance(data, dict) and data.get("contradiction") is True:
            return (data.get("reason") or "LLM 判定存在语义矛盾")[:500]
        return None
    except Exception as e:
        # 判定失败不建建议（宁漏勿误）
        logger.warning("矛盾判定失败（跳过该对）", error=str(e))
        return None
