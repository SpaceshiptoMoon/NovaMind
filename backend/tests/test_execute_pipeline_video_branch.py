"""Regression test for the video branch of DocumentService.execute_document_pipeline.

回归背景：document_service.py 视频分支曾存在 `returnrain`（单个 NAME token，非 `return`），
导致 `process_video_document` 完成 commit 后立刻抛 NameError，视频处理 100% 必崩。
原视频测试直接调用 process_video_document 而绕过 execute_document_pipeline，使该 bug 长期隐藏。
本测试直接驱动 execute_document_pipeline 的视频分支，确保其正常返回、不抛 NameError。
"""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import novamind.features.knowledge_space.services.document_service as ds_module
from novamind.features.knowledge_space.services.document_service import DocumentService


def test_execute_pipeline_video_branch_returns_cleanly():
    """视频分支应调用 process_video_document 后正常返回，不抛 NameError。"""
    async def _run():
        session = object()

        # document.file_type = "mp4" 命中 VIDEO_FILE_TYPES 分支
        document = SimpleNamespace(id=1, kb_id=1, space_id=1, file_type="mp4")
        kb = SimpleNamespace(id=1)

        doc_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=document))
        kb_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=kb))
        ds_module.DocumentRepository = lambda s: doc_repo
        ds_module.KnowledgeBaseRepository = lambda s: kb_repo

        # 提供一个已处于 PROCESSING 的 task，避免 mark_processing 副作用
        task = SimpleNamespace(status=SimpleNamespace(value=1), mark_processing=lambda: None)

        # mock 视频处理函数（分支内 from ... import 取到的对象）
        process_video_document = AsyncMock()
        import novamind.features.knowledge_space.services.media_processing as mp_module
        original = mp_module.process_video_document
        mp_module.process_video_document = process_video_document
        try:
            # 不应抛异常（修复前此处抛 NameError）
            await DocumentService.execute_document_pipeline(
                session=session,
                document_id=1,
                kb_id=1,
                space_id=1,
                file_content=b"\x00\x00\x00\x18ftypmp4",
                filename="demo.mp4",
                task=task,
            )
        finally:
            mp_module.process_video_document = original

        # 视频处理函数确被调用
        assert process_video_document.await_count == 1

    asyncio.run(_run())