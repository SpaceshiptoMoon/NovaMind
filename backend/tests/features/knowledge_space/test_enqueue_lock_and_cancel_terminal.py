"""入队防重锁读 + 取消终态统一（2026-09 链路审计 P1#1 / P1#6 回归）。

P1#1：文档行锁（FOR UPDATE，最新提交）与任务行普通读（RR 旧快照）混用会让
「锁后复查」失效——双击重试可双跑，或误清活 job 后任务永久 PENDING。
门禁：三个入队口（单文档 enqueue / 批量 / retry 校验）的活跃任务复查必须是
``lock_active_by_document_id(s)``（FOR UPDATE），不得回退普通读。

P1#6：worker 侧取消补偿 _handle_cancellation 必须写 CANCELLED（经
_ensure_mark_terminal），不得再走 _ensure_mark_failed 写 FAILED——
双 writer last-write-wins 曾让终态在 CANCELLED/FAILED 间随机。
"""
import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[3] / "src"

ENQUEUE_MODULE = SRC_ROOT / "features" / "knowledge_space" / "tasks" / "document_tasks.py"
SERVICE_MODULE = SRC_ROOT / "features" / "knowledge_space" / "services" / "document_task_service.py"
REPO_MODULE = (
    SRC_ROOT / "features" / "knowledge_space" / "repository" / "document_task_repository.py"
)


# ========== P1#1 入队防重锁读门禁 ==========


def test_enqueue_process_document_uses_locked_active_check():
    """单文档入队：锁文档行后的活跃任务复查必须是 lock_active_by_document_id。"""
    src = ENQUEUE_MODULE.read_text(encoding="utf-8")
    assert "lock_active_by_document_id" in src, (
        "enqueue_process_document 的活跃任务复查未用 FOR UPDATE 锁读，防重会失效"
    )
    # 锁序：必须先锁文档行再锁任务行
    doc_lock_pos = src.find("lock_active_document_by_id")
    task_lock_pos = src.find("lock_active_by_document_id")
    assert 0 < doc_lock_pos < task_lock_pos, "锁序错误：应先 document 行锁再 task 行锁"


def test_batch_process_uses_locked_active_check():
    """批量入口：活跃任务复查必须是 lock_active_by_document_ids。"""
    src = SERVICE_MODULE.read_text(encoding="utf-8")
    assert "lock_active_by_document_ids(" in src, (
        "批量入口的活跃任务复查未用 FOR UPDATE 批量锁读"
    )


def test_retry_validation_uses_locked_active_check():
    """retry 校验（_validate_document_not_processing）：必须用锁读。"""
    src = SERVICE_MODULE.read_text(encoding="utf-8")
    # _validate_document_not_processing 函数体内
    fn_pos = src.find("async def _validate_document_not_processing")
    assert fn_pos > 0
    fn_end = src.find("\n    async def ", fn_pos + 10)
    body = src[fn_pos:fn_end]
    assert "lock_active_by_document_id(" in body, (
        "retry 活跃校验未用 FOR UPDATE 锁读"
    )


def test_zombie_recheck_uses_locked_active_check():
    """僵尸 job 复核分支：DB 复查必须用锁读（误清活 job 曾致永久 PENDING）。"""
    src = SERVICE_MODULE.read_text(encoding="utf-8")
    fn_pos = src.find("async def _enqueue_document_processing")
    assert fn_pos > 0
    fn_end = src.find("\n    async def ", fn_pos + 10)
    body = src[fn_pos:fn_end]
    assert "lock_active_by_document_id(document.id)" in body, (
        "僵尸复核 DB 查询未用 FOR UPDATE 锁读，可能误清活 job"
    )


def test_locked_repo_methods_use_with_for_update():
    """仓库层锁读方法必须带 with_for_update。"""
    src = REPO_MODULE.read_text(encoding="utf-8")
    for method in ("lock_active_by_document_id", "lock_active_by_document_ids"):
        pos = src.find(f"async def {method}")
        assert pos > 0, f"仓库缺少 {method}"
        fn_end = src.find("\n    async def ", pos + 10)
        body = src[pos:fn_end]
        assert "with_for_update()" in body, f"{method} 未加 with_for_update"


# ========== P1#6 取消终态统一门禁 ==========


def test_handle_cancellation_marks_cancelled_not_failed():
    """worker 侧取消补偿必须写 CANCELLED，不得走 _ensure_mark_failed。"""
    src = ENQUEUE_MODULE.read_text(encoding="utf-8")
    fn_pos = src.find("async def _handle_cancellation")
    assert fn_pos > 0
    fn_end = src.find("\nasync def ", fn_pos + 10)
    body = src[fn_pos:fn_end]
    assert "_ensure_mark_terminal" in body and "CANCELLED" in body, (
        "_handle_cancellation 未统一写 CANCELLED 终态"
    )
    assert "_ensure_mark_failed" not in body, (
        "_handle_cancellation 仍走 FAILED 标记——与 API 侧 CANCELLED 形成"
        "双 writer 竞态，终态随机"
    )


def test_ensure_mark_terminal_supports_target_status():
    """_ensure_mark_terminal 存在且支持 target_status（FAILED 薄委托保留）。"""
    src = ENQUEUE_MODULE.read_text(encoding="utf-8")
    assert "async def _ensure_mark_terminal" in src
    assert "target_status" in src
    # FAILED 调用点仍保留 [已重试最大次数] 语义
    assert "[已重试最大次数]" in src


def test_retry_allows_cancelled_status():
    """retry_document 放行 CANCELLED（此前 CANCELLED 是不可重试死路）。"""
    src = SERVICE_MODULE.read_text(encoding="utf-8")
    fn_pos = src.find("async def retry_document")
    fn_end = src.find("\n    async def ", fn_pos + 10)
    body = src[fn_pos:fn_end]
    assert "TaskStatus.CANCELLED" in body, "retry 未放行 CANCELLED 终态"
