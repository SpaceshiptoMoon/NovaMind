"""源码乱码门禁：AST 扫描字符串常量，拦截 UTF-8→GBK 误解码形态混入源码。

历史教训（同一失败模式已复发两次）：
1. page_filter TOC_HEADING_PATTERN 中文项 GB18030 乱码（目录→鐩綍），永远匹配不到
   中文目录页；
2. updown_concat.py 全部中文正则 GBK 乱码（绗琜闆朵竴=第一二三四），commit 5c29484
   引入，xgboost 31 特征中 9 个中文特征恒 False、句号永不 break——段落粘连，
   且因显示层有损（Read/Edit 工具往返丢字符）长期不可见。

检测原理（伪影密度）：UTF-8 中文/标点的首字节（E2-E9, EF）与任意尾字节组成的
字节对按 GBK 解码，会产出一个有限字符集（含 锛 銆 鈥 绗 琜 滐 紘 等 1100+ 字符）。
真实中文语句中这些字符占比极低；而"UTF-8 被按 GBK 误解码"的字符串中占比极高。
实测：历史乱码样本密度 0.20-0.50，正常中文 0.00，阈值 0.2 + 伪影数 ≥2 零误报。
"""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# 扫描范围：src 与 tests 全部 Python 源码。
SCAN_ROOTS = [BACKEND_ROOT / "src", BACKEND_ROOT / "tests"]

# allowlist：字符串常量中合法包含 PUA/乱码特征的文件。
# - pdf.py：上游 proj_match 的 [⚫•➢✓]（PUA 是待匹配的真实输入，vendored 保真）
# - page_filter.py：DIRTY_TEXT_PATTERN 需要匹配 PDF 里的锟斤拷类乱码特征串
# - vendor/ragflow/pdf_parser.py：vendored 上游源码，proj_match 同含 PUA bullet 输入
# - 回归测试：断言/文档字符串需要复现乱码形态
# - 本文件：检测器自检样本
STRINGS_ALLOWED_FILES = {
    "src/engines/document/integrations/deepdoc/parsers/pdf.py",
    "src/engines/document/integrations/deepdoc/page_filter.py",
    "src/engines/document/integrations/deepdoc/vendor/ragflow/pdf_parser.py",
    "tests/shared/test_embedding_client_resilience.py",
    "tests/engines/document/deepdoc/test_deepdoc_pdf_fusion.py",
    "tests/engines/document/deepdoc/test_page_filter_dirty_pattern.py",
    "tests/engines/document/deepdoc/test_updown_concat_mojibake_fix.py",
    "tests/architecture/test_source_encoding_gate.py",
}

# 零容错绊线：伪影密度覆盖不到的形态。
# - 复合串：锟斤拷（U+FFFD 对不可逆）、锟斤苟（doc 566 实测变体）、鐩綍（目录 GB18030 乱码）
# - 单字绊线：常见 CJK 标点的 GBK 乱码形态（锛=，銆=。鈥=‘/“滐=”紘=：傦=！紵=？佲/屻=、
#   锘=U+FFFD/0x9D 碎片），真实中文文本几乎不用这些字。新增形态在此追加。
MOJIBAKE_TRIPWIRE_CHARS = ("锟斤拷", "锟斤苟", "鐩綍", "锛", "銆", "鈥", "滐", "紘", "傦", "紵", "佲", "屻", "锘")


@lru_cache(maxsize=1)
def _gbk_artifact_chars() -> frozenset[str]:
    """GBK 解码伪影字符集：UTF-8 中文/标点首字节 × 任意尾字节的 GBK 解码产物。"""
    artifacts: set[str] = set()
    for lead in list(range(0xE2, 0xEA)) + [0xEF]:
        for second in range(0x80, 0x100):
            try:
                artifacts.add(bytes([lead, second]).decode("gbk"))
            except UnicodeDecodeError:
                continue
    return frozenset(artifacts)


def _is_cjk_or_cjk_punct(ch: str) -> bool:
    cp = ord(ch)
    return 0x4E00 <= cp <= 0x9FFF or 0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF


def _artifact_stats(text: str) -> tuple[int, int]:
    """返回 (伪影字符数, CJK 类字符总数)。"""
    cjk_chars = [ch for ch in text if _is_cjk_or_cjk_punct(ch)]
    artifacts = _gbk_artifact_chars()
    return sum(1 for ch in cjk_chars if ch in artifacts), len(cjk_chars)


def _looks_like_utf8_as_gbk_mojibake(text: str) -> bool:
    """伪影字符 ≥2 且占 CJK 比例 ≥0.2 → 判为 UTF-8→GBK 乱码形态。

    双条件防误报：真实中文偶尔含单个伪影字符（如生僻人名用字），密度门槛
    （≥20%）+ 绝对数量门槛（≥2 个）同时满足才会命中。"""
    artifact_count, cjk_count = _artifact_stats(text)
    if cjk_count < 2 or artifact_count < 2:
        return False
    return artifact_count / cjk_count >= 0.2


def _has_raw_pua(text: str) -> bool:
    return any(0xE000 <= ord(ch) <= 0xF8FF for ch in text)


def _is_mojibake(text: str) -> bool:
    """复合判定：单字绊线（精确）或伪影密度（统计）任一命中即乱码。"""
    if any(tripwire in text for tripwire in MOJIBAKE_TRIPWIRE_CHARS):
        return True
    return _looks_like_utf8_as_gbk_mojibake(text)


def _iter_string_constants(source: str):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value:
            yield node.lineno, node.value


def _violations() -> list[str]:
    problems: list[str] = []
    for root in SCAN_ROOTS:
        for py in root.rglob("*.py"):
            rel = py.relative_to(BACKEND_ROOT).as_posix()
            strings_allowed = rel in STRINGS_ALLOWED_FILES
            try:
                source = py.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                problems.append(f"{rel}: 非 UTF-8 源文件（{exc}）")
                continue
            for lineno, value in _iter_string_constants(source):
                if not strings_allowed:
                    if _has_raw_pua(value):
                        problems.append(f"{rel}:{lineno}: 字符串常量含 raw PUA 字符: {value[:40]!r}")
                    if _is_mojibake(value):
                        problems.append(f"{rel}:{lineno}: 字符串常量是 UTF-8→GBK 乱码形态: {value[:40]!r}")
    return problems


@pytest.mark.unit
def test_mojibake_detector_selfcheck():
    """检测器自检：历史乱码样本全命中（绊线或密度任一），正常中文零误报。"""
    # 历史真实乱码（5c29484 的 _match_proj / 题注字符集 / 断段字符集）
    mojibake_samples = [
        "绗琜闆朵竴浜屼笁鍥涗簲鍏竷鍏節鍗佺櫨]+绔?",
        "锛屻€佲€滐紘(",
        "銆傦紵锛?",
        "[鈿€⑩灑飦垛憼鈶?]",
        "鐩綍",
    ]
    for sample in mojibake_samples:
        assert _is_mojibake(sample) is True, sample
    # 正常中文不误报
    for normal in ["第一章 引言", "数据集信息", "不同推荐算法评价指标比较", "摘要：本系统面向企业知识库场景", "，、；："]:
        assert _is_mojibake(normal) is False, normal


@pytest.mark.unit
def test_source_files_contain_no_mojibake_or_raw_pua():
    """门禁主断言：全源码字符串常量不得含乱码形态 / 非法 raw PUA。

    修复新违规时：若字符串本意是正常中文 → 恢复正确字符；若确需匹配乱码输入
    （如 DIRTY_TEXT_PATTERN）→ 加入 STRINGS_ALLOWED_FILES 并在注释里说明理由。
    """
    problems = _violations()
    assert not problems, "发现乱码/PUA 违规:\n" + "\n".join(problems)