"""批 H 收尾回归：finish_step 即时落库 + dimension 变更纳入 embedding 门禁。

finish_step 搭车落库（审计 P2）：begin_step 立即 commit 而 finish_step 依赖
下一个节点搭车——崩溃间隙里已完成节点在 DB 仍是 running，孤儿恢复后
mark_last_running_step_failed 把实际完成的步骤标 failed，前端节点日志失真。
finish_step_committed 与 begin_step 对偶，run_post_parse_tail 四个节点全部接线。

dimension 变更（审计 P2#13）：_is_embedding_changed 原只比对 model——仅改
dimension 时门禁放行，ES 索引维持旧维度 mapping，新向量 bulk 全部失败。
"""
import ast
from pathlib import Path

import pytest

from novamind.features.knowledge_space.services.space_service import SpaceService

SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
STEPS_MODULE = SRC_ROOT / "features" / "knowledge_space" / "services" / "pipeline_steps.py"


# ========== finish_step_committed 接线 ==========


def test_finish_step_committed_exists_and_commits():
    """finish_step_committed 存在、是协程、内部 commit。"""
    from novamind.features.knowledge_space.services.pipeline_steps import (
        finish_step_committed,
    )
    import asyncio as _asyncio
    import inspect

    assert _asyncio.iscoroutinefunction(finish_step_committed)
    src = inspect.getsource(finish_step_committed)
    assert "await session.commit()" in src


def test_tail_steps_all_use_committed_finish():
    """run_post_parse_tail 四个节点（split/embedded/question_generation/indexed）
    的 finish 全部走 committed 版，不留搭车落库。"""
    src = STEPS_MODULE.read_text(encoding="utf-8")
    fn_pos = src.find("async def run_post_parse_tail")
    fn_end = src.find("\nasync def ", fn_pos + 10)
    body = src[fn_pos:fn_end]
    for step in ("split", "embedded", "question_generation", "indexed"):
        assert f'finish_step_committed(session, task, "{step}"' in body, (
            f"节点 {step} 未接 finish_step_committed"
        )


def test_media_steps_use_committed_finish():
    """媒体分支步骤完成节点也走 committed 版。"""
    src = (SRC_ROOT / "features" / "knowledge_space" / "services" / "media_processing.py").read_text(
        encoding="utf-8"
    )
    assert "task.finish_step(" not in src, "媒体分支残留搭车落库的 finish_step"
    assert src.count("finish_step_committed(") >= 5


# ========== dimension 变更纳入 embedding 门禁 ==========


def _check(update: dict, current: dict) -> bool:
    """_is_embedding_changed 是实例方法——经 object.__new__ 构造免 DB 依赖。"""
    svc = object.__new__(SpaceService)
    return svc._is_embedding_changed(update, current)


def test_dimension_only_change_is_detected():
    """仅改 dimension 也算 embedding 变更（门禁拦截）。"""
    assert _check(
        {"embedding": {"dimension": 768}},
        {"embedding": {"model": "text-embedding-v3", "dimension": 1024}},
    ) is True


def test_model_change_still_detected():
    """model 变更仍被检测（回归保护）。"""
    assert _check(
        {"embedding": {"model": "other-model"}},
        {"embedding": {"model": "text-embedding-v3", "dimension": 1024}},
    ) is True


def test_same_embedding_not_detected():
    """相同 model+dimension 不算变更。"""
    assert _check(
        {"embedding": {"model": "text-embedding-v3", "dimension": 1024}},
        {"embedding": {"model": "text-embedding-v3", "dimension": 1024}},
    ) is False


def test_missing_embedding_key_not_detected():
    """更新不含 embedding 键时不算变更。"""
    assert _check(
        {"name": "新名字"},
        {"embedding": {"model": "text-embedding-v3", "dimension": 1024}},
    ) is False
