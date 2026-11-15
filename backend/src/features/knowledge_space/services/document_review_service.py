"""文档复审配置公共面（kb-ops B2）。

load_review_config/compute_next_review_at 供 knowledge_ops 的 review_reminder
cron 与 space_overview 消费（文档域行为归 ks，ko 反向 import 本公共面）。
人工操作入口（确认复审/设置复审策略 HTTP 端点与 DocumentReviewService）已随
2026-11-15 工作台剥离下线；存量复审字段由 cron 继续消费。
"""
from __future__ import annotations

from datetime import datetime, timedelta

# 默认参数（YAML knowledge_ops.review_* 可覆盖）
DEFAULT_ADVANCE_DAYS = 7        # 提前提醒量
DEFAULT_FALLBACK_CYCLE_DAYS = 90  # 无 review_cycle_days 的文档确认复审后的顺延周期


def load_review_config() -> dict:
    """读复审提醒参数（YAML 可配，异常回退默认值）。"""
    defaults = {
        "advance_days": DEFAULT_ADVANCE_DAYS,
        "fallback_cycle_days": DEFAULT_FALLBACK_CYCLE_DAYS,
    }
    try:
        from novamind.setting.yaml_config import get_config

        ko = get_config().knowledge_ops
        defaults["advance_days"] = int(ko.review_advance_days)
        defaults["fallback_cycle_days"] = int(ko.review_fallback_cycle_days)
    except Exception as e:
        from novamind.shared.logging import get_logger

        get_logger(__name__).warning("复审提醒配置读取失败，使用默认值", error=str(e))
    return defaults


def compute_next_review_at(
    review_cycle_days: int | None, fallback_cycle_days: int, base: datetime | None = None
) -> datetime:
    """计算下次复审时间：文档周期优先，空则回退默认周期。"""
    days = review_cycle_days or fallback_cycle_days
    return (base or datetime.now()) + timedelta(days=days)
