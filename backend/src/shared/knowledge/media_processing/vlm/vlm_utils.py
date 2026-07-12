import base64
from typing import Any, Dict, List, Optional


def build_image_data_url(file_bytes: bytes, mime_type: str) -> str:
    """将图片二进制内容编码为 data URL。"""
    base64_data = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{base64_data}"


def build_vlm_image_messages(file_bytes: bytes, mime_type: str, text_prompt: str) -> List[Dict[str, Any]]:
    """构建 OpenAI 兼容格式的图片多模态消息。"""
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


async def generate_vlm_text_with_fallback(
    vlm_client,
    messages: List[Dict[str, Any]],
    *,
    max_tokens: int,
    temperature: float,
    logger,
    vlm_model: str,
    log_context: Optional[Dict[str, Any]] = None,
) -> str:
    """兼容部分 VLM 提供商要求显式开启 thinking 的场景。"""
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
