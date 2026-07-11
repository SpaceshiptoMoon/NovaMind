from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np

from src.shared.integrations.deepdoc.vision._diagnostic_io import iter_diagnostic_images
from src.shared.integrations.deepdoc.vision.ocr import OCR
from src.shared.integrations.deepdoc.vision.seeit import draw_box


def run_ocr_diagnostics(
    inputs: str | Path,
    output_dir: str | Path = "ocr_outputs",
    *,
    threshold: float = 0.5,
    ocr: Any | None = None,
) -> list[dict[str, Any]]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    runtime = ocr or OCR(autoload=True)
    results: list[dict[str, Any]] = []

    for name, image in iter_diagnostic_images(inputs):
        bgr = np.asarray(image)[:, :, ::-1].copy()
        raw = runtime(bgr) or []
        detections: list[dict[str, Any]] = []
        texts: list[str] = []
        for box, recognition in raw:
            text, score = recognition if isinstance(recognition, (list, tuple)) else (str(recognition), 1.0)
            score = float(score)
            if score < threshold:
                continue
            points = np.asarray(box, dtype=float)
            detections.append(
                {
                    "text": str(text),
                    "type": "ocr",
                    "score": score,
                    "bbox": [
                        float(points[:, 0].min()),
                        float(points[:, 1].min()),
                        float(points[:, 0].max()),
                        float(points[:, 1].max()),
                    ],
                }
            )
            texts.append(str(text))

        image_path = output_path / f"{name}.jpg"
        text_path = output_path / f"{name}.txt"
        draw_box(image, detections, labels=["ocr"], threshold=threshold).save(image_path, quality=95)
        text_path.write_text("\n".join(texts), encoding="utf-8")
        results.append({"source": name, "image": image_path, "text": text_path, "detections": detections})
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run vendored DeepDoc OCR diagnostics")
    parser.add_argument("--inputs", required=True, help="Image/PDF file or directory")
    parser.add_argument("--output_dir", default="./ocr_outputs")
    parser.add_argument("--threshold", type=float, default=0.5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_ocr_diagnostics(args.inputs, args.output_dir, threshold=args.threshold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
