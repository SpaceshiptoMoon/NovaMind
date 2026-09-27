"""DeepDoc 可视化工具：将识别结果绘制到原始图像上（开发调试用）。"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from io import BytesIO
from pathlib import Path
from typing import Any

import PIL
from novamind.engines.document.integrations.deepdoc.compat import LazyImage
from PIL import Image, ImageDraw


def _as_image(value: Image.Image | LazyImage | bytes) -> Image.Image:
    """把 PIL / LazyImage / bytes 输入统一规整为 RGB PIL 图像副本。"""
    if isinstance(value, Image.Image):
        return value.copy()
    if isinstance(value, LazyImage):
        blob = value.first()
        if blob is None:
            raise ValueError("LazyImage does not contain an image blob")
        value = blob
    if isinstance(value, bytes):
        with Image.open(BytesIO(value)) as image:
            return image.convert("RGB")
    raise TypeError(f"Unsupported image value: {type(value)!r}")


def save_results(
    image_list: Sequence[Image.Image | LazyImage | bytes],
    results: Sequence[Sequence[Mapping[str, Any]]],
    labels: Sequence[str] | None = None,
    output_dir: str | Path = "output",
    threshold: float = 0.5,
) -> list[Path]:
    """逐图绘制检测结果并保存为 JPG 到 output_dir。

    Returns:
        保存文件路径列表（按输入顺序编号命名）。
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for index, value in enumerate(image_list):
        detections = results[index] if index < len(results) else []
        image = draw_box(value, detections, labels=labels, threshold=threshold)
        target = output_path / f"{index}.jpg"
        image.save(target, quality=95)
        logging.debug("save result to: %s", target)
        saved.append(target)
    return saved


def draw_box(
    image: Image.Image | LazyImage | bytes,
    result: Iterable[Mapping[str, Any]],
    labels: Sequence[str] | None = None,
    threshold: float = 0.5,
) -> Image.Image:
    """在图像上绘制检测框与类别+置信度标签（低于阈值的不绘制）。

    Args:
        image: 原始图像（PIL / LazyImage / bytes）。
        result: 检测结果列表（bbox 或 x0/top/x1/bottom 字段，像素坐标）。
        labels: 配色用的类别表；None 时从结果中出现的类别自动生成。
        threshold: 绘制阈值，置信度低于该值不绘制。

    Returns:
        绘制后的图像副本（不修改原图）。
    """
    rendered = _as_image(image)
    detections = [item for item in result if float(item.get("score", 1.0)) >= threshold]
    inferred = [str(item.get("type", "unknown")) for item in detections]
    label_values = list(labels or dict.fromkeys(inferred) or ["unknown"])
    colors = get_color_map_list(len(label_values))
    color_by_label = {name.lower(): tuple(colors[index]) for index, name in enumerate(label_values)}
    drawer = ImageDraw.Draw(rendered)
    thickness = max(1, min(rendered.size) // 320)

    for detection in detections:
        label = str(detection.get("type", "unknown"))
        color = color_by_label.get(label.lower(), (255, 0, 0))
        bbox = detection.get("bbox") or [
            detection.get("x0", 0),
            detection.get("top", 0),
            detection.get("x1", 0),
            detection.get("bottom", 0),
        ]
        xmin, ymin, xmax, ymax = [float(value) for value in bbox]
        drawer.line(
            [(xmin, ymin), (xmin, ymax), (xmax, ymax), (xmax, ymin), (xmin, ymin)],
            width=thickness,
            fill=color,
        )
        label_text = f"{label} {float(detection.get('score', 1.0)):.4f}"
        width, height = imagedraw_textsize_c(drawer, label_text)
        text_top = max(0.0, ymin - height)
        drawer.rectangle([(xmin + 1, text_top), (xmin + width + 1, text_top + height)], fill=color)
        drawer.text((xmin + 1, text_top), label_text, fill=(255, 255, 255))
    return rendered


def get_color_map_list(num_classes: int) -> list[list[int]]:
    """按类别数生成 PaddleOCR 风格的可区分配色（按位展开 RGB）。"""
    color_map = num_classes * [0, 0, 0]
    for index in range(num_classes):
        bit_index = 0
        label = index
        while label:
            color_map[index * 3] |= ((label >> 0) & 1) << (7 - bit_index)
            color_map[index * 3 + 1] |= ((label >> 1) & 1) << (7 - bit_index)
            color_map[index * 3 + 2] |= ((label >> 2) & 1) << (7 - bit_index)
            bit_index += 1
            label >>= 3
    return [color_map[index : index + 3] for index in range(0, len(color_map), 3)]


def imagedraw_textsize_c(draw: ImageDraw.ImageDraw, text: str) -> tuple[int, int]:
    """兼容 Pillow <10 的 textsize 测宽高（新版回退 textbbox 量测）。"""
    if int(PIL.__version__.split(".")[0]) < 10:
        return draw.textsize(text)
    left, top, right, bottom = draw.textbbox((0, 0), text)
    return right - left, bottom - top
