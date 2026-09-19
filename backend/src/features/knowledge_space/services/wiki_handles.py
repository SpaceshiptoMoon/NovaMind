"""Wiki 管道句柄表

移植自 WeKnora 的 modelcontext.HandleTable（wiki_slug_handles.go / wiki_ingest_cite.go）：
LLM 常常在复述高熵 ID 时打错一个字符（尤其 UUID 型 summary slug 与 chunk UUID），
句柄机制把「让模型复述 ID」改成「让模型抄短句柄」，从源头消除这类错误。

- chunk 句柄（c000/c001/…）：引文标注批次内每个 chunk 一个句柄，模型返回句柄，
  代码还原为真实 chunk_id；未知句柄直接丢弃。
- slug 句柄（ref-1/ref-2/…）：Reduce 阶段的 valid_links 清单以 ref-N = real slug
  形式喂给模型，模型写 [[ref-3|显示名]]，生成后 decode 还原；无映射句柄落入
  常规死链清理。

句柄表是纯内存 dict，生命周期 = 单次 ingest 任务，无需持久化。
"""
import re
from typing import Dict, Optional


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
        self._by_handle: Dict[str, str] = {}
        self._by_real: Dict[str, str] = {}

    def register(self, real_id: str) -> str:
        """注册真实 ID，返回（已存在则复用）其句柄"""
        existing = self._by_real.get(real_id)
        if existing is not None:
            return existing
        handle = f"{self._prefix}{str(len(self._by_handle) + self._start).zfill(self._width)}"
        self._by_handle[handle] = real_id
        self._by_real[real_id] = handle
        return handle

    def resolve(self, handle: str) -> Optional[str]:
        """句柄 → 真实 ID；未知句柄返回 None"""
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
