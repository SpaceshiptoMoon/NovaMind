"""ASR 转写质量评测（批次④ CER/WER 基建）。

纯逻辑无外部依赖：中文场景以 CER（字符错误率）为主指标，英文/混排用
WER（词错误率）可选。供后续把「标注参考 + ASR 输出」的对比接入 kb-ops
质量基线或独立评测脚本；本身不读取文件、不依赖 feature 层。

判据（Levenshtein 编辑距离，字符/词两级）：
    CER = (S + D + I) / N_ref
    S/D/I = 替换/删除/插入操作数，N_ref = 参考文本字符数。
"""
from __future__ import annotations


def _strip_for_eval(text: str) -> str:
    """评测前的文本归一：去空白与标点，统一小写（英文）。

    CER 评测惯例：标点与空白不计入错误（ASR 标点输出与参考标注惯例常
    不一致，计入会污染识别准确率本身）。
    """
    import re

    text = str(text or "")
    text = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    return text.lower()


def _edit_distance_ops(ref: list[str], hyp: list[str]) -> tuple[int, int, int]:
    """Levenshtein 对齐，返回 (替换, 删除, 插入) 操作数（标准 DP 回溯）。"""
    n, m = len(ref), len(hyp)
    # dp[i][j] = ref[:i] 与 hyp[:j] 的编辑距离
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,      # 删除（ref 字符被删）
                dp[i][j - 1] + 1,      # 插入（hyp 多出字符）
                dp[i - 1][j - 1] + cost,  # 替换/匹配
            )
    # 回溯统计操作数
    s = d = ins = 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (
            0 if ref[i - 1] == hyp[j - 1] else 1
        ):
            if ref[i - 1] != hyp[j - 1]:
                s += 1
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            d += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return s, d, ins


def cer(reference: str, hypothesis: str) -> dict:
    """字符错误率（中文 ASR 主指标）。

    Args:
        reference: 人工标注参考文本。
        hypothesis: ASR 转写输出。

    Returns:
        {"cer": float, "substitutions": int, "deletions": int,
         "insertions": int, "ref_length": int}；参考为空时 cer=0（无从谈起，
        调用方应避免空参考）。
    """
    ref = list(_strip_for_eval(reference))
    hyp = list(_strip_for_eval(hypothesis))
    if not ref:
        return {
            "cer": 0.0, "substitutions": 0, "deletions": 0,
            "insertions": 0, "ref_length": 0,
        }
    s, d, ins = _edit_distance_ops(ref, hyp)
    return {
        "cer": round((s + d + ins) / len(ref), 4),
        "substitutions": s,
        "deletions": d,
        "insertions": ins,
        "ref_length": len(ref),
    }


def wer(reference: str, hypothesis: str) -> dict:
    """词错误率（英文/混排场景可选指标；中文按字成词——单字一个「词」）。"""
    ref = _strip_for_eval(reference)
    hyp = _strip_for_eval(hypothesis)
    # 中文无空格分词，字符级即词级；英文按空白切（归一后空白已删，此处
    # 对英文参考用原文分词）
    ref_words = _words(reference)
    hyp_words = _words(hypothesis)
    if not ref_words:
        return {
            "wer": 0.0, "substitutions": 0, "deletions": 0,
            "insertions": 0, "ref_length": 0,
        }
    s, d, ins = _edit_distance_ops(ref_words, hyp_words)
    return {
        "wer": round((s + d + ins) / len(ref_words), 4),
        "substitutions": s,
        "deletions": d,
        "insertions": ins,
        "ref_length": len(ref_words),
    }


def _words(text: str) -> list[str]:
    """WER 分词：英文按空白；CJK 连续串逐字拆（字即词）。"""
    import re

    tokens: list[str] = []
    for tok in str(text or "").split():
        # CJK 段逐字拆
        for ch in re.findall(r"[一-鿿㐀-䶿]|\S+", tok):
            if len(ch) == 1 and re.match(r"[一-鿿㐀-䶿]", ch):
                tokens.append(ch)
            else:
                tokens.append(ch.lower())
    return tokens


def evaluate_transcript(reference: str, hypothesis: str) -> dict:
    """综合评测入口：同时给 CER 与 WER（上层按语种取主指标）。"""
    return {
        "cer": cer(reference, hypothesis),
        "wer": wer(reference, hypothesis),
    }
