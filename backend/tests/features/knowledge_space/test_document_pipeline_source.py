"""批1 c3/c4 回归：execute_document_pipeline 双参数派发 + 引擎 *_from_path 变体 + normalizer 超时修复。

背景：worker 下载 MinIO 原件改为流式落盘（download_document_to_file）后，
管道以 file_path 消费（视频透传/图像音频按需 read_bytes/文本直接复用），
execute_document_pipeline 的 file_content 与 file_path 互斥；
引擎层暴露 extract_frames_fixed_from_path / extract_frames_scene_from_path
（bytes 版委托路径版，行为零变化），video_normalizer 超时分支修复
未定义变量 input_path 的 NameError。
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.features.knowledge_space.models.document_task import TaskStatus
from novamind.features.knowledge_space.services.document_pipeline import (
    execute_document_pipeline,
)

pytestmark = pytest.mark.unit


def _patch_repos(ds_module, document):
    """给 execute_document_pipeline 换上内存 repo（doc/kb 各一）。"""
    doc_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=document))
    kb_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=SimpleNamespace(id=1)))
    ds_module.DocumentRepository = lambda s: doc_repo
    ds_module.KnowledgeBaseRepository = lambda s: kb_repo


def test_pipeline_rejects_both_and_neither_source():
    """file_content 与 file_path 都给/都缺 → ValueError（互斥守卫）。"""
    async def _run():
        with pytest.raises(ValueError, match="二选一"):
            await execute_document_pipeline(
                session=object(), document_id=1, kb_id=1, space_id=1, filename="a.mp4",
                file_content=b"x", file_path="/tmp/a.mp4",
            )
        with pytest.raises(ValueError, match="二选一"):
            await execute_document_pipeline(
                session=object(), document_id=1, kb_id=1, space_id=1, filename="a.mp4",
            )

    asyncio.run(_run())


def test_pipeline_video_branch_passes_file_path_through():
    """file_path 模式：视频分支把路径透传给 process_video_document，file_content 为 None。"""
    import novamind.features.knowledge_space.services.document_pipeline as ds_module
    import novamind.features.knowledge_space.services.media_processing as mp_module

    async def _run():
        document = SimpleNamespace(id=1, kb_id=1, space_id=1, file_type="mp4")
        _patch_repos(ds_module, document)
        task = SimpleNamespace(status=TaskStatus.PROCESSING, mark_processing=lambda: None)

        mock_video = AsyncMock()
        original = mp_module.process_video_document
        mp_module.process_video_document = mock_video
        try:
            await execute_document_pipeline(
                session=object(), document_id=1, kb_id=1, space_id=1,
                filename="demo.mp4", task=task,
                file_path="/tmp/downloads/demo.mp4",
            )
        finally:
            mp_module.process_video_document = original

        assert mock_video.await_count == 1
        kwargs = mock_video.await_args.kwargs
        assert kwargs.get("file_path") == "/tmp/downloads/demo.mp4"
        # bytes 版老契约：file_content 位置参数仍在（值为 None）
        assert mock_video.await_args.args[1] is None

    asyncio.run(_run())


def test_pipeline_video_branch_bytes_contract_unchanged():
    """file_content 模式回归：旧 bytes 调用路径行为不变（file_path=None）。"""
    import novamind.features.knowledge_space.services.document_pipeline as ds_module
    import novamind.features.knowledge_space.services.media_processing as mp_module

    async def _run():
        document = SimpleNamespace(id=1, kb_id=1, space_id=1, file_type="mp4")
        _patch_repos(ds_module, document)
        task = SimpleNamespace(status=TaskStatus.PROCESSING, mark_processing=lambda: None)

        mock_video = AsyncMock()
        original = mp_module.process_video_document
        mp_module.process_video_document = mock_video
        try:
            await execute_document_pipeline(
                session=object(), document_id=1, kb_id=1, space_id=1,
                filename="demo.mp4", task=task,
                file_content=b"\x00\x00\x00\x18ftypmp4",
            )
        finally:
            mp_module.process_video_document = original

        kwargs = mock_video.await_args.kwargs
        assert kwargs.get("file_path") is None
        assert mock_video.await_args.args[1] == b"\x00\x00\x00\x18ftypmp4"

    asyncio.run(_run())


def test_pipeline_audio_branch_reads_file_from_path():
    """file_path 模式：音频分支按需 read_bytes 后传整包给 process_audio_document。"""
    import novamind.features.knowledge_space.services.document_pipeline as ds_module
    import novamind.features.knowledge_space.services.media_processing as mp_module

    async def _run():
        tmp = Path(BACKEND_ROOT) / ".tmp_test_audio"
        tmp.write_bytes(b"ID3fake-audio-bytes")
        try:
            document = SimpleNamespace(id=1, kb_id=1, space_id=1, file_type="mp3")
            _patch_repos(ds_module, document)
            task = SimpleNamespace(status=TaskStatus.PROCESSING, mark_processing=lambda: None)

            mock_audio = AsyncMock()
            original = mp_module.process_audio_document
            mp_module.process_audio_document = mock_audio
            try:
                await execute_document_pipeline(
                    session=object(), document_id=1, kb_id=1, space_id=1,
                    filename="demo.mp3", task=task,
                    file_path=str(tmp),
                )
            finally:
                mp_module.process_audio_document = original

            assert mock_audio.await_count == 1
            assert mock_audio.await_args.args[1] == b"ID3fake-audio-bytes"
        finally:
            tmp.unlink(missing_ok=True)

    asyncio.run(_run())


def test_pipeline_text_branch_reuses_path_without_copy(monkeypatch):
    """file_path 模式：文本分支直接复用路径（不复制文件），文件生命周期归调用方。"""
    import novamind.features.knowledge_space.services.document_pipeline as ds_module

    async def _run():
        # 取消检查依赖 Redis——单测环境直接短路为「未取消」
        async def _no_cancel(document_id):
            return None
        monkeypatch.setattr(ds_module, "check_document_cancelled", _no_cancel)

        tmp = Path(BACKEND_ROOT) / ".tmp_test_text.txt"
        tmp.write_text("hello world")
        try:
            document = SimpleNamespace(
                id=1, kb_id=1, space_id=1, file_type="txt", uploader_id=1,
            )
            _patch_repos(ds_module, document)
            task = SimpleNamespace(
                status=TaskStatus.PROCESSING, mark_processing=lambda: None,
                start_step=lambda name: None,
                finish_step=lambda name, **kw: None,
                mark_completed=lambda result=None: None,
            )
            session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
            # 文本分支走 DocumentProcessor：mock 掉加载入口，验证收到的是同一路径
            calls = {}

            class FakeProcessor:
                async def parse_document_result(self, file_path, **kwargs):
                    calls["file_path"] = file_path
                    return SimpleNamespace(
                        full_text="hello world", chunks=[], metadata={}, tables=[], images=[],
                    )

            original_getter = ds_module._get_document_processor_static
            ds_module._get_document_processor_static = AsyncMock(return_value=FakeProcessor())
            original_ctx = ds_module.load_pipeline_context
            ds_module.load_pipeline_context = AsyncMock(return_value=SimpleNamespace(
                pipeline_config={}, space_owner_id=1, embedding_model_name="m",
                embedding_config={},
            ))
            original_tail = ds_module.run_post_parse_tail
            ds_module.run_post_parse_tail = AsyncMock(return_value={
                "chunk_count": 0, "total_tokens": 0,
            })
            original_persist = ds_module.persist_parsed_text
            ds_module.persist_parsed_text = AsyncMock()
            try:
                await execute_document_pipeline(
                    session=session, document_id=1, kb_id=1, space_id=1,
                    filename="demo.txt", task=task,
                    file_path=str(tmp),
                )
            finally:
                ds_module._get_document_processor_static = original_getter
                ds_module.load_pipeline_context = original_ctx
                ds_module.persist_parsed_text = original_persist
                ds_module.run_post_parse_tail = original_tail

            assert calls.get("file_path") == str(tmp)
            # 调用方文件未被管道删除（_owns_tmp_path=False）
            assert tmp.exists()
        finally:
            tmp.unlink(missing_ok=True)

    asyncio.run(_run())
