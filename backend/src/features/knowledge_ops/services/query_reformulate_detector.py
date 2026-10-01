"""会话内改写检测：识别用户换个问法再问一次的检索失败信号。

被动信号（零用户配合）：同会话短时间窗内两条高相似 query，前一条大概率
没答上——这是 gap 归因与看板都要用的强信号。判定保守（时间窗 + 字符
3-gram 相似度双门槛，仅 RAG 会话启用），阈值走 YAML 配置；检测失败只影响
信号标记，不影响问答（旁路语义）。

比对目标取自 question_answers 最新 user 消息（R2 允许的跨 feature models
直查；qa 不反向依赖本 feature，无环）。调用时机在当前 user 消息提交前，
独立会话读不到未提交行，最新可见 user 消息即上一条。
"""
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_ops.services.event_recorder import EventRecorder
from novamind.setting.yaml_config import get_config

logger = get_logger(__name__)

# 默认判定参数（YAML knowledge_ops 段可覆盖）
DEFAULT_WINDOW_SECONDS = 120
DEFAULT_SIMILARITY_THRESHOLD = 0.5


def normalize_query(text: str) -> str:
    """查询归一化：转小写、仅保留字母数字（中文整字保留、空白标点剔除）。

    聚类/比对统一入口（改写检测与后续 gap 聚合共用），保证同口径。
    """
    return "".join(ch for ch in text.lower() if ch.isalnum())


def char_trigram_similarity(a: str, b: str) -> float:
    """字符 3-gram Jaccard 相似度（0~1）。短于 3 字符的串退化为整体比较。

    选 Jaccard 而非编辑距离：纯集合运算无 O(mn) 动态规划，中文短句场景
    效果与成本折中；阈值语义直观（共有点比例）。
    """
    if not a or not b:
        return 0.0
    if len(a) < 3 or len(b) < 3:
        return 1.0 if a == b else 0.0
    grams_a = {a[i : i + 3] for i in range(len(a) - 2)}
    grams_b = {b[i : i + 3] for i in range(len(b) - 2)}
    intersection = len(grams_a & grams_b)
    if intersection == 0:
        return 0.0
    return intersection / len(grams_a | grams_b)


def _load_detection_config() -> tuple[int, float]:
    """读取 YAML knowledge_ops 配置，异常回落默认值（配置缺失不阻塞信号）。"""
    window = DEFAULT_WINDOW_SECONDS
    threshold = DEFAULT_SIMILARITY_THRESHOLD
    try:
        ops_cfg = getattr(get_config(), "knowledge_ops", None)
        if ops_cfg is not None:
            window = ops_cfg.reformulate_window_seconds
            threshold = ops_cfg.reformulate_similarity_threshold
    except Exception as e:
        logger.warning("改写检测配置读取失败，使用默认值", error=str(e))
    return int(window), float(threshold)


class QueryReformulateDetector:
    """会话内改写检测器：新查询入库后判定是否为上一条查询的改写。"""

    async def check_after_new_query(
        self,
        session_id: str,
        user_id: int,
        space_id: int | None,
        current_message_id: int,
        current_query: str,
    ) -> None:
        """判定当前查询是否为会话内上一条 user 查询的改写，命中则记事件。

        Args:
            session_id: 会话 ID。
            user_id: 用户 ID。
            space_id: 空间 ID（透传到事件，权限域过滤用）。
            current_message_id: 当前 user 消息 id（比对时排除自身）。
            current_query: 当前查询原文（调用方在握，无需查库）。
        """
        try:
            normalized = normalize_query(current_query)
            if not normalized:
                return  # 归一化后为空（纯标点等）：无信号价值

            window, threshold = _load_detection_config()

            previous = await self._get_previous_user_query(
                session_id, current_message_id
            )
            if previous is None:
                return

            # 时间窗：与上一条 user 消息的间隔超窗即不视为改写（回到旧会话重问
            # 不构成检索失败信号）
            from novamind.shared.utils.time_utils import now_china

            delta = (now_china() - previous.created_at).total_seconds()
            if previous.created_at is None or delta > window:
                return

            similarity = char_trigram_similarity(
                normalized, normalize_query(previous.content or "")
            )
            if similarity < threshold:
                return

            await EventRecorder().record(
                event_type="query_reformulate",
                user_id=user_id,
                session_id=session_id,
                space_id=space_id,
                query_text=current_query,
                extra={
                    "previous_message_id": previous.id,
                    "previous_query": (previous.content or "")[:256],
                    "similarity": round(similarity, 4),
                },
            )
        except Exception as e:
            # 旁路语义：检测失败不影响问答主链路
            logger.warning("改写检测失败（已忽略）", error=str(e))

    async def _get_previous_user_query(self, session_id: str, exclude_message_id: int):
        """取会话内最新一条 user 消息（排除当前消息），无则 None。

        独立短会话查询；调用时机在当前消息 commit 前，未提交行不可见，
        此处再显式按 id 排除兜底（不依赖隔离级别细节）。
        """
        from novamind.core.database.database import get_session_factory
        from novamind.features.qa.models.question_answer import QuestionAnswer
        from sqlalchemy import and_, select

        query = (
            select(QuestionAnswer)
            .where(
                and_(
                    QuestionAnswer.session_id == session_id,
                    QuestionAnswer.role == "user",
                    QuestionAnswer.id != exclude_message_id,
                )
            )
            .order_by(QuestionAnswer.id.desc())
            .limit(1)
        )
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(query)
            return result.scalar_one_or_none()
