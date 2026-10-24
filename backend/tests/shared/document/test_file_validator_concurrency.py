"""FileValidator 大小上限覆盖的并发安全回归测试。

历史缺陷：``validate_file`` 用「临时改写全局单例 ``max_file_size`` +
finally 还原」实现按次覆盖——单例被并发共享，A 调用方的覆盖窗口会把
上限泄漏给 B（100MB 窗口内放进 500MB 文件的权限放大）。修复后覆盖值经
参数传入 ``validate()``，不再触碰单例状态。

正例：覆盖值生效（按次上限正确放行/拒绝）。
反例：并发交错下互不泄漏 + 单例属性永不被污染。
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.shared.document.validation.file_validator import (
    FileValidator,
    validate_file,
)

pytestmark = pytest.mark.unit


class TestOverrideHonored:
    """正例：按次覆盖生效。"""

    def test_override_allows_larger_file(self):
        # 200 字节内容，默认 100MB 也放行；重点在覆盖为更小值时的拒/放行为
        content = b"x" * 200
        info = validate_file(content, "a.txt", max_file_size=1000)
        assert info.is_valid, info.validation_message

    def test_override_rejects_when_exceeded(self):
        content = b"x" * 200
        info = validate_file(content, "a.txt", max_file_size=100)
        assert "超过限制" in info.validation_message
        assert "100 字节" in info.validation_message

    def test_default_limit_used_when_no_override(self):
        content = b"x" * 200
        info = validate_file(content, "a.txt")
        assert info.is_valid, info.validation_message

    def test_singleton_state_never_mutated(self):
        """覆盖校验后单例上限保持初始值（历史缺陷的直接断言）。"""
        validator = FileValidator(max_file_size=100 * 1024 * 1024)
        validator.validate(b"x" * 200, "a.txt", max_file_size=10)
        assert validator.max_file_size == 100 * 1024 * 1024


class TestConcurrentIsolation:
    """反例：并发交错下覆盖值互不泄漏。

    线程 A 持 1000 字节上限（200 字节内容应放行），线程 B 持 100 字节上限
    （同样内容应拒绝）。历史缺陷下 B 可能落进 A 的 1000 字节窗口 → B 误放行
    → 本测试失败。修复后 B 恒拒。
    """

    def test_no_limit_leakage_between_threads(self):
        content = b"x" * 200
        rounds = 200

        def strict() -> bool:
            """B：100 字节上限，恒应拒。返回是否被正确拒绝。"""
            for _ in range(rounds):
                info = validate_file(content, "b.txt", max_file_size=100)
                if "超过限制" not in info.validation_message:
                    return False
            return True

        def lenient() -> bool:
            """A：1000 字节上限，恒应放行。"""
            for _ in range(rounds):
                info = validate_file(content, "a.txt", max_file_size=1000)
                if not info.is_valid:
                    return False
            return True

        with ThreadPoolExecutor(max_workers=2) as pool:
            strict_ok = pool.submit(strict)
            lenient_ok = pool.submit(lenient)
            assert strict_ok.result(), "并发下严格上限被宽松上限泄漏（竞态回归）"
            assert lenient_ok.result(), "并发下宽松上限被严格上限泄漏（竞态回归）"
