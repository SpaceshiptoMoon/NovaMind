"""
ANSI 转义序列剥离工具

参考 Hermes tools/ansi_strip.py，覆盖完整 ECMA-48 规范：
- CSI 序列（颜色、光标移动等）
- OSC 序列（窗口标题等）
- DCS/SOS/PM/APC 字符串
- 8-bit C1 控制字符

性能优化：快速路径检查，无转义字节时跳过正则匹配。
"""

import re

# 完整 ECMA-48 ANSI 转义序列正则
_ANSI_ESCAPE_RE = re.compile(
    r"\x1b"
    r"(?:"
        # CSI 序列: ESC [ <params> <intermediates> <final>
        r"\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"
        # OSC 序列: ESC ] ... (BEL 或 ESC \)
        r"|\][\s\S]*?(?:\x07|\x1b\\)"
        # DCS/SOS/PM/APC 字符串: ESC P/X/^/_ ... ESC \
        r"|[PX^_][\s\S]*?(?:\x1b\\)"
        # nF 转义序列: ESC <intermediates> <final>
        r"|[\x20-\x2f]+[\x30-\x7e]"
        # Fp/Fe/Fs 单字节序列
        r"|[\x30-\x7e]"
    r")"
    # 8-bit CSI
    r"|\x9b[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"
    # 8-bit OSC
    r"|\x9d[\s\S]*?(?:\x07|\x9c)"
    # 其他 8-bit C1 控制字符
    r"|[\x80-\x9f]",
    re.DOTALL,
)

# 快速路径：检查是否包含转义字节
_HAS_ESCAPE = re.compile(r"[\x1b\x80-\x9f]")


def strip_ansi(text: str) -> str:
    """剥离文本中的 ANSI 转义序列

    Args:
        text: 可能包含 ANSI 转义序列的文本

    Returns:
        剥离转义序列后的纯文本
    """
    if not text:
        return text
    # 快速路径：无转义字节时直接返回
    if not _HAS_ESCAPE.search(text):
        return text
    return _ANSI_ESCAPE_RE.sub("", text)
