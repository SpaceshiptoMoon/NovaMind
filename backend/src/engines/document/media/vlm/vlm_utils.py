"""VLM 工具：图像 data URL 构建 + VLM 消息构造 + 多模型 fallback 调用。"""
import base64
from typing import Any


def build_image_data_url(file_bytes: bytes, mime_type: str) -> str:
    """将图片二进制内容编码为 data URL。

    Args:
        file_bytes: 图片字节流。
        mime_type: MIME 类型。

    Returns:
        data:{mime};base64,... 形式的字符串。
    """
    base64_data = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{base64_data}"


def build_vlm_image_messages(file_bytes: bytes, mime_type: str, text_prompt: str) -> list[dict[str, Any]]:
    """构建 OpenAI 兼容格式的图片多模态消息。

    Args:
        file_bytes: 图片字节流。
        mime_type: MIME 类型。
        text_prompt: 随图发送的文本指令。

    Returns:
        单条 user 消息的列表（content 为 image_url + text 两段）。
    """
    return [{
        "role": "user",
        "content": [
            {
                "type": "image_url",
                "image_url": {"url": build_image_data_url(file_bytes, mime_type)},
            },
            {
                "type": "text",
                "text": text_prompt,
            },
        ],
    }]


def build_vlm_multi_image_messages(
    frames_bytes: list[bytes],
    mime_type: str,
    text_prompt: str,
) -> list[dict[str, Any]]:
    """构建 OpenAI 兼容格式的多图多模态消息（grouped 策略用）。

    content 列表含多个 ``image_url`` 项（按帧顺序）+ 一个 ``text`` 项。
    部分 VLM 提供商不支持多图输入，调用方捕获异常后应降级为逐帧单图描述。
    """
    content: list[dict[str, Any]] = [
        {
            "type": "image_url",
            "image_url": {"url": build_image_data_url(fb, mime_type)},
        }
        for fb in frames_bytes
    ]
    content.append({"type": "text", "text": text_prompt})
    return [{"role": "user", "content": content}]


async def generate_vlm_text_with_fallback(
    vlm_client,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int,
    temperature: float,
    logger,
    vlm_model: str,
    log_context: dict[str, Any] | None = None,
) -> str:
    """兼容部分 VLM 提供商要求显式开启 thinking 的场景。

    Args:
        vlm_client: VLM 客户端。
        messages: 多模态消息列表。
        max_tokens: 生成 token 上限。
        temperature: 采样温度。
        logger: 日志器（重试时记录）。
        vlm_model: 模型名（日志上下文）。
        log_context: 附加日志键值，可空。

    Returns:
        VLM 生成文本；首次失败且错误含 enable_thinking 时自动开启重试，其余异常原样上抛。
    """
    try:
        return await vlm_client.generate_text(
            prompt=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as e:
        error_text = str(e)
        if "enable_thinking" not in error_text.lower():
            raise

        logger.info(
            "VLM描述重试并开启thinking",
            model=vlm_model,
            **(log_context or {}),
        )
        return await vlm_client.generate_text(
            prompt=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            enable_thinking=True,
        )

# 覆盖率滑窗窗口宽（激进归一后的字符数；12 字约一个短短语粒度）
_COVERAGE_WINDOW = 12
# 页级及格线：低于此值触发单页重试；重试后仍低于此值只标记不失败
_COVERAGE_PASS = 0.95


def hard_norm_text(text: str) -> str:
    """激进归一：连字折叠 + 变音分解 + 仅保留字母数字与汉字并小写。

    用于 VLM 转写覆盖率自检——把连字（ﬁ→fi）、变音（ä→a）、全/半角标点、
    空格与数字内空格等「写法变体」折叠掉，只比对内容本身。
    """
    import unicodedata

    lig = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬆ": "st"}
    t = text.replace("-\n", " ")
    for k, v in lig.items():
        t = t.replace(k, v)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return "".join(ch for ch in t if ch.isalnum() or "\u4e00" <= ch <= "\u9fff").lower()


def transcription_coverage(output: str, truth: str | None) -> float | None:
    """VLM 转写输出对页面真值的滑窗覆盖率（0.0~1.0；无真值返回 None）。

    真值窗口在输出中做顺序无关包含判定——输出阅读顺序与文字层不同（双栏/
    表格）不扣分；窗口跨公式/表格时可能因 LaTeX 形态差异未命中，属可容忍
    假阳性（及格线 0.95 已留余量）。

    Args:
        output: VLM 转写产出文本。
        truth: 页面真值（文字层/幻灯片文本）；None 返回 None。

    Returns:
        覆盖率浮点值；truth 为 None 或真值归一后过短（< 窗口宽）时返回 None。
    """
    if truth is None:
        return None
    n_out, n_truth = hard_norm_text(output), hard_norm_text(truth)
    if len(n_truth) < _COVERAGE_WINDOW:
        return None
    win, hits, total = _COVERAGE_WINDOW, 0, 0
    for j in range(0, max(len(n_truth) - win, 1), win):
        total += 1
        if n_truth[j:j + win] in n_out:
            hits += 1
    return hits / max(total, 1)

