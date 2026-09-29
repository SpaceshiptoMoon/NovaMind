"""LoopDetector 单测（E3 loop_detection）。"""
import pytest
from novamind.engines.agent.loop_detection import LoopDetectionConfig, LoopDetector

pytestmark = pytest.mark.unit


def test_no_warning_under_threshold():
    d = LoopDetector(LoopDetectionConfig(warn_threshold=3, hard_limit=5))
    w, hs = None, False
    for _ in range(2):
        w, hs = d.track("web_search", {"query": "x"})
    assert w is None and not hs


def test_warn_at_threshold():
    d = LoopDetector(LoopDetectionConfig(warn_threshold=3, hard_limit=5))
    w, hs = None, False
    for _ in range(3):
        w, hs = d.track("web_search", {"query": "x"})
    assert w is not None and "LOOP DETECTED" in w
    assert not hs


def test_hard_stop_at_limit():
    d = LoopDetector(LoopDetectionConfig(warn_threshold=3, hard_limit=5))
    w, hs = None, False
    for _ in range(5):
        w, hs = d.track("web_search", {"query": "x"})
    assert hs is True
    assert "FORCED STOP" in (w or "")


def test_different_sig_args_no_loop():
    d = LoopDetector(LoopDetectionConfig(warn_threshold=3, hard_limit=5))
    for q in ("a", "b", "c", "d"):
        w, hs = d.track("web_search", {"query": q})
    assert w is None and not hs  # 不同 query 不算循环


def test_nonsig_args_ignored():
    """非显著参数（max_results）不同，query 相同仍算循环。"""
    d = LoopDetector(LoopDetectionConfig(warn_threshold=3, hard_limit=5))
    d.track("web_search", {"query": "x", "max_results": 5})
    d.track("web_search", {"query": "x", "max_results": 10})
    w, hs = d.track("web_search", {"query": "x", "max_results": 15})
    assert w is not None  # query 相同 → 循环


def test_warning_not_repeated():
    """同 hash warn 只触发一次（_warned 去重）。"""
    d = LoopDetector(LoopDetectionConfig(warn_threshold=3, hard_limit=5))
    d.track("t", {"q": "x"})
    d.track("t", {"q": "x"})
    w1, _ = d.track("t", {"q": "x"})  # 第 3 次 warn
    w2, _ = d.track("t", {"q": "x"})  # 第 4 次不再 warn
    assert w1 is not None
    assert w2 is None


def test_no_sig_field_tools_distinguished_by_full_args():
    """无显著字段工具按全参数区分：plan_output 查不同 step 不是循环（回归：曾因空 sig
    全部归一桶，把「回查不同步骤」误判为重复调用并注入纠偏警告）。"""
    d = LoopDetector(LoopDetectionConfig(warn_threshold=3, hard_limit=5))
    d.track("plan_output", {"step": 1})
    d.track("plan_output", {"step": 2})
    w, hs = d.track("plan_output", {"step": 3})
    assert w is None and not hs  # 三个不同 step → 不算循环


def test_no_sig_field_tools_same_args_still_loop():
    """无显著字段工具相同参数重复仍是循环（相邻正常场景不误伤兜底语义）。"""
    d = LoopDetector(LoopDetectionConfig(warn_threshold=3, hard_limit=5))
    d.track("plan_output", {"step": 1})
    d.track("plan_output", {"step": 1})
    w, _ = d.track("plan_output", {"step": 1})
    assert w is not None  # 同一 step 重复 3 次 → 循环