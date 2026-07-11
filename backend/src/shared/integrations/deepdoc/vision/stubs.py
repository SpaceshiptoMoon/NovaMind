from __future__ import annotations

def _unavailable(component: str):
    raise RuntimeError(
        f"DeepDoc {component} is vendored as a scaffold, but the full upstream implementation is not integrated yet",
    )


class OCR:
    def __init__(self, *args, **kwargs):
        _unavailable("vision OCR")


class LayoutRecognizer:
    def __init__(self, *args, **kwargs):
        _unavailable("vision layout recognizer")


class AscendLayoutRecognizer:
    def __init__(self, *args, **kwargs):
        _unavailable("vision ascend layout recognizer")


class TableStructureRecognizer:
    def __init__(self, *args, **kwargs):
        _unavailable("vision table recognizer")
