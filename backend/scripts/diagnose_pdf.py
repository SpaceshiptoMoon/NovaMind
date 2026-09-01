"""PDF 文字抽取诊断脚本：定位大 PDF 在 DeepDoc layout 模式下抽出 0 字符的真因。

用法（用 backend venv，别用 miniconda）：
    .venv/Scripts/python scripts/diagnose_pdf.py <pdf路径>

对比四个抽取器对同一 PDF 的产出：
  - PyPDF2         （default 解析路径用的库）
  - pdfplumber extract_text   （DeepDoc _plain_parser 用的，对应 plain_sections）
  - pdfplumber extract_words  （DeepDoc parse_into_bboxes 用的，对应 bboxes）
  - PyMuPDF/fitz   （PDF 阅读器级抽取，最能反映"用户能否选中文字"）

输出每页/全文的字符数与词数。判断：
  - extract_text 有字、extract_words 为空  → 词盒抽取失败，改用 plain/default 即可（已修复的报错会提示）
  - extract_text 与 extract_words 均空、fitz 有字 → pdfplumber 对该 PDF 字体解析失败，
    需更深修复（layout/plain 改用 fitz 抽取）；暂可改用 vision（OCR）或 default（PyPDF2）
  - 四者全空                       → 真无文字层（扫描件），走 vision/OCR
"""
from __future__ import annotations

import sys
from pathlib import Path


def _try(label: str, fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - 诊断脚本要吞所有异常继续跑
        return f"<异常: {type(e).__name__}: {e}>"


def diagnose(pdf_path: str) -> None:
    p = Path(pdf_path)
    if not p.exists():
        print(f"文件不存在: {pdf_path}")
        sys.exit(1)
    size_mb = p.stat().st_size / 1024 / 1024
    print(f"=== {p.name}  ({size_mb:.1f} MB) ===\n")

    # 1. PyPDF2（default 路径）
    def _pypdf2():
        from pypdf import PdfReader  # noqa: WPS433

        reader = PdfReader(str(p))
        total = 0
        per_page = []
        for i, page in enumerate(reader.pages):
            t = page.extract_text() or ""
            total += len(t)
            per_page.append(len(t))
        return total, per_page

    # 2. pdfplumber extract_text（plain_sections）
    def _plumber_text():
        import pdfplumber  # noqa: WPS433

        total = 0
        per_page = []
        with pdfplumber.open(str(p)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                total += len(t)
                per_page.append(len(t))
        return total, per_page

    # 3. pdfplumber extract_words（bboxes）
    def _plumber_words():
        import pdfplumber  # noqa: WPS433

        total = 0
        per_page = []
        with pdfplumber.open(str(p)) as pdf:
            for page in pdf.pages:
                words = page.extract_words(keep_blank_chars=False, use_text_flow=False) or []
                total += len(words)
                per_page.append(len(words))
        return total, per_page

    # 4. PyMuPDF/fitz（阅读器级）
    def _fitz():
        import fitz  # noqa: WPS433

        total = 0
        per_page = []
        doc = fitz.open(str(p))
        for page in doc:
            t = page.get_text() or ""
            total += len(t)
            per_page.append(len(t))
        doc.close()
        return total, per_page

    results = {}
    for label, fn in [("PyPDF2", _pypdf2), ("pdfplumber.extract_text", _plumber_text),
                       ("pdfplumber.extract_words", _plumber_words), ("PyMuPDF/fitz", _fitz)]:
        r = _try(label, fn)
        if isinstance(r, tuple):
            total, per_page = r
            nonzero = sum(1 for x in per_page if x > 0)
            print(f"{label:30s} 总量={total:>8}  非空页={nonzero:>4}/{len(per_page)}")
            results[label] = (total, per_page)
        else:
            print(f"{label:30s} {r}")
            results[label] = r

    # 前 10 页逐页对比
    print("\n--- 前 10 页逐页字符数（extract_text / extract_words / fitz） ---")
    pt = results.get("pdfplumber.extract_text")
    pw = results.get("pdfplumber.extract_words")
    fz = results.get("PyMuPDF/fitz")
    for i in range(10):
        t = pt[1][i] if isinstance(pt, tuple) and i < len(pt[1]) else "?"
        w = pw[1][i] if isinstance(pw, tuple) and i < len(pw[1]) else "?"
        f = fz[1][i] if isinstance(fz, tuple) and i < len(fz[1]) else "?"
        print(f"  page {i + 1:>3}: extract_text={t:>6}  extract_words={w:>5}  fitz={f:>6}")

    # 结论
    print("\n=== 结论 ===")
    pt_total = pt[0] if isinstance(pt, tuple) else 0
    pw_total = pw[0] if isinstance(pw, tuple) else 0
    fz_total = fz[0] if isinstance(fz, tuple) else 0
    if pt_total > 0 and pw_total == 0:
        print("extract_text 有字、extract_words 为空 → 词盒抽取失败。改用 plain 或 default 模式即可拿到文本。")
    elif pt_total == 0 and fz_total > 0:
        print("pdfplumber 抽不到字、fitz 能抽到 → pdfplumber 对该 PDF 字体/CMap 解析失败。"
              "暂改用 vision（OCR）或 default（PyPDF2）；根治需让 layout/plain 改用 fitz 抽取。")
    elif pt_total == 0 and pw_total == 0 and fz_total == 0:
        print("四个抽取器全空 → 该 PDF 无文字层（扫描件）。改用 vision 模式（含 OCR）。")
    else:
        print("抽取器部分有产出，需结合逐页数据人工判断。")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: .venv/Scripts/python scripts/diagnose_pdf.py <pdf路径>")
        sys.exit(1)
    diagnose(sys.argv[1])