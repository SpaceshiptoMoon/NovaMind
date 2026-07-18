from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from novamind.shared.knowledge.integrations.deepdoc.core.capabilities import get_deepdoc_capabilities
from novamind.shared.knowledge.integrations.deepdoc.diagnostics.dependencies import get_deepdoc_runtime_report
from novamind.shared.knowledge.integrations.deepdoc.core.factory import DeepDocParserFactory
from novamind.shared.knowledge.integrations.deepdoc.core.models import DeepDocParseResult
from novamind.shared.knowledge.integrations.deepdoc.core.runtime_parser import DeepDocParser
from novamind.shared.knowledge.integrations.deepdoc.compat.upstream import get_upstream_deepdoc_snapshot
from novamind.shared.knowledge.integrations.deepdoc.logging_compat import get_logger
from novamind.shared.knowledge.integrations.deepdoc.vision.model_manager import get_model_status
from novamind.shared.knowledge.integrations.deepdoc.vision_runtime import (
    get_vision_health_status,
    run_vision_smoke_check,
)


class DeepDocEngine:
    """Standalone facade for the vendored deepdoc module."""

    def __init__(self, parser: Optional[DeepDocParser] = None):
        self.parser = parser or DeepDocParser()

    @staticmethod
    def supported_extensions() -> set[str]:
        return DeepDocParser.supported_extensions()

    @classmethod
    def can_parse(cls, file_type: str) -> bool:
        return file_type.lower().lstrip(".") in cls.supported_extensions()

    @staticmethod
    def describe_capabilities():
        return get_deepdoc_capabilities()

    @staticmethod
    def runtime_dependencies():
        return get_deepdoc_runtime_report()

    @staticmethod
    def vision_model_status():
        return get_model_status()

    @staticmethod
    def text_concat_model_status():
        from novamind.shared.knowledge.integrations.deepdoc.text_concat_model import get_text_concat_model_status

        return get_text_concat_model_status()

    @staticmethod
    def vision_health_status():
        return get_vision_health_status()

    @staticmethod
    def vision_smoke_check():
        return run_vision_smoke_check()

    @staticmethod
    def upstream_snapshot():
        return get_upstream_deepdoc_snapshot()

    @staticmethod
    def ensure_vision_model_group(group: str):
        from novamind.shared.knowledge.integrations.deepdoc.vision.model_manager import ensure_model_group_available

        return ensure_model_group_available(group)

    @staticmethod
    def download_vision_models(group: str | None = None):
        from novamind.shared.knowledge.integrations.deepdoc.vision.model_manager import download_model_group

        return download_model_group(group)

    @staticmethod
    def download_text_concat_model():
        from novamind.shared.knowledge.integrations.deepdoc.text_concat_model import download_text_concat_model as download_text_concat_model_artifact

        return download_text_concat_model_artifact()

    @classmethod
    def available_pdf_modes(cls) -> dict:
        return dict(get_deepdoc_capabilities()["pdf_modes"])

    @classmethod
    def supports_pdf_mode(cls, mode: str) -> bool:
        info = cls.available_pdf_modes().get(mode)
        return bool(info and info.get("available"))

    async def aparse_file(self, file_path: str | Path, **kwargs) -> DeepDocParseResult:
        return await self.parser.parse(file_path, **kwargs)

    async def aparse_bytes(self, file_bytes: bytes, *, file_type: str, **kwargs) -> DeepDocParseResult:
        return await self.parser.parse_bytes(file_bytes, file_type=file_type, **kwargs)

    async def aparse_with_parser_id(
        self,
        *,
        file_type: str,
        parser_id: str | None = None,
        file_path: str | Path | None = None,
        file_bytes: bytes | None = None,
        parsing_config: Optional[dict] = None,
        splitting_config: Optional[dict] = None,
    ) -> DeepDocParseResult:
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
        return self._run_async(self.aparse_file(file_path, **kwargs))

    def parse_bytes(self, file_bytes: bytes, *, file_type: str, **kwargs) -> DeepDocParseResult:
        return self._run_async(self.aparse_bytes(file_bytes, file_type=file_type, **kwargs))

    def parse_with_parser_id(self, **kwargs) -> DeepDocParseResult:
        return self._run_async(self.aparse_with_parser_id(**kwargs))

    @staticmethod
    def _run_async(awaitable):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        raise RuntimeError("DeepDocEngine.parse_* sync APIs cannot run inside an active event loop; use aparse_* instead")
