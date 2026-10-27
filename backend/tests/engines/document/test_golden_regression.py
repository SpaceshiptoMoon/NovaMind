"""金样回归门禁：真实文档解析产物与基线快照 diff，防隐性质量退化。

设计（脱敏优先）：
- 样例两个来源：``tests/engines/document/golden_samples/``（开源公开样例，
  入库，门禁永远可用）+ ``backend/test_data/golden/``（gitignore 本地目录，
  放敏感真实文档，文件名任意）；
- 入库的只有 ``golden_baseline.json`` 指标快照（sha256 + 结构计数），
  不含任何文档内容；
- 两目录均空 → skip（门禁依赖语料，诚实标记不可用而非假绿）；
- 解析行为变更（引擎改动影响真实文档产物）→ 快照 diff FAIL，确认预期后
  经 ``test_data/_probe/golden_baseline_tool.py --refresh`` 显式刷新基线。

指标口径：full_text/markdown 的 sha256、chunk 数、统一块按 kind 计数。
duration 不进对比（机器波动）。PDF 门禁走 plain 模式（文字层快路径，快、
稳定、无模型依赖）；full 模式（OCR/版面）产物更重但耗时长，留给 --bench
基准工具按需手动跑，不进全量测试套件。
"""
import asyncio
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit

from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
    DeepDocParser,
)

GOLDEN_DIRS = (
    Path(__file__).parent / "golden_samples",  # 入库公开样例（门禁永远可用）
    BACKEND_ROOT / "test_data" / "golden",     # 本地敏感真实文档（gitignore）
)
BASELINE_PATH = Path(__file__).parent / "golden_baseline.json"

# 支持的解析后缀（与 runtime 路由一致）
SUPPORTED_SUFFIXES = {
    "pdf", "docx", "xlsx", "xls", "ppt", "pptx", "epub", "jpg", "jpeg", "png",
    "gif", "webp", "bmp", "txt", "md", "markdown", "csv", "json", "html",
    "eml", "msg", "ofd",
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _golden_samples() -> list[Path]:
    samples: list[Path] = []
    for directory in GOLDEN_DIRS:
        if directory.is_dir():
            samples.extend(
                p for p in directory.iterdir()
                if p.is_file() and p.suffix.lower().lstrip(".") in SUPPORTED_SUFFIXES
            )
    return sorted(samples)


def _snapshot(result, name: str) -> dict:
    kind_counts = Counter(
        block.get("kind", "unknown")
        for block in result.metadata.get("document_blocks") or []
    )
    return {
        "sample": name,
        "full_text_sha256": _sha256(result.full_text),
        "markdown_sha256": _sha256(result.markdown or ""),
        "chunk_count": len(result.chunks),
        "char_count": len(result.full_text),
        "block_kinds": dict(sorted(kind_counts.items())),
    }


def test_golden_regression_against_baseline():
    """真实文档解析产物与基线快照逐项 diff：哈希/计数变化即 FAIL。"""
    samples = _golden_samples()
    if not samples:
        pytest.skip(
            "金样目录为空，门禁不可用——放置文档到 golden_samples/ 或 "
            "test_data/golden/ 后运行 golden_baseline_tool.py --refresh"
        )
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8")) if BASELINE_PATH.exists() else {}
    assert baseline, "基线快照文件缺失/为空——先运行 golden_baseline_tool.py --refresh"

    parser = DeepDocParser()
    mismatches: list[str] = []
    unknown: list[str] = []
    for index, sample in enumerate(samples, start=1):
        key = f"sample_{index:03d}"
        parsing_config = (
            {"deepdoc_pdf_mode": "plain"} if sample.suffix.lower() == ".pdf" else {}
        )
        result = asyncio.run(
            parser.parse_bytes(
                sample.read_bytes(), file_type=sample.suffix.lower().lstrip("."),
                parsing_config=parsing_config, splitting_config={"chunk_size": 1000},
            )
        )
        snapshot = _snapshot(result, key)
        expected = baseline.get(key)
        if expected is None:
            unknown.append(key)
            continue
        for field in ("full_text_sha256", "markdown_sha256", "chunk_count", "char_count", "block_kinds"):
            if snapshot[field] != expected.get(field):
                mismatches.append(
                    f"{key}({sample.name}).{field}: 基线={expected.get(field)!r} 当前={snapshot[field]!r}"
                )
    if unknown:
        pytest.fail(
            f"基线缺少 {unknown}——文档集合已变化，运行 --refresh 重新冻结基线"
        )
    assert not mismatches, (
        "解析产物与基线不一致（引擎行为变更影响真实文档）：\n" + "\n".join(mismatches)
        + "\n确认变更为预期后运行 test_data/_probe/golden_baseline_tool.py --refresh"
    )
