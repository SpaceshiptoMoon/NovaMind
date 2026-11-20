"""双队列分槽回归测试（红队 B12：解析与轻任务混载饿尾）。

历史缺陷：文档解析（长视频可占槽至 job_timeout=7200s）、wiki/叙事/cron
全在 arq:queue 单队列 max_jobs=3 共槽——3 个长视频可让轻任务与定时任务
饿尾 2 小时。修复：解析组沿用 arq:queue（存量 pending job 无迁移），
轻任务组入 arq:light（light_max_jobs 独立配额）。
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit

_STARTUP_MANAGER = BACKEND_ROOT / "src" / "core" / "middleware" / "startup_manager.py"
_WIKI_TASKS = BACKEND_ROOT / "src" / "features" / "knowledge_space" / "tasks" / "wiki_tasks.py"
_NARRATIVE_TASK = BACKEND_ROOT / "src" / "features" / "knowledge_space" / "tasks" / "video_narrative_task.py"


def test_task_queue_config_has_light_slot():
    from novamind.setting.yaml_config.config import TaskQueueConfig

    cfg = TaskQueueConfig()
    assert cfg.light_queue_name == "arq:light"
    assert cfg.light_max_jobs >= 1
    assert cfg.queue_name == "arq:queue", "解析主队列不得改名（存量 pending job 兼容）"


def test_startup_registers_two_worker_groups():
    """startup 必须启动两组 worker：解析组（原队列）+ 轻任务组（light 队列+全部 cron）。"""
    source = _STARTUP_MANAGER.read_text(encoding="utf-8")
    assert "light_queue_name" in source, "startup 未引用 light 队列配置（分槽未落地）"
    assert source.count("start_embedded_worker(") >= 2, "必须启动两组嵌入式 worker"
    # 按调用点切片：第 1 段=解析组调用体，第 2 段=轻任务组调用体
    call_segments = source.split("await start_embedded_worker")
    assert len(call_segments) >= 3, "start_embedded_worker 调用不足两组"
    parse_call = call_segments[1]
    light_call = call_segments[2]
    assert "process_document_task" in parse_call, "解析组必须挂 process_document_task"
    assert "process_wiki_ingest_task" not in parse_call, "wiki 任务不得回解析队列"
    assert "task_queue=light_queue" in light_call, "轻任务组必须消费 light 队列"
    # cron 全部落在轻任务组（light worker 的 cron_jobs 参数段内）
    for cron_name in (
        "cleanup_stale_parts", "attribute_pending_events", "send_weekly_kb_ops_digest",
        "send_review_reminders", "run_quality_baseline",
    ):
        assert cron_name in light_call, f"cron {cron_name} 必须注册在轻任务 worker"


def test_light_enqueue_calls_carry_queue_name():
    """轻任务入队点必须显式 _queue_name=get_light_queue_name()（否则落解析队列）。"""
    wiki_source = _WIKI_TASKS.read_text(encoding="utf-8")
    assert wiki_source.count("_queue_name=get_light_queue_name()") == 3, (
        "wiki 三处入队（锁忙碌重入队/主入队/retract）都必须显式指定 light 队列"
    )
    narrative_source = _NARRATIVE_TASK.read_text(encoding="utf-8")
    assert "_queue_name=get_light_queue_name()" in narrative_source


def test_get_light_queue_name_reads_config():
    """get_light_queue_name 必须与 TaskQueueConfig 默认值同源（worker/enqueue 两侧一致）。"""
    from novamind.setting.yaml_config import get_config
    from novamind.shared.mq import get_light_queue_name

    assert get_light_queue_name() == get_config().task_queue.light_queue_name
