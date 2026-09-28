"""SSE 输出标签清洗器：程序化保证 memory-context/documents/think 等内部标签不泄露到前端；有状态设计处理跨 SSE chunk 的标签分割。"""
import re

# 匹配系统提示行
_SYSTEM_NOTE_PATTERN = re.compile(
    r"\[系统提示[：:].*?\]",
)

# 需要清洗的标签对：(open_tag, close_tag)
_SCRUB_TAGS = (
    ("<memory-context>", "</memory-context>"),
    ("<documents>", "</documents>"),
)

# 自关闭标签模式（如 <think ...>...</think 或 <think/>）
_THINK_OPEN = "<think"
_THINK_CLOSE = "</think"
_THINK_SELF_CLOSE = "/>"


class StreamingContextScrubber:
    """SSE 输出标签清洗器（有状态，处理跨 chunk 分割）"""

    def __init__(
        self,
        extra_tags: frozenset[str] | None = None,
    ) -> None:
        """初始化跨 chunk 缓冲与标签内状态；实例绑定单个输出流，不可跨流复用。"""
        self._buffer = ""
        self._in_tag: str | None = None  # 当前正在清洗的 open tag
        self._in_think = False

    def feed(self, chunk: str) -> str:
        """清洗单个 SSE chunk，返回去除内部标签后的内容。

        Args:
            chunk: 上游 SSE 增量文本片段。

        Returns:
            可安全输出的清洗文本；标签未闭合时为空串，剩余内容留在缓冲待后续 chunk。
        """
        if not chunk:
            return chunk

        self._buffer += chunk
        result = []

        while self._buffer:
            # ---- 在 <think 块内部 ----
            if self._in_think:
                close_idx = self._buffer.find(_THINK_CLOSE)
                if close_idx == -1:
                    self._buffer = ""
                    return ""
                self._buffer = self._buffer[close_idx + len(_THINK_CLOSE):]
                self._in_think = False
                continue

            # ---- 在其他标签块内部 ----
            if self._in_tag:
                close_tag = self._in_tag[1]  # (open, close) → close
                close_idx = self._buffer.find(close_tag)
                if close_idx == -1:
                    self._buffer = ""
                    return ""
                self._buffer = self._buffer[close_idx + len(close_tag):]
                self._in_tag = None
                continue

            # ---- 不在任何标签内，扫描下一个触发点 ----
            # 查找最近的 open tag
            best_idx = len(self._buffer)
            best_tag = None
            for open_tag, close_tag in _SCRUB_TAGS:
                idx = self._buffer.find(open_tag)
                if idx != -1 and idx < best_idx:
                    best_idx = idx
                    best_tag = (open_tag, close_tag)

            # 查找 <think
            think_idx = self._buffer.find(_THINK_OPEN)
            if think_idx != -1 and think_idx < best_idx:
                best_idx = think_idx
                best_tag = "think"

            if best_tag is None:
                # 没有找到任何开始标签，输出安全部分
                safe_end = self._buffer
                safe_end = self._retain_partial_open(safe_end)
                safe_end = _SYSTEM_NOTE_PATTERN.sub("", safe_end)
                result.append(safe_end)
                break

            # 输出开始标签之前的内容
            before = self._buffer[:best_idx]
            before = _SYSTEM_NOTE_PATTERN.sub("", before)
            result.append(before)

            if best_tag == "think":
                # <think 可能是 <think...> 或 <think/>
                remainder = self._buffer[best_idx + len(_THINK_OPEN):]
                self_close_idx = remainder.find(_THINK_SELF_CLOSE)
                close_tag_idx = remainder.find(">")
                if self_close_idx != -1 and (close_tag_idx == -1 or self_close_idx < close_tag_idx):
                    # 自关闭 <think ... />
                    self._buffer = remainder[self_close_idx + len(_THINK_SELF_CLOSE):]
                    self._in_think = False
                elif close_tag_idx != -1:
                    # <think ...> — 进入 think 块
                    self._buffer = remainder[close_tag_idx + 1:]
                    self._in_think = True
                else:
                    # 不完整的 <think 标签，等待更多数据
                    self._buffer = self._buffer[best_idx:]
                    break
            else:
                open_tag, close_tag = best_tag
                self._buffer = self._buffer[best_idx + len(open_tag):]
                self._in_tag = best_tag

        return "".join(result)

    def flush(self) -> str:
        """处理缓冲区中剩余的内容"""
        remaining = self._buffer
        self._buffer = ""
        self._in_tag = None
        self._in_think = False
        if remaining:
            remaining = _SYSTEM_NOTE_PATTERN.sub("", remaining)
        return remaining

    def _retain_partial_open(self, content: str) -> str:
        """检查尾部是否有部分开始标签，保留在缓冲区"""
        all_opens = [t[0] for t in _SCRUB_TAGS] + [_THINK_OPEN]
        for open_tag in all_opens:
            for prefix_len in range(1, len(open_tag)):
                if content.endswith(open_tag[:prefix_len]):
                    self._buffer = content[-prefix_len:]
                    return content[:-prefix_len]
        self._buffer = ""
        return content
