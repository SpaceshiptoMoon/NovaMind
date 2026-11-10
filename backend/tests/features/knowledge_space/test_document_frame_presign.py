"""帧图预签名共享实现单元测试（DocumentQueryService.presign_frame_urls）。

检索端点与文档 chunks 端点共用同一实现，本文件覆盖实现本体：
frame_paths → frame_urls 写回、无帧分块不动、单帧失败跳过、全部失败不写键、
上限截断、非 dict / 非列表输入容错。检索侧的委托接线见
test_search_frame_presign.py。
"""
from types import SimpleNamespace

import pytest
from novamind.features.knowledge_space.services.document_query_service import (
    DocumentQueryService,
)

pytestmark = pytest.mark.unit


def _fake_minio(fail_paths: set[str] | None = None, fail_all: bool = False):
    fail_paths = fail_paths or set()
    calls: list[str] = []

    async def get_file_url(bucket, object_name, expires=3600):
        calls.append(object_name)
        if fail_all or object_name in fail_paths:
            raise RuntimeError("presign boom")
        return f"https://signed/{bucket}/{object_name}"

    return SimpleNamespace(default_bucket="novamind-dev", get_file_url=get_file_url, calls=calls)


@pytest.mark.asyncio
async def test_video_chunk_frame_paths_presigned_in_order():
    """video 分块：frame_paths 逐帧换签，写回 frame_urls 且保持帧序。"""
    metadata = {
        "start_time": 0.0,
        "end_time": 5.0,
        "frame_paths": ["v.mp4_frames/frame_0000.jpg", "v.mp4_frames/frame_0001.jpg"],
    }
    await DocumentQueryService.presign_frame_urls([metadata], _fake_minio())
    assert metadata["frame_urls"] == [
        "https://signed/novamind-dev/v.mp4_frames/frame_0000.jpg",
        "https://signed/novamind-dev/v.mp4_frames/frame_0001.jpg",
    ]
    # 源路径原样保留：frame_urls 是派生字段，不替换 frame_paths
    assert metadata["frame_paths"] == [
        "v.mp4_frames/frame_0000.jpg",
        "v.mp4_frames/frame_0001.jpg",
    ]


@pytest.mark.asyncio
async def test_chunks_without_frames_untouched_and_no_presign_call():
    """相邻正常场景：audio/text 分块无 frame_paths，不写键也不触发签名。"""
    audio_meta = {"start_time": 0.0, "end_time": 13.32, "confidence": 0.9}
    text_meta = {"page": 3, "section_title": "概述"}
    empty_frames_meta = {"frame_paths": []}
    client = _fake_minio()
    await DocumentQueryService.presign_frame_urls(
        [audio_meta, text_meta, empty_frames_meta], client
    )
    assert "frame_urls" not in audio_meta
    assert "frame_urls" not in text_meta
    assert "frame_urls" not in empty_frames_meta
    assert client.calls == []


@pytest.mark.asyncio
async def test_mixed_page_only_video_chunks_get_urls():
    """一页混排：只有带帧的分块被写回，其余分块互不影响。"""
    video_meta = {"frame_paths": ["a.jpg"]}
    audio_meta = {"start_time": 1.0}
    await DocumentQueryService.presign_frame_urls([audio_meta, video_meta], _fake_minio())
    assert video_meta["frame_urls"] == ["https://signed/novamind-dev/a.jpg"]
    assert "frame_urls" not in audio_meta


@pytest.mark.asyncio
async def test_failed_frame_skipped_others_kept():
    """单帧签名失败只跳过该帧，其余帧照常返回。"""
    metadata = {"frame_paths": ["ok1.jpg", "boom.jpg", "ok2.jpg"]}
    await DocumentQueryService.presign_frame_urls(
        [metadata], _fake_minio(fail_paths={"boom.jpg"})
    )
    assert metadata["frame_urls"] == [
        "https://signed/novamind-dev/ok1.jpg",
        "https://signed/novamind-dev/ok2.jpg",
    ]


@pytest.mark.asyncio
async def test_all_frames_failed_writes_no_key():
    """全部帧签名失败：不写 frame_urls（能力缺失而非空列表/错误结果），且不抛异常。"""
    metadata = {"frame_paths": ["a.jpg", "b.jpg"]}
    await DocumentQueryService.presign_frame_urls([metadata], _fake_minio(fail_all=True))
    assert "frame_urls" not in metadata


@pytest.mark.asyncio
async def test_capped_at_default_max():
    """帧数超过上限时按 MAX_FRAME_URLS 截断，取前 N 帧。"""
    paths = [f"p_{i:02d}.jpg" for i in range(DocumentQueryService.MAX_FRAME_URLS + 6)]
    metadata = {"frame_paths": paths}
    client = _fake_minio()
    await DocumentQueryService.presign_frame_urls([metadata], client)
    assert len(metadata["frame_urls"]) == DocumentQueryService.MAX_FRAME_URLS
    assert client.calls == paths[: DocumentQueryService.MAX_FRAME_URLS]


@pytest.mark.asyncio
async def test_explicit_max_urls_respected():
    """调用方显式传入的上限优先于默认值。"""
    metadata = {"frame_paths": ["a.jpg", "b.jpg", "c.jpg"]}
    await DocumentQueryService.presign_frame_urls([metadata], _fake_minio(), max_urls=2)
    assert metadata["frame_urls"] == [
        "https://signed/novamind-dev/a.jpg",
        "https://signed/novamind-dev/b.jpg",
    ]


@pytest.mark.asyncio
async def test_non_dict_and_non_list_inputs_tolerated():
    """脏数据容错：metadata 为 None/非 dict、frame_paths 非列表，一律跳过不抛。"""
    string_frames_meta = {"frame_paths": "not-a-list.jpg"}
    client = _fake_minio()
    await DocumentQueryService.presign_frame_urls(
        [None, "oops", 42, string_frames_meta], client
    )
    # 字符串若被当序列切片会按字符逐个签名，必须整体跳过
    assert "frame_urls" not in string_frames_meta
    assert client.calls == []
