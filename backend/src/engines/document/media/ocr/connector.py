"""OCR 连接器：外部 OCR 统一入口（路由解析 + 协议分发）。

与 AsrConnector 同形态、两处有意差异：
- 凭证来自宿主注入的引擎配置而非 per-user 模型管理（模型类型白名单
  尚无 "ocr"），resolve_route 是同步纯函数（无凭证 IO）；
- 协议由「输入形态 + 任务」推导而非凭证记录：PDF 默认 openai
  responses（document_parsing 整本直传）；图片走 dashscope（multi_lan
  单图）；PDF + multi_lan 渲染页图后逐页识别。

失败语义（文件损坏永久性 / 请求失败瞬时性）归调用方按场景处理，
连接器不做场景策略。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from novamind.engines.document.media.ocr.qwen import (
    MIME_BY_EXT,
    DEFAULT_RENDER_DPI,
    OcrEngineConfig,
    OcrFileInvalidError,
    OcrRequestError,
    recognize_image_with_qwen_ocr,
    render_pdf_page_images,
)
from novamind.engines.document.media.ocr.blocks import OcrResult

logger = logging.getLogger(__name__)

SUPPORTED_OCR_TASKS = ("document_parsing", "multi_lan")


class OcrCredentialsMissingError(RuntimeError):
    """OCR 凭证缺失或配置非法（api_key/模型名为空、任务不在支持面）——配置错误。"""


@dataclass(frozen=True)
class OcrRoute:
    """一次 OCR 调用的完整路由。"""

    protocol: str  # openai（responses document_parsing）/ dashscope（multi_lan）
    model: str
    api_key: str | None = None
    base_url: str | None = None  # 按 protocol 取 openai_base_url / dashscope_base_url
    ocr_task: str = "multi_lan"  # document_parsing / multi_lan
    render_dpi: int = DEFAULT_RENDER_DPI  # 仅 dashscope + PDF 输入时消费


class OcrConnector:
    """OCR 连接器：YAML 配置驱动（宿主注入 OcrEngineConfig），无状态即用即建。"""

    def __init__(self, engine_config: OcrEngineConfig | None = None):
        """
        Args:
            engine_config: 宿主构造的引擎配置；None 时所有请求判凭证缺失
                （纯本地部署不注入即显式禁用外部 OCR）。
        """
        self._engine_config = engine_config

    def resolve_route(self, *, file_type: str, ocr_task: str | None = None) -> OcrRoute:
        """按输入形态 + 任务解析路由（同步纯函数，无 IO）。

        Args:
            file_type: 文件扩展名（大小写不敏感）。
            ocr_task: 显式任务；None 按输入形态自动（PDF→document_parsing，
                图片→multi_lan）。

        Raises:
            OcrCredentialsMissingError: 未注入配置、api_key/模型名空、
                显式任务不在支持面。
            OcrFileInvalidError: 扩展名不属于 PDF 或支持的图片类型。
        """
        if self._engine_config is None:
            raise OcrCredentialsMissingError("未注入 OCR 引擎配置，外部 OCR 不可用")
        config = self._engine_config
        if not config.api_key:
            raise OcrCredentialsMissingError(
                "OCR api_key 为空：请在配置中心 ocr.api_key 填入密钥"
                "（支持 ${ENV_VAR} 占位符引用 .env）"
            )
        if not config.model:
            raise OcrCredentialsMissingError("OCR 模型名为空：请配置 ocr.model")

        ext = (file_type or "").lower().lstrip(".")
        if ext == "pdf":
            task = ocr_task or "document_parsing"
            if task not in SUPPORTED_OCR_TASKS:
                raise OcrCredentialsMissingError(
                    f"OCR 任务「{task}」不受支持：仅支持 {' / '.join(SUPPORTED_OCR_TASKS)}"
                )
            if task == "document_parsing":
                return OcrRoute(
                    protocol="openai", model=config.model, api_key=config.api_key,
                    base_url=config.openai_base_url, ocr_task=task,
                )
            return OcrRoute(
                protocol="dashscope", model=config.model, api_key=config.api_key,
                base_url=config.dashscope_base_url, ocr_task=task,
                render_dpi=config.render_dpi,
            )
        if ext in MIME_BY_EXT:
            if ocr_task not in (None, "multi_lan"):
                raise OcrCredentialsMissingError(
                    f"图片输入仅支持 multi_lan 任务，不支持「{ocr_task}」"
                )
            return OcrRoute(
                protocol="dashscope", model=config.model, api_key=config.api_key,
                base_url=config.dashscope_base_url, ocr_task="multi_lan",
            )
        raise OcrFileInvalidError(
            f"外部 OCR 不支持「{ext}」类型：仅支持 PDF 与图片"
            f"（{'/'.join(MIME_BY_EXT)}）"
        )

    async def recognize(
        self, *, file_content: bytes, file_type: str, ocr_task: str | None = None
    ) -> OcrResult:
        """统一入口：路由解析 + 协议分发。

        Returns:
            归一化 OcrResult（MD 渲染调 result.render_markdown()）。

        Raises:
            同 resolve_route / 各通路实现。
        """
        route = self.resolve_route(file_type=file_type, ocr_task=ocr_task)
        return await self.recognize_with_route(
            route, file_content=file_content, file_type=file_type
        )

    async def recognize_with_route(
        self, route: OcrRoute, *, file_content: bytes, file_type: str
    ) -> OcrResult:
        """按已解析路由分发（两阶段入口，供调用方复用路由）。"""
        if route.protocol == "openai":
            return await self._recognize_document_parsing(route, file_content)
        return await self._recognize_multi_lan(route, file_content, file_type)

    async def _recognize_document_parsing(self, route: OcrRoute, file_content: bytes) -> OcrResult:
        """openai responses 整本 PDF 直传。"""
        from novamind.engines.document.media.ocr.qwen import parse_document_with_qwen_ocr

        config = self._require_config()
        result = await parse_document_with_qwen_ocr(file_content=file_content, config=config)
        return result

    async def _recognize_multi_lan(
        self, route: OcrRoute, file_content: bytes, file_type: str
    ) -> OcrResult:
        """multi_lan 分发：图片单次识别；PDF 渲页逐页识别（单页失败不整单失败）。"""
        from novamind.engines.document.media.ocr.qwen import recognize_image_with_qwen_ocr as _recognize

        config = self._require_config()
        ext = (file_type or "").lower().lstrip(".")
        mime = MIME_BY_EXT.get(ext)
        if mime is not None:
            return await _recognize(image_bytes=file_content, mime_type=mime, config=config)

        # 经模块属性取用：延迟绑定让测试可 monkeypatch 渲染与识别两个符号
        from novamind.engines.document.media.ocr import qwen as qwen_mod

        pages = await asyncio.to_thread(qwen_mod.render_pdf_page_images, file_content, route.render_dpi)
        merged_blocks = []
        raw_pages: list[str] = []
        failures = 0
        last_error: Exception | None = None
        for png_bytes, page_num in pages:
            try:
                page_result = await _recognize(
                    image_bytes=png_bytes, mime_type="image/png", config=config
                )
            except OcrRequestError as exc:
                # 失败方向安全：单页缺失优于整单失败；全败才上抛
                failures += 1
                last_error = exc
                logger.warning("OCR multi_lan 第 %d 页识别失败，跳过: %s", page_num + 1, exc)
                continue
            for block in page_result.blocks:
                merged_blocks.append(
                    type(block)(block_type=block.block_type, page_num=page_num,
                                bbox=block.bbox, text=block.text, markdown=block.markdown)
                )
            raw_pages.append(page_result.blocks[0].text if page_result.blocks else "")
        if failures == len(pages) and pages:
            raise OcrRequestError(f"OCR multi_lan 全部 {len(pages)} 页均失败: {last_error}")
        return OcrResult(
            blocks=merged_blocks,
            page_count=len(pages),
            model=route.model,
            protocol=route.protocol,
            raw_pages=raw_pages,
        )

    def _require_config(self) -> OcrEngineConfig:
        if self._engine_config is None:
            raise OcrCredentialsMissingError("未注入 OCR 引擎配置，外部 OCR 不可用")
        return self._engine_config
