#!/usr/bin/env python3
"""Generate the lightweight packages used by the standalone DeepDoc image.

Adapted from RAGFlow ``deepdoc/server/docker_stubs.py``. The upstream script
writes to ``/app`` at import time. This version exposes an explicit function so
the project can reuse and test the behavior without filesystem side effects.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


DEFAULT_TARGET = Path(os.environ.get("STUB_TARGET", "/app"))

STUB_FILES: Mapping[str, str] = {
    "deepdoc/__init__.py": """
# Minimal deepdoc package for the standalone inference image.
""",
    "deepdoc/vision/__init__.py": """
# Minimal DeepDoc vision exports without the full RAGFlow dependency tree.
from .ocr import OCR
from .recognizer import Recognizer
from .layout_recognizer import LayoutRecognizer
from .table_structure_recognizer import TableStructureRecognizer

__all__ = ["OCR", "Recognizer", "LayoutRecognizer", "TableStructureRecognizer"]
""",
    "common/__init__.py": """
import os


class _Settings:
    PARALLEL_DEVICES = int(os.environ.get("PARALLEL_DEVICES", "0"))


settings = _Settings()
""",
    "common/file_utils.py": """
import os

_PROJECT_BASE = None


def get_project_base_directory(*args):
    global _PROJECT_BASE
    if _PROJECT_BASE is None:
        _PROJECT_BASE = os.environ.get("RAGFLOW_PROJECT_BASE", "/app")
    if args:
        return os.path.join(_PROJECT_BASE, *args)
    return _PROJECT_BASE
""",
    "common/misc_utils.py": """
def pip_install_torch(*args, **kwargs):
    try:
        import torch  # noqa: F401
    except ImportError:
        pass
""",
    "rag/__init__.py": """
# Minimal rag package for the standalone inference image.
""",
    "rag/nlp/__init__.py": """
class _StubTokenizer:
    def tokenize(self, text):
        return text

    def tag(self, word):
        return ""


rag_tokenizer = _StubTokenizer()
""",
    "rag/utils/lazy_image.py": """
from PIL import Image


def ensure_pil_image(image):
    if isinstance(image, Image.Image):
        return image
    return None
""",
}


def write_docker_stubs(target: str | os.PathLike[str] = DEFAULT_TARGET) -> list[Path]:
    """Write RAGFlow-compatible lightweight modules beneath ``target``."""
    target_path = Path(target)
    written: list[Path] = []
    for relative_path, content in STUB_FILES.items():
        destination = target_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content.lstrip("\n"), encoding="utf-8")
        written.append(destination)
    return written


def main() -> int:
    written = write_docker_stubs()
    print(f"Docker stubs written to {DEFAULT_TARGET} ({len(written)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
