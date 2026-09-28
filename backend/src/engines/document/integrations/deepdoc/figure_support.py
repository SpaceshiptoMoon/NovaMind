"""DeepDoc 图表支持：图表检测与提取辅助。"""
from __future__ import annotations

import io
import time
from functools import wraps
from typing import Any

from novamind.engines.document.integrations.deepdoc.compat import LazyImage
from PIL import Image


class LLMType:
    """模型类型常量（standalone 模式仅保留 image2text）。"""
    IMAGE2TEXT = "image2text"


class LLMBundle:
    """RAGFlow 租户模型束占位：standalone DeepDoc 下一律拒绝构造。"""
    def __init__(self, *args, **kwargs):
        """构造即拒绝：standalone 模式无租户模型服务。"""
        raise RuntimeError("RAGFlow tenant model services are not available in standalone DeepDoc")


def get_tenant_default_model_by_type(*args, **kwargs):
    """租户默认模型查询占位：调用即报错，强制调用方显式传 vision_model。"""
    raise RuntimeError("Provide vision_model explicitly when using standalone DeepDoc")


def timeout(_seconds: int, attempts: int = 1):
    """Retry a callable without introducing RAGFlow's signal-based timeout。

    Args:
        _seconds: 兼容上游签名的占位参数（不生效）。
        attempts: 重试次数，最小按 1 计。

    Returns:
        装饰器：被装饰函数按次数重试，全失败抛最后一次异常。
    """

    def decorator(func):
        """被装饰函数包一层重试。"""
        @wraps(func)
        def wrapped(*args, **kwargs):
            """按 attempts 重试调用，全失败抛最后一次异常。"""
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
    """把 PIL/LazyImage/字节流统一转为 RGB PIL 图；不可识别返回 None。

    Args:
        image: PIL 图 / LazyImage / 字节流之一。

    Returns:
        RGB PIL 图；不可识别输入为 None。
    """
    if isinstance(image, Image.Image):
        return image
    if isinstance(image, LazyImage):
        image = image.first()
    if isinstance(image, (bytes, bytearray, memoryview)):
        with Image.open(io.BytesIO(bytes(image))) as opened:
            return opened.convert("RGB")
    return None


def open_image_for_processing(image: Any, allow_bytes: bool = False) -> tuple[Image.Image | None, bool]:
    """打开待处理图片，返回 (图, 是否新打开)。
    
    已有 PIL 原样返回（调用方不应关闭）；bytes 在 allow_bytes=True 时
    打开并返回 True（调用方负责关闭），否则返回 (None, False)。
    """
    if isinstance(image, Image.Image):
        return image, False
    if isinstance(image, LazyImage):
        image = image.first()
    if allow_bytes and isinstance(image, (bytes, bytearray, memoryview)):
        opened = Image.open(io.BytesIO(bytes(image)))
        return opened.convert("RGB"), True
    return None, False


def is_image_like(image: Any) -> bool:
    """对象是否为可处理的图片形态（PIL/LazyImage/字节）。

    Args:
        image: 待检测对象。

    Returns:
        是可处理图片形态为 True。
    """
    return isinstance(image, (Image.Image, LazyImage, bytes, bytearray, memoryview))


def vision_llm_figure_describe_prompt() -> str:
    """图表描述默认提示词（标签/趋势/关系）。"""
    return "Describe the figure accurately, including visible labels, trends, and relationships."


def vision_llm_figure_describe_prompt_with_context(
    *,
    context_above: str = "",
    context_below: str = "",
) -> str:
    """带上下文的图表描述提示词（拼上图/下图文本）。

    Args:
        context_above: 图表上方文本。
        context_below: 图表下方文本。

    Returns:
        拼接后的完整提示词。
    """
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
    """调视觉模型生成图片描述文本。
    
    vision_model 接受可调用对象或带 describe/generate/invoke 方法的对象；
    返回 dict 时取 text/content 键。模型缺失返回空串。
    """
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
    """为每个图表附上下文文本（return_context=True 时）。
    
    把 sections 文本截前 context_size 字符作为每个 figure 的上文；
    return_context=False 时原样返回 figures_data。
    """
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
