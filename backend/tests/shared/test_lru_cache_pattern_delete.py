"""LRUCache.delete_pattern 回归测试（批量失效 L1 缺口修复，对齐 deer-flow 对照批次 2）。"""
import pytest
from novamind.shared.cache.lru_cache import LRUCache

pytestmark = pytest.mark.unit


def test_delete_pattern_removes_matching_keys_only():
    c = LRUCache(max_size=100, default_ttl=60)
    c.set("user:1", {"a": 1})
    c.set("user:2", {"b": 2})
    c.set("space:1", {"c": 3})
    c.set("user", {"d": 4})  # 不带冒号的精确键，不应被 user:* 命中

    removed = c.delete_pattern("user:*")

    assert removed == 2
    assert c.get("user:1") is None
    assert c.get("user:2") is None
    assert c.get("space:1") == {"c": 3}
    assert c.get("user") == {"d": 4}


def test_delete_pattern_question_mark_wildcard():
    c = LRUCache(max_size=100, default_ttl=60)
    c.set("kb:1:doc", 1)
    c.set("kb:2:doc", 2)
    c.set("kb:11:doc", 3)

    assert c.delete_pattern("kb:?:doc") == 2  # kb:1 与 kb:2，不含 kb:11
    assert c.get("kb:11:doc") == 3


def test_delete_pattern_no_match_returns_zero():
    c = LRUCache(max_size=10, default_ttl=60)
    assert c.delete_pattern("nothing:*") == 0


def test_delete_pattern_thread_safe_iterate():
    """在锁内遍历删除，不抛 RuntimeError（遍历时修改 OrderedDict）"""
    c = LRUCache(max_size=100, default_ttl=60)
    for i in range(50):
        c.set(f"item:{i}", i)
    assert c.delete_pattern("item:*") == 50
    assert c.get("item:49") is None