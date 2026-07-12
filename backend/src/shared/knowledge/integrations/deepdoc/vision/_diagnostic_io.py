from __future__ import annotations

from pathlib import Path
from typing import Iterator

from PIL import Image

_IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def iter_diagnostic_images(inputs: str | Path) -> Iterator[tuple[str, Image.Image]]:
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
