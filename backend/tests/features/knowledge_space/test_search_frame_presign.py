"""检索结果帧图预签名单元测试（search_service._presign_frame_urls）。

覆盖：frame_paths → frame_urls 写回、非 video hit 不动、单条失败跳过、
上限截断、非 dict hit 容错。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from novamind.features.knowledge_space.services import search_service as ss_module
from novamind.features.knowledge_space.services.search_service import SearchService

pytestmark = pytest.mark.unit


def _fake_minio(fail_paths: set[str] | None = None):
    fail_paths = fail_paths or set()

    async def get_file_url(bucket, object_name, expires=3600):
        if object_name in fail_paths:
            raise RuntimeError("presign boom")
        return f"https://signed/{bucket}/{object_name}"

    return SimpleNamespace(default_bucket="novamind-dev", get_file_url=get_file_url)


def _make_service() -> SearchService:
    """最小构造（构造函数只建 repository，传 AsyncMock session 即可）。"""
    from unittest.mock import MagicMock

    return SearchService(session=MagicMock(), es_client=MagicMock())


@pytest.mark.asyncio
async def test_frame_urls_written_for_video_hit(monkeypatch):
    hit = {
        "chunk_id": "1_0",
        "content": "描述",
        "metadata": {"frame_paths": ["a_frames/frame_0001.jpg", "a_frames/frame_0002.jpg"]},
    }
    monkeypatch.setattr(ss_module, "get_minio_client", AsyncMock(return_value=_fake_minio()))
    await _make_service()._presign_frame_urls([hit])
    assert hit["metadata"]["frame_urls"] == [
        "https://signed/novamind-dev/a_frames/frame_0001.jpg",
        "https://signed/novamind-dev/a_frames/frame_0002.jpg",
    ]


@pytest.mark.asyncio
async def test_text_hit_untouched(monkeypatch):
    hit = {"chunk_id": "1_1", "metadata": {"parser": "deepdoc"}}
    monkeypatch.setattr(ss_module, "get_minio_client", AsyncMock(return_value=_fake_minio()))
    await _make_service()._presign_frame_urls([hit])
    assert "frame_urls" not in hit["metadata"]


@pytest.mark.asyncio
async def test_failed_frame_skipped_others_kept(monkeypatch):
    hit = {
        "metadata": {"frame_paths": ["ok1.jpg", "boom.jpg", "ok2.jpg"]},
    }
    monkeypatch.setattr(
        ss_module, "get_minio_client", AsyncMock(return_value=_fake_minio(fail_paths={"boom.jpg"}))
    )
    await _make_service()._presign_frame_urls([hit])
    assert hit["metadata"]["frame_urls"] == [
        "https://signed/novamind-dev/ok1.jpg",
        "https://signed/novamind-dev/ok2.jpg",
    ]


@pytest.mark.asyncio
async def test_capped_at_max(monkeypatch):
    hit = {"metadata": {"frame_paths": [f"p_{i:02d}.jpg" for i in range(15)]}}
    monkeypatch.setattr(ss_module, "get_minio_client", AsyncMock(return_value=_fake_minio()))
    await _make_service()._presign_frame_urls([hit])
    assert len(hit["metadata"]["frame_urls"]) == SearchService._MAX_FRAME_URLS


@pytest.mark.asyncio
async def test_non_dict_and_bad_metadata_tolerated(monkeypatch):
    monkeypatch.setattr(ss_module, "get_minio_client", AsyncMock(return_value=_fake_minio()))
    # 不应抛异常：非 dict hit、metadata 非 dict 都跳过
    await _make_service()._presign_frame_urls(["oops", {"metadata": "not-a-dict"}, 42])
