"""DeepDoc 解析引擎：统一入口，编排解析管道（加载→解析→版面分析→输出）。"""
from __future__ import annotations

import asyncio
from pathlib import Path

from novamind.engines.document.integrations.deepdoc.compat.upstream import (
    get_upstream_deepdoc_snapshot,
)
from novamind.engines.document.integrations.deepdoc.core.capabilities import (
    get_deepdoc_capabilities,
)
from novamind.engines.document.integrations.deepdoc.core.factory import DeepDocParserFactory
from novamind.engines.document.integrations.deepdoc.core.models import DeepDocParseResult
from novamind.engines.document.integrations.deepdoc.core.runtime_parser import DeepDocParser
from novamind.engines.document.integrations.deepdoc.diagnostics.dependencies import (
    get_deepdoc_runtime_report,
)
from novamind.engines.document.integrations.deepdoc.vision.model_manager import get_model_status
from novamind.engines.document.integrations.deepdoc.vision_runtime import (
    get_vision_health_status,
    run_vision_smoke_check,
)
from novamind.shared.logging import get_logger


class DeepDocEngine:
    """Standalone facade for the vendored deepdoc module."""

    def __init__(self, parser: DeepDocParser | None = None):
        """初始化运行时解析器（可注入实例，缺省自建）。"""
        self.parser = parser or DeepDocParser()

    @staticmethod
    def supported_extensions() -> set[str]:
        """支持的文件后缀全集（透传运行时解析器）。"""
        return DeepDocParser.supported_extensions()

    @staticmethod
    def describe_capabilities():
        """引擎能力描述（解析器目录/PDF 模式/vision 可用性），供注册层与前端。"""
        return get_deepdoc_capabilities()

    @staticmethod
    def runtime_dependencies():
        """运行时依赖明细（各包可导入性与版本）。"""
        return get_deepdoc_runtime_report()

    @staticmethod
    def vision_model_status():
        """视觉模型三组（ocr/layout/tsr）的下载状态。"""
        return get_model_status()

    @staticmethod
    def text_concat_model_status():
        """段落合并 xgb 模型状态。"""
        from novamind.engines.document.integrations.deepdoc.text_concat_model import (
            get_text_concat_model_status,
        )

        return get_text_concat_model_status()

    @staticmethod
    def vision_health_status():
        """视觉能力健康摘要（可执行布尔判定）。"""
        return get_vision_health_status()

    @staticmethod
    def vision_smoke_check():
        """视觉链路冒烟测试（真实加载 + 合成图推理）。"""
        return run_vision_smoke_check()

    @staticmethod
    def upstream_snapshot():
        """上游 ragflow vendor 快照信息（commit/文件清单，供对拍审计）。"""
        return get_upstream_deepdoc_snapshot()

    @staticmethod
    def download_vision_models(group: str | None = None):
        """按组下载视觉模型（ocr/layout/tsr，None 全量），返回逐组结果。

        Args:
            group: 模型组名（ocr/layout/tsr）；None 下载全集。

        Returns:
            下载目标目录 Path。
        """
        from novamind.engines.document.integrations.deepdoc.vision.model_manager import (
            download_model_group,
        )

        return download_model_group(group)

    @staticmethod
    def download_text_concat_model():
        """下载段落合并模型，返回终态状态。"""
        from novamind.engines.document.integrations.deepdoc.text_concat_model import (
            download_text_concat_model as download_text_concat_model_artifact,
        )

        return download_text_concat_model_artifact()

    @staticmethod
    def download_formula_model():
        """下载公式识别模型（含 INT8 量化），返回终态状态。"""
        from novamind.engines.document.integrations.deepdoc.formula_recognition import (
            download_formula_model as download_formula_model_artifact,
        )

        return download_formula_model_artifact()

    @classmethod
    def available_pdf_modes(cls) -> dict:
        """PDF 模式能力表（含逐模式 available/missing）。"""
        return dict(get_deepdoc_capabilities()["pdf_modes"])

    async def aparse_with_parser_id(
        self,
        *,
        file_type: str,
        parser_id: str | None = None,
        file_path: str | Path | None = None,
        file_bytes: bytes | None = None,
        parsing_config: dict | None = None,
        splitting_config: dict | None = None,
    ) -> DeepDocParseResult:
        """异步解析：按 parser_id（auto 时按后缀推断）选择 spec 执行。
        
        Raises:
            ValueError: parser_id 未知或文件类型无匹配 spec。
        """
        parser_spec = DeepDocParserFactory.resolve_parser_id(file_type, parser_id)
        parser, parser_defaults = DeepDocParserFactory.build_configs(file_type, parser_spec.parser_id)
        merged_parsing = {**parser_defaults, **(parsing_config or {})}
        _log = get_logger(__name__)
        _log.info(
            "DeepDoc aparse_with_parser_id 解析器选择",
            requested_parser_id=parser_id,
            resolved_parser_id=parser_spec.parser_id,
            parser_mode=parser_spec.mode,
            parser_available=parser_spec.available,
            merged_parsing_keys=list(merged_parsing.keys()),
            source="file_path" if file_path else "file_bytes",
        )
        if file_path is not None:
            result = await parser.parse(
                file_path,
                parsing_config=merged_parsing,
                splitting_config=splitting_config,
            )
        elif file_bytes is not None:
            result = await parser.parse_bytes(
                file_bytes,
                file_type=file_type,
                parsing_config=merged_parsing,
                splitting_config=splitting_config,
            )
        else:
            raise ValueError("Either file_path or file_bytes must be provided")
        result.metadata.setdefault("parser_id", parser_spec.parser_id)
        _log.info(
            "DeepDoc aparse_with_parser_id 解析完成",
            parser_id=parser_spec.parser_id,
            char_count=len(result.full_text),
            chunk_count=len(result.chunks),
        )
        return result

    def parse_file(self, file_path: str | Path, **kwargs) -> DeepDocParseResult:
        """同步解析本地文件（asyncio.run 桥接 aparse_with_parser_id）。

        Args:
            file_path: 文件路径。
            kwargs: 透传 parser.parse 的解析/切分配置。

        Returns:
            DeepDocParseResult。

        Raises:
            RuntimeError: 已在活动事件循环内调用（应改用 aparse_* 异步入口）。
        """
        return self._run_async(self.parser.parse(file_path, **kwargs))

    def parse_with_parser_id(self, **kwargs) -> DeepDocParseResult:
        """同步解析字节流：显式 parser_id 或按 file_type 推断 spec。"""
        return self._run_async(self.aparse_with_parser_id(**kwargs))

    @staticmethod
    def _run_async(awaitable):
        """事件循环桥：已有活循环时用独立线程跑，否则 asyncio.run。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        raise RuntimeError("DeepDocEngine.parse_* sync APIs cannot run inside an active event loop; use aparse_* instead")
