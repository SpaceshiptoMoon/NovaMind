"""Wiki 管道句柄表：把「让 LLM 复述高熵 ID」改为「让 LLM 抄短句柄」（chunk 句柄 c000…、slug 句柄 ref-N…），从源头消除复述错字。未知句柄直接丢弃（chun
k 引用）或落入常规死链清理（slug 链接）；句柄表纯内存 dict，生命周期等于单次 ingest 任务，不持久化。
"""
import re


class HandleTable:
    """短句柄 ↔ 真实 ID 的双向映射（单任务生命周期）"""

    def __init__(self, prefix: str, start: int = 0, width: int = 3):
        """
        Args:
            prefix: 句柄前缀（如 "ref-" 或 "c"）
            start: 编号起始值
            width: 编号零填充宽度（c000 为 3 位，ref-1 为 1 位）
        """
        self._prefix = prefix
        self._start = start
        self._width = width
        self._by_handle: dict[str, str] = {}
        self._by_real: dict[str, str] = {}

    def register(self, real_id: str) -> str:
        """注册真实 ID，返回（已存在则复用）其句柄。

        Args:
            real_id: 真实 ID（chunk_id 或 slug）。

        Returns:
            按前缀+零填充序号生成的短句柄；重复注册返回既有句柄。
        """
        existing = self._by_real.get(real_id)
        if existing is not None:
            return existing
        handle = f"{self._prefix}{str(len(self._by_handle) + self._start).zfill(self._width)}"
        self._by_handle[handle] = real_id
        self._by_real[real_id] = handle
        return handle

    def resolve(self, handle: str) -> str | None:
        """句柄 → 真实 ID；未知句柄返回 None。

        Args:
            handle: 模型输出的句柄（自动去首尾空白）。

        Returns:
            对应的真实 ID；未注册返回 None。
        """
        return self._by_handle.get(str(handle or "").strip())

    def decode_text(self, text: str, pattern: str) -> str:
        """按给定正则（含一个捕获组=句柄）把文本中的句柄替换回真实 ID。

        未映射句柄原样保留——调用方的后续白名单校验（如 _extract_wiki_links）
        会把无效链接当作死链处理。
        """
        if not text:
            return text

        def _sub(m: "re.Match") -> str:
            real = self.resolve(m.group(1))
            if real is None:
                return m.group(0)
            return m.group(0).replace(m.group(1), real)

        return re.sub(pattern, _sub, text)
