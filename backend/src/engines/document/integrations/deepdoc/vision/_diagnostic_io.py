"""DeepDoc 视觉诊断 I/O：开发调试用中间产物（图像标注 / 识别结果）的读写。"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from PIL import Image

_IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def iter_diagnostic_images(inputs: str | Path) -> Iterator[tuple[str, Image.Image]]:
    """遍历诊断输入：图像文件逐个产出，PDF 展开为逐页图像。

    Args:
        inputs: 图像/PDF 文件，或目录（子文件按名称排序处理）。

    Yields:
        (输入名（stem 或 stem-page-N）, RGB PIL 图像) 元组。

    Raises:
        FileNotFoundError: 输入路径不存在。
    """
    source = Path(inputs)
    if not source.exists():
        raise FileNotFoundError(f"Diagnostic input does not exist: {source}")
    paths = sorted(source.iterdir()) if source.is_dir() else [source]
    for path in paths:
        suffix = path.suffix.lower()
        if suffix in _IMAGE_EXTENSIONS:
            with Image.open(path) as image:
                yield path.stem, image.convert("RGB")
        elif suffix == ".pdf":
            yield from _iter_pdf_pages(path)


def _iter_pdf_pages(path: Path) -> Iterator[tuple[str, Image.Image]]:
    """以 2 倍缩放把 PDF 逐页栅格化为 RGB 图像（依赖 PyMuPDF）。"""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF diagnostic inputs") from exc
    document = fitz.open(path)
    try:
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            yield f"{path.stem}-page-{index + 1}", image
    finally:
        document.close()
