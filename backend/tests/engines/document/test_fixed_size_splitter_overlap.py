"""FixedSizeSplitter 重叠死循环回归测试（评审补跑欠账发现，2026-09-27）。

历史实现里，chunk_overlap > 0 时末块起点钳在 ``len(text) - overlap``，
永远小于 ``len(text)``——while 循环永不终止，同一 100 字符尾块被 append
数万次直至 MemoryError（test_tagged_rechunk 端到端用例 chunk_overlap=100
触发）。生产默认 overlap=0 掩盖了它；用户配置任何 overlap>0 的 fixed 切分
都会打爆内存。

纯字符切分逻辑测试，不加载模型。正反用例：
- 正例：overlap>0 正常终止，块覆盖原文、末块为剩余尾部；
- 反例：文本长度恰好整除步长（历史临界）与 overlap>=chunk_size（退化配置）
  都不挂死。
"""
import pytest

from novamind.engines.document.splitters.fixed_size_splitter import FixedSizeSplitter

pytestmark = pytest.mark.unit


class TestOverlapTermination:
    def test_overlap_tail_terminates_and_covers(self):
        """正例：overlap=100、len=2323（原 MemoryError 触发尺寸）正常终止。"""
        splitter = FixedSizeSplitter(chunk_size=600, chunk_overlap=100)
        text = "x" * 2323
        chunks = splitter._split_text_fixed_size(text)
        assert 2 <= len(chunks) <= 10
        # 覆盖无损：首块从 0 起、末块含最后一个字符
        assert text.startswith(chunks[0])
        assert text.endswith(chunks[-1])
        # 每块不超上限
        assert all(len(c) <= 600 for c in chunks)

    def test_exact_multiple_of_step_terminates(self):
        """反例（历史临界）：len 恰为步长整数倍时恰好 2 块、含 overlap、不挂死。"""
        splitter = FixedSizeSplitter(chunk_size=600, chunk_overlap=100)
        text = "x" * 1000  # 步长 500 → 2 块：[0,600) 与 [500,1000)
        chunks = splitter._split_text_fixed_size(text)
        assert len(chunks) == 2
        assert chunks[0] == "x" * 600
        assert chunks[1] == "x" * 500  # 含 100 字符 overlap
        assert chunks[-1].endswith(text[-1])

    def test_degenerate_overlap_does_not_hang(self):
        """反例：overlap >= chunk_size 的非法配置降级为零重叠，不挂死。"""
        splitter = FixedSizeSplitter(chunk_size=100, chunk_overlap=100)
        chunks = splitter._split_text_fixed_size("x" * 350)
        assert sum(len(c) for c in chunks) >= 350
        assert all(len(c) <= 100 for c in chunks)
        # 不改写调用方可见的实例配置（就地改写会让后续读取发现配置漂移）
        assert splitter.chunk_overlap == 100

    def test_invalid_chunk_size_does_not_hang(self):
        """反例：chunk_size <= 0 的非法配置整篇单块返回，不挂死不丢内容。"""
        for size in (0, -100):
            splitter = FixedSizeSplitter(chunk_size=size, chunk_overlap=0)
            assert splitter._split_text_fixed_size("abc") == ["abc"]
            assert splitter._split_text_fixed_size("") == []

    @pytest.mark.parametrize("size", [0, 1, 599, 600, 601, 1200])
    def test_zero_overlap_lossless(self, size):
        """回归锚：overlap=0 各长度切分必须无损还原。"""
        splitter = FixedSizeSplitter(chunk_size=600, chunk_overlap=0)
        chunks = splitter._split_text_fixed_size("x" * size)
        assert "".join(chunks) == "x" * size
