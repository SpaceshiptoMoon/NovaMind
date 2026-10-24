"""qwen3.5-ocr 客户端层：OpenAI responses 与 DashScope 双通路归一。

两条通路（协议由调用方经路由决定，本模块只管通路实现与归一）：
- document_parsing：OpenAI 兼容 responses API，base64 PDF input_file 直传，
  返回版面 layouts（块类型/坐标/页码/markdownContent）——信息最全；
- multi_lan：DashScope MultiModalConversation 单图识别，返回纯文本。

并发语义（批次 6.3）：api_key 恒经 ``MultiModalConversation.call(api_key=...)``
per-call 传递，不依赖全局态；base_http_api_url 是 SDK 唯一的进程级全局且
无 per-call 透传——SDK 默认值与本模块标准百炼地址恒相同，因此标准场景
不再每次 configure 写全局（与 ASR Paraformer 并发的互踩窗口根除）；仅当
配置了非默认私有化地址时才写全局并记 warning（该场景与 ASR 并发仍有
互踩窗口，属 SDK 限制）。
"""
from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from typing import Any

from novamind.engines.document.media.ocr.blocks import (
    OcrBlock,
    OcrResult,
    bbox_from_quad,
)

logger = logging.getLogger(__name__)

# PDF 渲页默认 DPI。300dpi 相比 200dpi 对扫描件公式识别提升显著
# （范数 ||·|| 误识率大幅下降），降档只能省内存不应默认牺牲精度。
DEFAULT_RENDER_DPI = 300


class OcrFileInvalidError(RuntimeError):
    """PDF/图片损坏、加密或格式不支持（永久性，重试不可能成功）。"""


class OcrRequestError(RuntimeError):
    """OCR 服务调用失败（网络/超时/非 2xx/响应畸形），瞬时性可重试。"""


@dataclass(frozen=True)
class OcrEngineConfig:
    """引擎层 OCR 配置（宿主从 YAML 构造注入；引擎不读 setting）。"""

    api_key: str = ""
    model: str = "qwen3.5-ocr"
    openai_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    render_dpi: int = DEFAULT_RENDER_DPI
    timeout: int = 120


# multi_lan 单图通路支持的图片 MIME（扩展名 → MIME）
MIME_BY_EXT: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "bmp": "image/bmp",
}


def render_pdf_page_images(file_content: bytes, dpi: int = DEFAULT_RENDER_DPI) -> list[tuple[bytes, int]]:
    """PDF 字节逐页渲染为 PNG（同步，调用方负责 to_thread 隔离）。

    Args:
        file_content: PDF 文件字节。
        dpi: 渲染分辨率（300dpi 对公式识别显著优于 200dpi）。

    Returns:
        [(png_bytes, page_num)] 列表，page_num 0-based 按文档页序。

    Raises:
        OcrFileInvalidError: 文件损坏、加密或非 PDF。
    """
    import fitz

    try:
        doc = fitz.open(stream=file_content, filetype="pdf")
    except Exception as exc:
        raise OcrFileInvalidError(f"PDF 打开失败（损坏或加密）: {exc}") from exc
    pages: list[tuple[bytes, int]] = []
    try:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            pages.append((pix.tobytes("png"), i))
    finally:
        doc.close()
    return pages


def _extract_ocr_result(payload: dict[str, Any]) -> dict[str, Any]:
    """从 responses 响应 dict 中防御性提取 ocr_result。

    ocr_result 是端点扩展字段（非 SDK 标准类型），不依赖强类型访问；
    遍历 output → content 找到第一个含 ocr_result 的元素。
    """
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and isinstance(content.get("ocr_result"), dict):
                return content["ocr_result"]
    raise OcrRequestError("OCR 响应中未找到 ocr_result 字段（端点契约漂移或任务不支持）")


def _normalize_layouts(ocr_result: dict[str, Any]) -> list[OcrBlock]:
    """document_parsing 的 layouts 列表归一为 OcrBlock 列表。

    清洗规则：type 白名单外归 text；pageNum 不可解析或负值钳 0；
    markdownContent 优先、text 兜底；双空块丢弃（空坐标不丢块）。
    """
    blocks: list[OcrBlock] = []
    for layout in ocr_result.get("layouts") or []:
        if not isinstance(layout, dict):
            continue
        block_type = layout.get("type")
        if block_type not in ("title", "text", "formula"):
            block_type = "text"
        try:
            page_num = int(layout.get("pageNum") or 0)
        except (TypeError, ValueError):
            page_num = 0
        page_num = max(page_num, 0)
        markdown = (layout.get("markdownContent") or "").strip()
        text = (layout.get("text") or "").strip()
        if not markdown and not text:
            continue
        blocks.append(
            OcrBlock(
                block_type=block_type,
                page_num=page_num,
                bbox=bbox_from_quad(layout.get("pos")),
                text=text,
                markdown=markdown,
            )
        )
    return blocks


async def parse_document_with_qwen_ocr(*, file_content: bytes, config: OcrEngineConfig) -> OcrResult:
    """document_parsing 通路：OpenAI responses API 整本 PDF 直传。

    Args:
        file_content: PDF 文件字节（base64 后整体上传，单请求上限由服务端约束）。
        config: 引擎配置（api_key/openai_base_url/model/timeout）。

    Returns:
        归一化 OcrResult（blocks 带版面结构；MD 渲染用 render_markdown()）。

    Raises:
        OcrRequestError: 网络失败、超时、非 2xx、响应缺 ocr_result。
    """
    from openai import OpenAI

    b64 = base64.b64encode(file_content).decode("ascii")
    client = OpenAI(
        api_key=config.api_key,
        base_url=config.openai_base_url,
        timeout=config.timeout,
    )

    def _call() -> dict[str, Any]:
        response = client.responses.create(
            model=config.model,
            input=[{
                "role": "user",
                "content": [{
                    "type": "input_file",
                    "file_data": f"data:application/pdf;base64,{b64}",
                }],
            }],
            extra_body={"ocr_options": {"task": "document_parsing"}},
        )
        return response.model_dump()

    try:
        payload = await asyncio.to_thread(_call)
    except OcrRequestError:
        raise
    except Exception as exc:
        raise OcrRequestError(f"OCR document_parsing 请求失败: {exc}") from exc

    ocr_result = _extract_ocr_result(payload)
    blocks = _normalize_layouts(ocr_result)
    page_count = max((b.page_num for b in blocks), default=-1) + 1
    return OcrResult(blocks=blocks, page_count=page_count, model=config.model, protocol="openai")


def _extract_multi_lan_text(output: Any) -> str:
    """DashScope multi_lan 响应提取纯文本：收集所有 text 字段拼接。"""
    parts: list[str] = []
    try:
        choices = output["choices"]
        content = choices[0]["message"].content
        for piece in content:
            if isinstance(piece, dict) and piece.get("text"):
                parts.append(piece["text"])
    except (KeyError, IndexError, AttributeError, TypeError):
        text = str(output).strip()
        logger.warning("multi_lan 响应结构异常，降级为字符串输出: %.200s", text)
        return text
    return "\n".join(p for p in (part.strip() for part in parts) if p)


async def recognize_image_with_qwen_ocr(
    *, image_bytes: bytes, mime_type: str, config: OcrEngineConfig
) -> OcrResult:
    """multi_lan 通路：DashScope MultiModalConversation 单图识别。

    Args:
        image_bytes: 图片字节。
        mime_type: 图片 MIME 类型。
        config: 引擎配置（api_key/dashscope_base_url/model/timeout）。

    Returns:
        归一化 OcrResult（单 text 块；无版面结构）。

    Raises:
        OcrRequestError: SDK 调用失败或响应非成功状态。
    """
    from novamind.engines.document.media.vlm import build_image_data_url
    from novamind.shared.ai_models.asr.dashscope_client import configure_dashscope

    def _call() -> str:
        import dashscope
        from dashscope import MultiModalConversation

        # api_key 恒 per-call 传递；base url 仅在偏离 SDK 默认（私有化部署）时
        # 写全局——标准百炼场景与 ASR 并发的全局互踩窗口由此根除（批次 6.3）
        if config.dashscope_base_url.rstrip("/") != "https://dashscope.aliyuncs.com/api/v1":
            configure_dashscope(config.api_key, config.dashscope_base_url)
            logger.warning(
                "OCR 使用非默认 DashScope 地址（私有化部署），base url 为进程级全局，"
                "与 ASR Paraformer 并发时存在互踩窗口"
            )
        response = MultiModalConversation.call(
            api_key=config.api_key or None,
            model=config.model,
            messages=[{
                "role": "user",
                "content": [{
                    "image": build_image_data_url(image_bytes, mime_type),
                    "min_pixels": 3072,
                    "max_pixels": 8388608,
                    "enable_rotate": False,
                }],
            }],
            ocr_options={"task": "multi_lan"},
            timeout=config.timeout,
        )
        if getattr(response, "status_code", None) not in (None, 200):
            raise OcrRequestError(
                f"OCR multi_lan 请求失败: [{response.status_code}] {response.message}"
            )
        return _extract_multi_lan_text(response.output)

    try:
        text = await asyncio.to_thread(_call)
    except OcrRequestError:
        raise
    except Exception as exc:
        raise OcrRequestError(f"OCR multi_lan 请求失败: {exc}") from exc

    block = OcrBlock(block_type="text", page_num=0, text=text)
    return OcrResult(
        blocks=[block], page_count=1, model=config.model, protocol="dashscope", raw_pages=[text]
    )
