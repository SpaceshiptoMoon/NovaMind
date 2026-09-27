"""DeepDoc 表格识别器：表格结构检测 + 单元格内容 OCR。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from novamind.engines.document.integrations.deepdoc.vision._diagnostic_io import (
    iter_diagnostic_images,
)
from novamind.engines.document.integrations.deepdoc.vision.layout_recognizer import (
    LayoutRecognizer4YOLOv10 as LayoutRecognizer,
)
from novamind.engines.document.integrations.deepdoc.vision.seeit import draw_box
from novamind.engines.document.integrations.deepdoc.vision.table_structure_recognizer import (
    TableStructureRecognizer,
)


def run_recognizer_diagnostics(
    inputs: str | Path,
    output_dir: str | Path = "layout_outputs",
    *,
    mode: str = "layout",
    threshold: float = 0.5,
    recognizer: Any | None = None,
) -> list[dict[str, Any]]:
    """对图像/PDF 跑 layout / TSR 检测诊断：输出标注图像与 JSON 检测明细。

    Args:
        inputs: 图像/PDF 文件或目录。
        output_dir: 输出目录（自动创建）。
        mode: "layout" 为版面检测，"tsr" 为表格结构检测。
        threshold: 置信度阈值。
        recognizer: 外部注入的识别器运行时；None 时内部构建。

    Returns:
        每个输入的诊断结果 dict（source/image/json/detections）。
    """
    normalized_mode = mode.lower()
    if normalized_mode not in {"layout", "tsr"}:
        raise ValueError("mode must be 'layout' or 'tsr'")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    images = list(iter_diagnostic_images(inputs))
    pil_images = [image for _, image in images]
    runtime = recognizer or (
        LayoutRecognizer(autoload=True)
        if normalized_mode == "layout"
        else TableStructureRecognizer(autoload=True)
    )

    if normalized_mode == "layout":
        raw_results = runtime.forward(pil_images, thr=threshold, batch_size=16)
    else:
        raw_results = runtime(pil_images, thr=threshold)

    outputs: list[dict[str, Any]] = []
    labels = list(getattr(runtime, "labels", []))
    for index, (name, image) in enumerate(images):
        raw_items = raw_results[index] if index < len(raw_results) else []
        detections = [_normalize_detection(item, normalized_mode) for item in raw_items]
        image_path = output_path / f"{name}-{normalized_mode}.jpg"
        json_path = output_path / f"{name}-{normalized_mode}.json"
        draw_box(image, detections, labels=labels, threshold=threshold).save(image_path, quality=95)
        json_path.write_text(json.dumps(detections, ensure_ascii=False, indent=2), encoding="utf-8")
        outputs.append({"source": name, "image": image_path, "json": json_path, "detections": detections})
    return outputs


def _normalize_detection(item: dict[str, Any], mode: str) -> dict[str, Any]:
    """统一不同输出形态为 {type, score, bbox}（tsr 框取 label 与 x0/top/x1/bottom 字段）。"""
    if mode == "tsr" and "label" in item:
        return {
            "type": str(item["label"]),
            "score": float(item.get("score", 1.0)),
            "bbox": [float(item["x0"]), float(item["top"]), float(item["x1"]), float(item["bottom"])],
        }
    return {
        "type": str(item.get("type", "unknown")),
        "score": float(item.get("score", 1.0)),
        "bbox": [float(value) for value in item.get("bbox", [0, 0, 0, 0])],
    }


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="Run vendored DeepDoc layout/TSR diagnostics")
    parser.add_argument("--inputs", required=True, help="Image/PDF file or directory")
    parser.add_argument("--output_dir", default="./layout_outputs")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--mode", choices=["layout", "tsr"], default="layout")
    return parser


def main(argv: list[str] | None = None) -> int:
    """命令行入口：解析参数后执行 layout/TSR 诊断，返回退出码 0。"""
    args = build_parser().parse_args(argv)
    run_recognizer_diagnostics(
        args.inputs,
        args.output_dir,
        mode=args.mode,
        threshold=args.threshold,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
