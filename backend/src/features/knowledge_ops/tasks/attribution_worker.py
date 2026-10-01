"""归因 worker（kb-ops A1）：对零命中/低分/点踩的问答做四分归因并写回消息行。

归因四分法（设计文档 §5.2）：
- content_gap：库内真无相关内容（重放检索零命中，降阈值仍零命中）
- retrieval_failure：有相关内容但没召回（降阈值能命中而原始阈值零命中——切分/参数问题）
- quality_decay：召回主体是失效文档（superseded/archived 占比过半）
- permission_boundary：内容存在但提问者无权（检索层权限接线前为 stub，见
  attribute_single_event 内注释）

判据与批次 2b 看板同源（question_answers.extra.retrieval + answer_status + 点踩），
归因结果写回 extra.attribution，gap 聚合（A2）与看板可同源联查。

失败方向安全：任何一步失败保持 attribution 为空（宁缺归因，不给错误归因）；
幂等：已有 attribution 不覆盖（重放检索结果有时变异性，覆盖=引入噪声）。
"""
from datetime import datetime, timedelta
from typing import Any

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 缺省参数（YAML knowledge_ops.attribution_* 可覆盖；读配置失败回退这些值）
LOW_SCORE_THRESHOLD = 0.35
ATTRIBUTION_LOOKBACK_DAYS = 7
ATTRIBUTION_BATCH_LIMIT = 50
REPLAY_LOW_THRESHOLD = 0.15
# quality_decay 判定：命中来源中失效文档（superseded/archived）占比下限
DEAD_DOC_RATIO = 0.5

# 归因常量（extra.attribution 取值域）
ATTR_CONTENT_GAP = "content_gap"
ATTR_RETRIEVAL_FAILURE = "retrieval_failure"
ATTR_QUALITY_DECAY = "quality_decay"
ATTR_PERMISSION_BOUNDARY = "permission_boundary"


def _load_config() -> dict:
    """读归因参数（YAML 可配，异常回退模块常量）。"""
    try:
        from novamind.setting.yaml_config import get_config

        ko = get_config().knowledge_ops
        return {
            "low_score_threshold": float(ko.attribution_low_score_threshold),
            "replay_low_threshold": float(ko.attribution_replay_low_threshold),
            "lookback_days": int(ko.attribution_lookback_days),
            "batch_limit": int(ko.attribution_batch_limit),
        }
    except Exception as e:
        logger.warning("归因配置读取失败，使用缺省值", error=str(e))
        return {
            "low_score_threshold": LOW_SCORE_THRESHOLD,
            "replay_low_threshold": REPLAY_LOW_THRESHOLD,
            "lookback_days": ATTRIBUTION_LOOKBACK_DAYS,
            "batch_limit": ATTRIBUTION_BATCH_LIMIT,
        }


async def attribute_pending_events(ctx: dict | None = None) -> dict[str, int]:
    """归因扫批任务：拉取未归因的失败问答 → 重放检索 → 写回 extra.attribution。

    cron 周期驱动；返回归因计数分布（供日志）。单条失败不中断批（逐条容错），
    失败条目 attribution 留空、下轮自然重试（幂等谓词只挑未归因的）。
    """
    from sqlalchemy import and_, func, or_, select

    from novamind.core.database.database import get_db_session
    from novamind.features.qa.models.qa_feedback import MessageFeedback
    from novamind.features.qa.models.question_answer import QuestionAnswer

    cfg = _load_config()
    counts: dict[str, int] = {}
    async with get_db_session() as db:
        now = datetime.now()
        window_start = now - timedelta(days=cfg["lookback_days"])

        # 失败问答候选：与批次 2b 看板同口径（零命中 or 低分 or 点踩），且未归因
        extra = QuestionAnswer.extra
        # JSON 数值比较：CAST 为 Numeric 再比（字符串比较 0.35 < 0.9 会出错；
        # 与 space_stats_repository.list_low_score_messages 同款写法）
        from sqlalchemy import Numeric

        max_score = func.cast(extra["retrieval"]["max_score"].as_string(), Numeric(10, 6))
        zero_hit_cond = or_(
            func.coalesce(extra["retrieval"]["result_count"].as_integer(), -1) == 0,
            func.coalesce(extra["answer_status"].as_string(), "") == "refused",
        )
        low_cond = and_(max_score.isnot(None), max_score < cfg["low_score_threshold"])
        down_subq = (
            select(MessageFeedback.message_id).where(
                MessageFeedback.rating == "down",
                MessageFeedback.created_at >= window_start,
            )
        )
        conditions = [
            QuestionAnswer.role == "assistant",
            # space 门槛不能硬卡：消息行不回填 space_id（O2 教训），点踩/低分候选
            # 的空间锚点在反馈表/会话配置里，由 attribute_single_event 兜底解析。
            # 这里只排除「连会话都没有的脏数据」交给单条归因的 ValueError 路径。
            QuestionAnswer.created_at >= window_start,
            func.coalesce(extra["attribution"].as_string(), "") == "",
            or_(zero_hit_cond, low_cond, QuestionAnswer.id.in_(down_subq)),
        ]
        rows = (await db.execute(
            select(QuestionAnswer.id)
            .where(and_(*conditions))
            .order_by(QuestionAnswer.id)
            .limit(cfg["batch_limit"])
        )).all()

        message_ids = [r[0] for r in rows]
        logger.info("归因扫批开始", pending=len(message_ids))
        for message_id in message_ids:
            try:
                attr = await attribute_single_event(db, message_id)
                counts[attr] = counts.get(attr, 0) + 1
            except Exception as e:
                logger.warning("单条归因失败（下轮重试）", message_id=message_id, error=str(e))

    if counts:
        logger.info("归因扫批完成", counts=counts)
    return counts


async def attribute_single_event(db, message_id: int) -> str:
    """单条归因：重放检索 → 四分判定 → 写回 extra.attribution。

    Args:
        db: 数据库会话（调用方管理事务）。
        message_id: assistant 消息 ID。

    Returns:
        归因常量（ATTR_* 之一）。

    Raises:
        ValueError: 消息不存在/非 assistant/无 space_id/找不到相邻 user 查询
            （均属不可归因，调用方记 warning 跳过）。
    """
    from sqlalchemy import select

    from novamind.features.qa.models.question_answer import QuestionAnswer

    row = (await db.execute(
        select(QuestionAnswer).where(QuestionAnswer.id == message_id)
    )).scalar_one_or_none()
    if row is None or row.role != "assistant":
        raise ValueError(f"消息 {message_id} 不存在或非 assistant")

    # 幂等：已有归因不覆盖（提前返回，不跑重放检索省 LLM/ES 成本）
    existing = (row.extra or {}).get("attribution")
    if existing:
        return existing

    # 空间锚点：消息行不回填 space_id（O2 教训），从会话 RAG 配置兜底
    rag_cfg = await _load_session_rag_config(db, row.session_id)
    space_id = row.space_id or rag_cfg.get("space_id")
    if space_id is None:
        raise ValueError(f"消息 {message_id} 无 space_id 且会话无 RAG 绑定，无法归因")
    kb_ids = rag_cfg.get("kb_ids") or []
    search_mode = rag_cfg.get("search_mode") or "content_hybrid"
    top_k = int(rag_cfg.get("top_k") or 5)

    app_cfg = _load_config()
    low_threshold = app_cfg["low_score_threshold"]
    replay_low_threshold = app_cfg["replay_low_threshold"]

    # 取原始 user 查询（相邻前一条 user 消息）
    query = await _get_user_query_for_answer(db, row.session_id, message_id)
    if not query:
        raise ValueError(f"消息 {message_id} 找不到相邻 user 查询")

    # ---- 重放：原始阈值（复现用户视角）----
    sources_orig = await _replay_search(
        db, space_id=space_id, kb_ids=kb_ids, user_id=row.user_id,
        query=query, search_mode=search_mode, top_k=top_k,
        score_threshold=low_threshold,
    )

    # ---- 重放：降阈值（判别 content_gap vs retrieval_failure）----
    sources_low: list[dict] = []
    if not sources_orig:
        sources_low = await _replay_search(
            db, space_id=space_id, kb_ids=kb_ids, user_id=row.user_id,
            query=query, search_mode=search_mode, top_k=top_k * 2,
            score_threshold=replay_low_threshold,
        )

    # ---- 权限边界探测：用户视角零命中时，以「无文档级限制」语义重放 ----
    # _replay_search 走 SearchService（检索层权限过滤生效——用户视角结果已被
    # hidden_doc_ids 剔除）；此路传 bypass_document_permission=True 跳过过滤，
    # 命中即说明「内容存在但该用户无权」→ permission_boundary（不进 gap 统计，
    # 是安全策略非运营问题——归因四分法的第四类）。
    sources_priv: list[dict] = []
    if not sources_orig and not sources_low:
        sources_priv = await _replay_search(
            db, space_id=space_id, kb_ids=kb_ids, user_id=row.user_id,
            query=query, search_mode=search_mode, top_k=top_k,
            score_threshold=low_threshold,
            bypass_document_permission=True,
        )

    # ---- 四分判定 ----
    if sources_orig and _dead_doc_ratio(sources_orig) >= DEAD_DOC_RATIO:
        attribution = ATTR_QUALITY_DECAY
    elif sources_orig:
        # 命中且文档健康——但该消息已是零命中/低分/点踩候选。A1 无生成质量信号，
        # 保守落 retrieval_failure（检索侧改进空间），不臆断生成问题。
        attribution = ATTR_RETRIEVAL_FAILURE
    elif sources_low:
        # 原始阈值零命中、降阈值命中：相关内容存在但分数不达阈值（切分/ embedding 覆盖不足）
        attribution = ATTR_RETRIEVAL_FAILURE
    elif sources_priv:
        # 用户视角（含降阈值）零命中、无权限限制重放命中：内容存在但该用户无权
        attribution = ATTR_PERMISSION_BOUNDARY
    else:
        attribution = ATTR_CONTENT_GAP

    await _write_back_attribution(db, message_id, attribution, sources_orig, sources_low)
    return attribution


# ========== 内部辅助 ==========


async def _load_session_rag_config(db, session_id: str) -> dict[str, Any]:
    """读会话 RAG 配置（kb_ids/search_mode/top_k），配置缺失回退空 dict。

    R2 防环：qa → knowledge_ops 单向，worker 读 qa.models 直查不 import qa services。
    """
    from sqlalchemy import select

    from novamind.features.qa.models.session_config import SessionConfig

    row = (await db.execute(
        select(SessionConfig).where(SessionConfig.session_id == session_id)
    )).scalar_one_or_none()
    if row is None:
        return {}
    bindings = row.get_kb_bindings() or {}
    return {
        "space_id": bindings.get("space_id"),
        "kb_ids": bindings.get("kb_ids") or [],
        "search_mode": bindings.get("search_mode") or "content_hybrid",
        "top_k": bindings.get("top_k") or 5,
    }


async def _get_user_query_for_answer(db, session_id: str, message_id: int) -> str | None:
    """取 assistant 消息前最近一条 user 消息文本（与看板「零命中问题」取法一致）。"""
    from sqlalchemy import and_, select

    from novamind.features.qa.models.question_answer import QuestionAnswer

    row = (await db.execute(
        select(QuestionAnswer.content)
        .where(and_(
            QuestionAnswer.session_id == session_id,
            QuestionAnswer.role == "user",
            QuestionAnswer.id < message_id,
        ))
        .order_by(QuestionAnswer.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    return row


async def _replay_search(
    db,
    *,
    space_id: int,
    kb_ids: list[int],
    user_id: int,
    query: str,
    search_mode: str,
    top_k: int,
    score_threshold: float,
    bypass_document_permission: bool = False,
) -> list[dict[str, Any]]:
    """重放检索：装配 SearchService（与请求链路同构）执行知识库检索。

    KB 列表为空时回退空间前 3 个 KB（与主链路 _retrieve_knowledge 一致）。
    检索服务不可用/异常抛给上层（宁缺归因不乱归因）。
    bypass_document_permission：跳过文档级权限过滤（permission_boundary
    探测重放用——「无权限限制视角」命中而用户视角零命中 = 权限边界）。

    Returns:
        合并去重排序后的来源列表（含 document_id/lifecycle 元数据）。
    """
    from novamind.features.knowledge_space.api.dependencies import (
        get_elasticsearch_client,
    )
    from novamind.features.knowledge_space.repository.knowledge_base_repository import (
        KnowledgeBaseRepository,
    )
    from novamind.features.knowledge_space.schemas.search_schema import (
        SearchRequest,
        WeightConfig,
    )
    from novamind.features.knowledge_space.services.search_service import SearchService
    from novamind.features.user.services.model_config_service import ModelConfigService

    kb_repo = KnowledgeBaseRepository(db)
    if not kb_ids:
        kbs = await kb_repo.get_by_space(space_id)
        kb_ids = [kb.id for kb in kbs[:3]]
    if not kb_ids:
        return []

    search_request = SearchRequest(
        query=query,
        search_mode=search_mode,
        top_k=top_k,
        score_threshold=score_threshold,
        weights=WeightConfig(vector_weight=0.7, bm25_weight=0.3),
    )

    es_client = await get_elasticsearch_client()
    search_service = SearchService(
        session=db,
        es_client=es_client,
        model_config_service=ModelConfigService(db),
    )

    all_results: list[dict[str, Any]] = []
    failed_kbs = 0
    for kb_id in kb_ids:
        try:
            r = await search_service.search(
                space_id=space_id, kb_id=kb_id, user_id=user_id, request=search_request,
                bypass_document_permission=bypass_document_permission,
            )
            all_results.extend(r.get("results", []))
        except Exception as e:
            failed_kbs += 1
            logger.warning("重放检索单 KB 失败（跳过）", kb_id=kb_id, error=str(e))

    # 全部 KB 失败 = 检索基建故障（ES 不可达/embedding 未配置），不是「无相关内容」。
    # 宁缺勿错：抛错让 attribution 留空下轮重试，绝不把基建故障归因为 content_gap
    # （真实验证曾因 encryption_key 缺失把检索失败误归因为 content_gap）。
    if failed_kbs and failed_kbs == len(kb_ids):
        raise RuntimeError(
            f"重放检索全部 KB 失败（{failed_kbs}/{len(kb_ids)}），疑似检索基建故障，归因留空重试"
        )

    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return all_results[:top_k]


def _dead_doc_ratio(sources: list[dict[str, Any]]) -> float:
    """命中来源中失效文档占比（lifecycle 元数据缺失视为健康——B1 之前恒 0）。"""
    if not sources:
        return 0.0
    dead = sum(
        1 for s in sources
        if (s.get("lifecycle_status") or "active") in ("superseded", "archived")
    )
    return dead / len(sources)


async def _write_back_attribution(
    db,
    message_id: int,
    attribution: str,
    sources_orig: list[dict[str, Any]],
    sources_low: list[dict[str, Any]],
) -> None:
    """把归因结果写回 assistant 消息 extra.attribution（SAVEPOINT 保护，幂等不覆盖）。"""
    from sqlalchemy import select

    from novamind.features.qa.models.question_answer import QuestionAnswer

    row = (await db.execute(
        select(QuestionAnswer).where(QuestionAnswer.id == message_id)
    )).scalar_one_or_none()
    if row is None:
        return
    extra = dict(row.extra or {})
    if extra.get("attribution"):
        return  # 并发窗口兜底：读到已有归因则放弃
    extra["attribution"] = attribution
    extra["attribution_meta"] = {
        "replay_orig_count": len(sources_orig),
        "replay_low_count": len(sources_low),
        "dead_doc_ratio": round(_dead_doc_ratio(sources_orig), 4),
        "attributed_at": datetime.now().isoformat(timespec="seconds"),
    }
    async with db.begin_nested():
        row.extra = extra
        await db.flush()
