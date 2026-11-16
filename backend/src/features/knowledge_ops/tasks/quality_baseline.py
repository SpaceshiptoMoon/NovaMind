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


async def _digest_regression(db, service, space_id: int, kb_id: int, same_fingerprint: list) -> None:
    """消化上一轮跑批的回归对比（批次 E3：judge_regression 从零调用接线）。

    latest（最近完成）vs prev（更早一个）跑 judge_regression，关键指标降幅
    超阈时：通知空间管理员 + 落 baseline_regression 动作。同一 latest 任务
    只消化一次（ops_actions 存在性判幂等）。失败仅告警，不影响跑批主流程。
    """
    from novamind.features.knowledge_ops.repository.ops_action_repository import (
        OpsActionRepository,
    )

    latest, prev = same_fingerprint[0], same_fingerprint[1]
    try:
        repo = OpsActionRepository(db)
        if await repo.exists_by_action_target("baseline_regression", "evaluation_task", latest.id):
            return  # 已消化
        latest_report = await service.get_report(latest.id)
        prev_report = await service.get_report(prev.id)
        regressions = judge_regression(
            (prev_report or {}).get("summary") or {},
            (latest_report or {}).get("summary") or {},
        )
        if not regressions:
            return
        detail = "；".join(
            f"{r['key']} {r['baseline']}→{r['current']}（{r['delta']:.0%}）" for r in regressions
        )
        from novamind.features.knowledge_ops.services.ops_action_service import OpsActionService

        await OpsActionService().record(
            action="baseline_regression",
            target_kind="evaluation_task",
            target_id=latest.id,
            actor_id=space_id,  # cron 系统行为，与发起跑批同口径
            space_id=space_id,
            kb_id=kb_id,
            context_snapshot={"regressions": regressions, "baseline_task_id": prev.id},
        )
        await _notify_regression(db, space_id, kb_id, latest.id, detail)
        logger.warning(
            "质量基线回归告警", space_id=space_id, kb_id=kb_id, task_id=latest.id, regressions=regressions
        )
    except Exception as e:
        logger.warning("回归消化失败（跳过）", kb_id=kb_id, task_id=latest.id, error=str(e))


async def _notify_regression(db, space_id: int, kb_id: int, task_id: int, detail: str) -> None:
    """回归告警通知空间管理员（失败仅告警）。"""
    try:
        from novamind.features.knowledge_space.models.space_member import SpaceMember
        from novamind.features.notification.models.notification import NotificationType
        from novamind.features.notification.services.notification_service import (
            NotificationService,
        )
        from sqlalchemy import select

        admins = (
            await db.execute(
                select(SpaceMember.user_id).where(
                    SpaceMember.space_id == space_id, SpaceMember.role >= 2
                )
            )
        ).scalars().all()
        notifier = NotificationService(db)
        for user_id in admins or []:
            try:
                await notifier.send_notification(
                    user_id=user_id,
                    type=NotificationType.KB_BASELINE_REGRESSION.value,
                    title=f"知识库质量基线回归（跑批 #{task_id}）",
                    content=f"关键指标降幅超阈值：{detail}。请在效果评估页查看归因明细并处置。",
                    link=f"/home/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation",
                )
            except Exception as e:
                logger.warning("回归通知单管理员失败（跳过）", user_id=user_id, error=str(e))
    except Exception as e:
        logger.warning("回归通知发送失败（跳过）", space_id=space_id, error=str(e))


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
    from sqlalchemy import select

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
                same_fingerprint = [
                    t for t in completed if compute_config_fingerprint(t.config) == fingerprint
                ]

                # 回归消化（批次 E3 接线）：上一轮跑批 vs 更早基线的对比——
                # judge_regression 判回归则通知空间管理员 + 落动作（幂等：
                # 同一 latest 任务只消化一次）
                if len(same_fingerprint) >= 2:
                    await _digest_regression(db, service, row.space_id, row.kb_id, same_fingerprint)

                baseline = same_fingerprint[0] if same_fingerprint else None
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
