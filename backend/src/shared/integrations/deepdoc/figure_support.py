from __future__ import annotations

import io
import time
from functools import wraps
from typing import Any

from PIL import Image

from src.shared.integrations.deepdoc.compat import LazyImage


class LLMType:
    IMAGE2TEXT = "image2text"


class LLMBundle:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("RAGFlow tenant model services are not available in standalone DeepDoc")


def get_tenant_default_model_by_type(*args, **kwargs):
    raise RuntimeError("Provide vision_model explicitly when using standalone DeepDoc")


def timeout(_seconds: int, attempts: int = 1):
    """Retry a callable without introducing RAGFlow's signal-based timeout."""

    def decorator(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            last_error = None
            for attempt in range(max(1, attempts)):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_error = exc
                    if attempt + 1 < max(1, attempts):
                        time.sleep(0)
            raise last_error

        return wrapped

    return decorator


def ensure_pil_image(image: Any) -> Image.Image | None:
    if isinstance(image, Image.Image):
        return image
    if isinstance(image, LazyImage):
        image = image.first()
    if isinstance(image, (bytes, bytearray, memoryview)):
        with Image.open(io.BytesIO(bytes(image))) as opened:
            return opened.convert("RGB")
    return None


def open_image_for_processing(image: Any, allow_bytes: bool = False) -> tuple[Image.Image | None, bool]:
    if isinstance(image, Image.Image):
        return image, False
    if isinstance(image, LazyImage):
        image = image.first()
    if allow_bytes and isinstance(image, (bytes, bytearray, memoryview)):
        opened = Image.open(io.BytesIO(bytes(image)))
        return opened.convert("RGB"), True
    return None, False


def is_image_like(image: Any) -> bool:
    return isinstance(image, (Image.Image, LazyImage, bytes, bytearray, memoryview))


def vision_llm_figure_describe_prompt() -> str:
    return "Describe the figure accurately, including visible labels, trends, and relationships."


def vision_llm_figure_describe_prompt_with_context(
    *,
    context_above: str = "",
    context_below: str = "",
) -> str:
    return (
        f"{vision_llm_figure_describe_prompt()}\n"
        f"Context above:\n{context_above}\n"
        f"Context below:\n{context_below}"
    )


def picture_vision_llm_chunk(
    *,
    binary: Any,
    vision_model: Any,
    prompt: str,
    callback=None,
) -> str:
    if vision_model is None:
        return ""
    callback = callback or (lambda progress, message: None)
    callback(0.0, "Describing figure")
    if callable(vision_model):
        result = vision_model(binary, prompt)
    else:
        result = None
        for method_name in ("describe", "generate", "invoke"):
            method = getattr(vision_model, method_name, None)
            if callable(method):
                result = method(binary, prompt)
                break
        if result is None:
            raise TypeError("vision_model must be callable or expose describe/generate/invoke")
    if isinstance(result, dict):
        result = result.get("text") or result.get("content") or ""
    return str(result or "")


def append_context2table_image4pdf(
    sections,
    figures_data,
    context_size: int,
    *,
    return_context: bool = False,
):
    if not return_context:
        return figures_data
    texts = []
    for section in sections or []:
        if isinstance(section, str):
            texts.append(section)
        elif isinstance(section, (tuple, list)) and section:
            texts.append(str(section[0]))
    joined = "\n".join(texts)
    if context_size <= 0:
        return [("", "") for _ in figures_data]
    context = joined[:context_size]
    return [(context, "") for _ in figures_data]
