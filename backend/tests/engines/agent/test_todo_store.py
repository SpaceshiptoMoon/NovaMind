"""TodoStore 硬上限测试：单条内容截断、总条数截断、format_for_injection 行为回归。

背景：todo 清单会被 ContextCompressor 在压缩后经 format_for_injection 重注入，
无上限时模型写入的超长内容/超多条目会让重注入块无界膨胀，架空压缩本身。
"""
import pytest
from novamind.engines.agent.memory.todo_store import (
    MAX_TODO_CONTENT_CHARS,
    MAX_TODO_ITEMS,
    TodoStore,
)

pytestmark = pytest.mark.unit

CONV = 1


# ==================== 单条内容上限 ====================


def test_write_truncates_oversized_content_head_kept() -> None:
    """超长单条（>4000 字符）保头部截断并带标记——任务描述要点在前部"""
    store = TodoStore()
    long_text = "长" * 5000
    store.write(CONV, [{"id": "1", "content": long_text, "status": "pending"}])

    items = store.read(CONV)
    assert len(items[0]["content"]) == MAX_TODO_CONTENT_CHARS
    assert items[0]["content"].startswith("长")           # 头部保留
    assert items[0]["content"].endswith("… [truncated]")   # 截断可见


def test_write_normal_content_untouched() -> None:
    """正常长度内容不误伤（相邻正常场景回归）"""
    store = TodoStore()
    store.write(CONV, [{"id": "1", "content": "正常任务描述", "status": "pending"}])
    assert store.read(CONV)[0]["content"] == "正常任务描述"


# ==================== 总条数上限 ====================


def test_write_caps_items_priority_head_kept() -> None:
    """超 256 条保列表头部（顺序即优先级）"""
    store = TodoStore()
    todos = [
        {"id": str(i), "content": f"任务{i}", "status": "pending"}
        for i in range(MAX_TODO_ITEMS + 10)
    ]
    store.write(CONV, todos)

    items = store.read(CONV)
    assert len(items) == MAX_TODO_ITEMS
    # 头部保留 = 优先级高的前 256 条
    assert items[0]["id"] == "0"
    assert items[-1]["id"] == str(MAX_TODO_ITEMS - 1)


def test_merge_mode_also_capped() -> None:
    """merge 追加路径同样受上限约束"""
    store = TodoStore()
    first = [{"id": str(i), "content": f"t{i}", "status": "pending"} for i in range(MAX_TODO_ITEMS)]
    store.write(CONV, first, merge=False)
    store.write(CONV, [{"id": "new", "content": "追加", "status": "pending"}], merge=True)

    items = store.read(CONV)
    assert len(items) == MAX_TODO_ITEMS
    assert items[0]["id"] == "0"  # 保头部，追加项在尾部被截掉


# ==================== 注入行为回归 ====================


def test_format_for_injection_regression() -> None:
    """上限内行为不变：只注入 pending/in_progress，completed 不注入"""
    store = TodoStore()
    store.write(CONV, [
        {"id": "1", "content": "已完成项", "status": "completed"},
        {"id": "2", "content": "进行中项", "status": "in_progress"},
        {"id": "3", "content": "待办项", "status": "pending"},
    ])
    text = store.format_for_injection(CONV)
    assert text is not None
    assert "已完成项" not in text          # completed 不注入（防压缩后重做已完成工作）
    assert "[in_progress] 进行中项" in text
    assert "[pending] 待办项" in text


def test_format_for_injection_none_when_all_done() -> None:
    """全部完成时返回 None（不注入空块）"""
    store = TodoStore()
    store.write(CONV, [{"id": "1", "content": "done", "status": "completed"}])
    assert store.format_for_injection(CONV) is None
