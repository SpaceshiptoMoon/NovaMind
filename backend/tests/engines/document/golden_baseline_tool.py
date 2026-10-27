"""金样基线工具：冻结/刷新基线快照 + 解析基准报告。

用法（backend/ 下，.venv/Scripts/python）：
    冻结/刷新基线：
        tests/engines/document/golden_baseline_tool.py --refresh
    基准报告（指标 + 耗时，输出 stdout，默认 full 口径）：
        tests/engines/document/golden_baseline_tool.py --bench

公开样例在 golden_samples/（入库）；补充敏感文档放 backend/test_data/golden/（gitignore），基线快照写
tests/engines/document/golden_baseline.json（入库，仅 sha256 与计数，
无文档内容）。refresh 是「解析行为变更已确认为预期」后的显式动作。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
    DeepDocParser,
)

GOLDEN_DIRS = (
    BACKEND_ROOT / "tests" / "engines" / "document" / "golden_samples",
    BACKEND_ROOT / "test_data" / "golden",
)
BASELINE_PATH = BACKEND_ROOT / "tests" / "engines" / "document" / "golden_baseline.json"

SUPPORTED_SUFFIXES = {
    "pdf", "docx", "xlsx", "xls", "ppt", "pptx", "epub", "jpg", "jpeg", "png",
    "gif", "webp", "bmp", "txt", "md", "markdown", "csv", "json", "html",
    "eml", "msg", "ofd",
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _samples() -> list[Path]:
    samples: list[Path] = []
    for directory in GOLDEN_DIRS:
        if directory.is_dir():
            samples.extend(
                p for p in directory.iterdir()
                if p.is_file() and p.suffix.lower().lstrip(".") in SUPPORTED_SUFFIXES
            )
    return sorted(samples)


def _parse_all(pdf_mode: str = "plain"):
    parser = DeepDocParser()
    for index, sample in enumerate(_samples(), start=1):
        key = f"sample_{index:03d}"
        parsing_config = (
            {"deepdoc_pdf_mode": pdf_mode} if sample.suffix.lower() == ".pdf" else {}
        )
        started = time.perf_counter()
        result = asyncio.run(
            parser.parse_bytes(
                sample.read_bytes(), file_type=sample.suffix.lower().lstrip("."),
                parsing_config=parsing_config, splitting_config={"chunk_size": 1000},
            )
        )
        yield key, sample, result, (time.perf_counter() - started) * 1000


def _snapshot(result, key: str) -> dict:
    kind_counts = Counter(
        block.get("kind", "unknown")
        for block in result.metadata.get("document_blocks") or []
    )
    return {
        "full_text_sha256": _sha256(result.full_text),
        "markdown_sha256": _sha256(result.markdown or ""),
        "chunk_count": len(result.chunks),
        "char_count": len(result.full_text),
        "block_kinds": dict(sorted(kind_counts.items())),
    }


def refresh(pdf_mode: str = "plain") -> None:
    """重跑全部金样并冻结基线快照（覆盖 golden_baseline.json）。

    口径必须与门禁测试一致：PDF 走 plain（默认）；变更口径即变更基线语义。
    """
    samples = _samples()
    if not samples:
        print("金样目录为空，无基线可冻结")
        return
    baseline: dict[str, dict] = {}
    for key, sample, result, _duration in _parse_all(pdf_mode=pdf_mode):
        baseline[key] = _snapshot(result, key)
        print(f"{key} <- {sample.name}: {len(result.full_text)} 字符, {len(result.chunks)} chunks")
    BASELINE_PATH.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"基线已冻结（pdf_mode={pdf_mode}）：{BASELINE_PATH}（{len(baseline)} 个样本）")


def bench(pdf_mode: str = "full") -> None:
    """解析基准报告：各样本产物规模/结构计数/耗时/警告数。

    默认 full 模式（真实产线口径，OCR/版面全流水线）——手动按需跑。
    """
    samples = _samples()
    if not samples:
        print("金样目录为空")
        return
    rows = []
    for key, sample, result, duration in _parse_all(pdf_mode=pdf_mode):
        quality = result.metadata.get("quality") or {}
        rows.append({
            "sample": key,
            "file": sample.name,
            "suffix": sample.suffix.lower(),
            "char_count": len(result.full_text),
            "chunk_count": len(result.chunks),
            "markdown_chars": len(result.markdown or ""),
            "duration_ms": round(duration),
            "warnings": len(quality.get("warnings") or []),
        })
    print(f"pdf_mode={pdf_mode}")
    print(f"{'样本':<10} {'格式':<6} {'字符':>8} {'块':>6} {'md字符':>8} {'耗时ms':>8} {'警告':>4}  文件")
    for row in rows:
        print(
            f"{row['sample']:<10} {row['suffix']:<6} {row['char_count']:>8} "
            f"{row['chunk_count']:>6} {row['markdown_chars']:>8} {row['duration_ms']:>8} {row['warnings']:>4}  {row['file']}"
        )
    total_ms = sum(row["duration_ms"] for row in rows)
    print(f"\n合计 {len(rows)} 样本，{total_ms} ms，均值 {total_ms // max(len(rows), 1)} ms")


def main() -> None:
    ap = argparse.ArgumentParser(description="金样基线与基准工具")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--refresh", action="store_true", help="重跑金样冻结基线快照（pdf plain 口径）")
    group.add_argument("--bench", action="store_true", help="输出解析基准报告（pdf full 口径）")
    ap.add_argument("--pdf-mode", default=None, choices=["plain", "full"], help="覆盖 PDF 解析模式")
    args = ap.parse_args()
    if args.refresh:
        refresh(pdf_mode=args.pdf_mode or "plain")
    else:
        bench(pdf_mode=args.pdf_mode or "full")


if __name__ == "__main__":
    main()
