"""查询文本相似度工具（knowledge_ops 共享）。

历史：本模块原为会话内改写检测器（随 QA 对话链清退，检测类已删），
normalize_query 与 char_trigram_similarity 被 gap 聚类与矛盾检测复用而保留。
"""

from __future__ import annotations


def normalize_query(text: str) -> str:
    """查询归一化：转小写、仅保留字母数字（中文整字保留、空白标点剔除）。

    聚类/比对统一入口（gap 聚合与矛盾检测共用），保证同口径。
    """
    return "".join(ch for ch in text.lower() if ch.isalnum())


def char_trigram_similarity(a: str, b: str) -> float:
    """字符 3-gram Jaccard 相似度（0~1）。短于 3 字符的串退化为整体比较。

    选 Jaccard 而非编辑距离：纯集合运算无 O(mn) 动态规划，中文短句场景
    效果与成本折中；阈值语义直观（共有点比例）。
    """
    if not a or not b:
        return 0.0
    if len(a) < 3 or len(b) < 3:
        return 1.0 if a == b else 0.0
    grams_a = {a[i : i + 3] for i in range(len(a) - 2)}
    grams_b = {b[i : i + 3] for i in range(len(b) - 2)}
    intersection = len(grams_a & grams_b)
    if intersection == 0:
        return 0.0
    return intersection / len(grams_a | grams_b)
