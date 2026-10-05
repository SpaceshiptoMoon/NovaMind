"""公共切句纯函数：中英文句读边界的权威实现（句子窗口策略的底层原语）。

切分契约：句读保留在前句尾部、零宽断言切分不丢任何字符、无标点段整段保留。
注意：engines 层已有的 recursive（分隔符层级下探）与 markdown（_split_by_sentences
组合打包）两处句处理各自服务于其聚合语义，不可直接复用；本模块只提供「句序列」
这一最小原语，供 SentenceWindowSplitter 按「每句一检索单元」消费。
"""
import re

from novamind.engines.document.splitters.fixed_size_splitter import FixedSizeSplitter

# 全部句读统一「后随边界才断」：中文句读（。！？）是全角标点、文本中几乎
# 只作句读用，后必断；英文句读（. ! ?）在 URL query（path?q=1）、缩写（e.g.）
# 中高频出现，仅在后随空白或文末时才断——避开 path?q=1、3.14、v1.2 被误切。
# 零宽断言 split 不消耗分隔符，句读符号天然保留在前句尾部。
_SENTENCE_BOUNDARY = re.compile(
    r"(?<=[。！？])|(?<=[.!?！？])(?=\s|$)"
)


def split_sentences(text: str, max_sentence_length: int = 1000) -> list[str]:
    """把文本切成句序列，句读保留在前句尾部，不丢任何字符。

    Args:
        text: 待切分文本。
        max_sentence_length: 单句硬切上限；超过此长度的句（无句读长段/超长
            复合句）按固定窗口切成多个子句，窗口不重叠。

    Returns:
        非空句列表（句读随句尾保留）；纯空白输入返回空列表。无句读的段落
        整段成为单句——绝不静默丢弃（对齐 markdown 切句的审计教训）。
    """
    if not text or not text.strip():
        return []

    sentences: list[str] = []
    for seg in _SENTENCE_BOUNDARY.split(text):
        seg = seg.strip()
        if not seg:
            continue
        if len(seg) <= max_sentence_length:
            sentences.append(seg)
        else:
            # 超长句硬切：复用 FixedSizeSplitter 的滑动窗口不变量
            #（末块整块输出防死循环），与 DelimiterSplitter 复用同一先例。
            sentences.extend(
                FixedSizeSplitter(
                    chunk_size=max_sentence_length, chunk_overlap=0
                )._split_text_fixed_size(seg)
            )
    return sentences
