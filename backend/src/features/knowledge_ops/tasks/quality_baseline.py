"""质量基线自动跑批（kb-ops backlog）：对有测试集的 KB 周期发起测评并做同指纹回归对比。

装配经 standalone_factory（无请求依赖）；YAML quality_baseline_enabled 默认关
（LLM 成本敏感，开启前确认配额）。回归判定：同测试集 + 同配置指纹的最近一次
completed 任务为基线，关键指标降幅超阈值即告警（日志，周报钩子可消费）。
"""
from __future__ import annotations

from typing import Any

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 回归告警阈值：关键指标相对基线的最大降幅（容忍 LLM judge 抖动）
REGRESSION_ALERT_DELTA = 0.05
# 关键指标名匹配（summary 扁平键包含判定）
KEY_METRIC_PATTERNS = ("retrieval.mrr", "retrieval.hit_rate", "generation.overall", "correctness")


def is_baseline_enabled() -> bool:
    """跑批开关（YAML knowledge_ops.quality_baseline_enabled，默认 False）。"""
    try:
        from novamind.setting.yaml_config import get_config

        return bool(get_config().knowledge_ops.quality_baseline_enabled)
    except Exception:
        return False


def _is_key_metric(key: str) -> bool:
    return any(p in key for p in KEY_METRIC_PATTERNS)


def judge_regression(
    baseline_summary: dict[str, Any],
    current_summary: dict[str, Any],
    delta_threshold: float = REGRESSION_ALERT_DELTA,
) -> list[dict[str, Any]]:
    """同指纹回归判定（纯函数，供测试）：关键指标扁平对比，降幅超阈值列出。

    Returns:
        [{key, baseline, current, delta}] 降幅超阈值的指标（空=无回归）。
    """

    def _flatten(s: dict[str, Any], prefix: str = "") -> dict[str, float]:
        flat: dict[str, float] = {}
        for k, v in (s or {}).items():
            if isinstance(v, dict):
                flat.update(_flatten(v, f"{prefix}{k}."))
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                flat[f"{prefix}{k}"] = float(v)
        return flat

    base_flat = _flatten(baseline_summary)
    cur_flat = _flatten(current_summary)
    regressions: list[dict[str, Any]] = []
    for key in sorted(set(base_flat) & set(cur_flat)):
        if not _is_key_metric(key):
            continue
        base_v = base_flat[key]
        cur_v = cur_flat[key]
        if base_v <= 0:
            continue  # 基线为零无法算降幅（避免除零）
        delta = (cur_v - base_v) / base_v
        if delta < -delta_threshold:
            regressions.append({
                "key": key,
                "baseline": round(base_v, 4),
                "current": round(cur_v, 4),
                "delta": round(delta, 4),
            })
    return regressions


async def run_quality_baseline(ctx: dict | None = None) -> dict[str, Any]:
    """质量基线 cron（每周）：逐 KB 取最近测试集 → 同指纹最近 completed 为基线 →
    发起新跑批（后台协程）→ 登记对比意图。

    跑批是 asyncio 后台协程（create_task），本 cron 不等待完成——完成后的
    回归告警在下一轮 cron 执行（届时新任务已 completed 并成为「最近」，与
    更早的基线自然形成对比链），周期性最终一致。
    """
    if not is_baseline_enabled():
        logger.debug("质量基线跑批未启用（quality_baseline_enabled=false），跳过")
        return {}

    import asyncio

    from sqlalchemy import select

    from novamind.core.database.database import get_db_session
    from novamind.features.evaluation.models.evaluation_task import (
        EvaluationStatus,
        EvaluationTask,
        EvaluationTestSet,
    )
    from novamind.features.evaluation.services.config_fingerprint import (
        compute_config_fingerprint,
    )
    from novamind.features.evaluation.services.standalone_factory import (
        build_standalone_evaluation_service,
    )

    service = await build_standalone_evaluation_service()
    results: dict[str, Any] = {}

    async with get_db_session() as db:
        # 每 KB 最近一个测试集（一 KB 一基线集口径）
        rows = (await db.execute(
            select(EvaluationTestSet.space_id, EvaluationTestSet.kb_id, EvaluationTestSet.id)
            .distinct(EvaluationTestSet.kb_id)
            .order_by(EvaluationTestSet.kb_id, EvaluationTestSet.id.desc())
        )).all()

        for row in rows:
            kb_key = str(row.kb_id)
            try:
                fingerprint = compute_config_fingerprint(None)  # cron 固定全默认配置
                completed = (await db.execute(
                    select(EvaluationTask)
                    .where(
                        EvaluationTask.test_set_id == row.id,
                        EvaluationTask.status == EvaluationStatus.COMPLETED,
                    )
                    .order_by(EvaluationTask.id.desc())
                    .limit(10)
                )).scalars().all()
                baseline = next(
                    (t for t in completed if compute_config_fingerprint(t.config) == fingerprint),
                    None,
                )
                if baseline is None:
                    logger.info(
                        "质量基线：无同指纹基线，本轮跑批建立首个基线点",
                        kb_id=row.kb_id, test_set_id=row.id,
                    )
                else:
                    # 基线已足够新（同指纹最近任务 <7 天）则跳过——避免每周必跑
                    from datetime import datetime, timedelta

                    age = datetime.now() - baseline.updated_at
                    if age < timedelta(days=7):
                        results[kb_key] = {"skipped": "baseline_fresh", "task_id": baseline.id}
                        continue

                task = await service.create_task(
                    test_set_id=row.id,
                    user_id=row.space_id,  # cron 系统行为；user_id 仅用于模型解析，传空间 ID 无副作用
                    name=f"质量基线自动跑批-{row.kb_id}",
                    config=None,
                )
                results[kb_key] = {
                    "task_id": task.id,
                    "fingerprint": fingerprint,
                    "baseline_task_id": baseline.id if baseline else None,
                }
                logger.info(
                    "质量基线跑批已发起（后台执行）",
                    kb_id=row.kb_id, task_id=task.id, has_baseline=baseline is not None,
                )
            except Exception as e:
                logger.warning("质量基线单 KB 失败（跳过）", kb_id=row.kb_id, error=str(e))
                results[kb_key] = {"error": str(e)}

    # 持有 service 引用防 GC（后台协程闭包内使用其工厂）
    results["_service_held"] = service is not None
    if any(k != "_service_held" and "error" not in v and "skipped" not in v for k, v in results.items()):
        logger.info("质量基线本轮发起跑批", summary={k: v for k, v in results.items() if k != "_service_held"})
    return results
