"""视频入库 RAG 全流程修复回归测试（B1/B2/B3+B4/B5/B6/B9/B10/B12）。

覆盖本轮修复的 8 个视频管道 bug，均为单元级复现原失败模式：

- B1+B6 ``_build_es_chunks``：frame_paths 改 Dict[int,str] 后抽帧空洞不错位；
  VIDEO chunk image_url 取首帧 path，IMAGE chunk 维持 media_url。
- B2 ``describe_grouped``：全组配额失败时 quota_failures 累计真实值，不再硬编码 0。
- B3+B4 ``_split_line_aware`` / ``_split_md_text`` recursive：line_aware 扩展到 recursive，
  超长锚点行不被切分家。
- B5 ``MinioClient.delete_objects_by_prefix``：递归 list+remove 清前缀。
- B9 ``describe_single``：有界并发（Semaphore+gather）保序、in-flight ≤ concurrency。
- B10 ``process_video_document``：vlm_model 改读嵌套 video_config，留空抛错、不回退用户默认、
  不串用 image 的 vlm_model。
- B12 ``process_video_document``：帧上传后立即持久化 storage["frames"]，tail 失败时帧已落库。
"""

import asyncio
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.exceptions import DocumentProcessingError
from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.services import document_pipeline, media_processing
from novamind.engines.document.media.video import frame_description as fd
from novamind.engines.document.media.video.frame_description import (
    AllFrameDescriptionsFailedError,
    describe_grouped,
    describe_single,
)

pytestmark = pytest.mark.unit


def _silent_logger() -> SimpleNamespace:
    return SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        debug=lambda *a, **k: None,
    )


def _make_video_document() -> SimpleNamespace:
    return SimpleNamespace(
        id=71,
        space_id=1,
        kb_id=1,
        file_hash="h",
        filename="v.mp4",
        file_type="mp4",
        storage={"minio_object_name": "obj"},
        uploader_id=1,
    )


# ---------------------------------------------------------------------------
# B1 + B6：frame_paths Dict 映射 + image_url 取首帧
# ---------------------------------------------------------------------------


def test_build_es_chunks_frame_paths_dict_no_misalign_on_hole():
    """B1：抽帧空洞（frame_idx 2 缺失）时，dict 映射让 chunk 按真实 frame_idx 取到正确帧，
    不错位、不丢失。B6：VIDEO chunk image_url 取首帧 path 而非视频文件。"""
    document = _make_video_document()
    # frame_idx 2 解码失败未上传 → 空洞；frame_idx 3 正常
    frame_paths = {
        0: "obj_frames/frame_0000.jpg",
        1: "obj_frames/frame_0001.jpg",
        3: "obj_frames/frame_0003.jpg",
    }
    chunk_items = [("[00:00:09#3] 描述", {"frame_indices": [3], "start_time": 9.0, "end_time": 12.0})]
    chunks = document_pipeline._build_es_chunks(
        document, chunk_items, ChunkType.VIDEO, frame_paths=frame_paths
    )
    # 取到 frame_idx=3 的真实路径，不是位置 3（越界丢弃）也不是位置错位
    assert chunks[0]["metadata"]["frame_paths"] == ["obj_frames/frame_0003.jpg"]
    # B6：image_url 指向首帧帧图，而非视频文件 obj
    assert chunks[0]["image_url"] == "obj_frames/frame_0003.jpg"
    assert chunks[0]["media_url"] == "obj"


def test_build_es_chunks_image_url_is_media_url_for_image():
    """B6：IMAGE 模态 chunk image_url 维持 media_url（图片文件本身），不带 frame_paths。"""
    document = SimpleNamespace(
        id=72, space_id=1, kb_id=1, file_hash="h", filename="i.png", file_type="png",
        storage={"minio_object_name": "img.png"}, uploader_id=1,
    )
    chunks = document_pipeline._build_es_chunks(document, [("描述", {})], ChunkType.IMAGE)
    assert chunks[0]["image_url"] == "img.png"
    assert "frame_paths" not in chunks[0]["metadata"]


def test_build_es_chunks_video_no_frames_image_url_empty():
    """B6：VIDEO chunk 无 frame_indices 时 image_url 空串，不误导指向视频文件。"""
    document = _make_video_document()
    chunks = document_pipeline._build_es_chunks(
        document, [("描述", {})], ChunkType.VIDEO, frame_paths={0: "obj_frames/frame_0000.jpg"}
    )
    assert chunks[0]["image_url"] == ""


# ---------------------------------------------------------------------------
# B2：grouped 全组配额失败时 quota_failures 累计
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grouped_quota_failures_accumulated(monkeypatch):
    """B2：所有组主多图调用配额失败 + single 回退也全配额失败时，
    AllFrameDescriptionsFailedError.quota_failures == total_frames，
    使 vlm_skip_on_quota_error 能正确触发占位降级。"""
    monkeypatch.setattr(fd, "generate_vlm_text_with_fallback", _raising_vlm_call)
    monkeypatch.setattr(fd, "build_vlm_image_messages", lambda b, mt, p: [{"role": "user", "content": "x"}])
    monkeypatch.setattr(fd, "build_vlm_multi_image_messages", lambda bs, mt, p: [{"role": "user", "content": "x"}])

    frames = [(b"f", float(i), i) for i in range(6)]  # 6 帧，group_size=3 → 2 组

    with pytest.raises(AllFrameDescriptionsFailedError) as ei:
        await describe_grouped(
            frames, 3, object(), "prompt",
            logger=_silent_logger(),  # 测试环境未配 structlog，用接受 **kwargs 的 silent logger
            is_quota_error=lambda exc: True,
            concurrency=1,  # 串行便于确定性
        )
    assert ei.value.total_frames == 6
    assert ei.value.quota_failures == 6  # 原硬编码 0 → 现累计真实值


async def _raising_vlm_call(*args, **kwargs):
    raise RuntimeError("quota exceeded")


# ---------------------------------------------------------------------------
# B3 + B4：line_aware 扩展到 recursive，超长锚点行不被切分家
# ---------------------------------------------------------------------------


def test_split_line_aware_preserves_anchors():
    """B3/B4 helper：超长锚点行（>chunk_size）按行整行成块，锚点 [HH:MM:SS#idx] 完整保留，
    不被 recursive 分隔符层级切到行内导致锚点分家。"""
    long_desc = "x" * 600
    text = f"[00:00:05#3] {long_desc}\n\n[00:00:10#4] short"
    chunks = media_processing._split_line_aware(text, chunk_size=200, chunk_overlap=0)
    assert len(chunks) >= 2
    # 两个锚点均完整出现在某 chunk 中
    joined = "\n".join(chunks)
    assert "[00:00:05#3]" in joined
    assert "[00:00:10#4]" in joined
    # 不出现被截断的锚点（如 "[00:00:05#3" 后无 ]）
    assert re.search(r"\[00:00:05#3[^\]]", joined) is None


@pytest.mark.asyncio
async def test_split_md_text_recursive_line_aware_honored():
    """B4：recursive 分支 line_aware=True 时走行边界切分（原忽略 line_aware）。"""
    long_desc = "x" * 600
    text = f"[00:00:05#3] {long_desc}\n\n[00:00:10#4] short"
    items = await media_processing._split_md_text(
        text, strategy="recursive", line_aware=True, chunk_size=200, chunk_overlap=0
    )
    anchors: list[str] = []
    for chunk_text, _ in items:
        anchors.extend(re.findall(r"\[00:00:\d{2}#\d+\]", chunk_text))
    assert "[00:00:05#3]" in anchors
    assert "[00:00:10#4]" in anchors


# ---------------------------------------------------------------------------
# B5：MinioClient.delete_objects_by_prefix 递归清理
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_objects_by_prefix_lists_and_removes():
    """B5：delete_objects_by_prefix 递归列出前缀下对象并逐个删除，返回删除数。"""
    from novamind.shared.storage.minio_client import MinioClient

    class _FakeObj:
        def __init__(self, name: str) -> None:
            self.object_name = name

    removed: list[str] = []

    class _FakeMinio:
        def list_objects(self, bucket, prefix, recursive=False):
            return [_FakeObj("obj_frames/frame_0000.jpg"), _FakeObj("obj_frames/frame_0003.jpg")]

        def remove_object(self, bucket, name):
            removed.append(name)

    client = MinioClient.__new__(MinioClient)
    client.client = _FakeMinio()  # type: ignore[attr-defined]

    count = await client.delete_objects_by_prefix("bucket", "obj_frames/")
    assert count == 2
    assert removed == ["obj_frames/frame_0000.jpg", "obj_frames/frame_0003.jpg"]


# ---------------------------------------------------------------------------
# B9：describe_single 有界并发保序
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_single_bounded_concurrency(monkeypatch):
    """B9：concurrency=4 时 VLM 同时 in-flight ≤4，结果按 frame_idx 保序。"""
    inflight = {"n": 0, "max": 0}

    async def fake_gen(*args, **kwargs):
        inflight["n"] += 1
        inflight["max"] = max(inflight["max"], inflight["n"])
        await asyncio.sleep(0.02)
        inflight["n"] -= 1
        return "desc"

    monkeypatch.setattr(fd, "generate_vlm_text_with_fallback", fake_gen)
    monkeypatch.setattr(fd, "build_vlm_image_messages", lambda b, mt, p: [{"role": "user", "content": "x"}])

    frames = [(b"f", float(i), i) for i in range(12)]
    res = await describe_single(frames, object(), "prompt", concurrency=4, cancel_every=1)

    assert len(res) == 12
    assert [r[2] for r in res] == list(range(12))  # 保序
    assert inflight["max"] <= 4  # 有界
    assert inflight["max"] >= 2  # 确实并发（非串行=1）


# ---------------------------------------------------------------------------
# B10：vlm_model 改读嵌套 video_config，留空抛错不兜底
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1

    async def begin_nested(self):
        return self


class _FakeMinio:
    async def upload_file(self, object_name, data, content_type):
        return None


@pytest.mark.asyncio
async def test_video_vlm_model_empty_raises_no_fallback(monkeypatch):
    """B10：video_config 无 vlm_model、image 有 vlm_model 时，视频路径读嵌套 video_config 得空，
    抛 DocumentProcessingError——不串用 image 的 vlm_model、不回退用户默认。"""
    document = _make_video_document()
    ctx = SimpleNamespace(
        pipeline_config={
            "parsing": {
                "video": {"strategy": "simple"},  # 无 vlm_model
                "image": {"strategy": "vlm", "vlm_model": "img-vlm"},  # 图片有，不应串到视频
            }
        },
        embedding_config={"model": "emb", "dimension": 8},
    )

    async def fake_load(session, doc, task):
        return ctx

    async def fake_cancel(doc_id):
        return None

    async def fake_extract(content, interval, maxf):
        return [(b"f", 0.0, 0)]

    async def fake_get_minio(cls):
        return _FakeMinio()

    monkeypatch.setattr(media_processing, "load_pipeline_context", fake_load)
    monkeypatch.setattr(media_processing, "_check_document_cancelled", fake_cancel)
    monkeypatch.setattr(media_processing, "extract_frames_fixed", fake_extract)
    monkeypatch.setattr(
        "novamind.shared.storage.client_factory.ClientFactory.get_minio_client",
        classmethod(fake_get_minio),
    )

    # model_config_port 有 get_user_default_model_name（返回默认 VLM），但不应被回退使用
    class _MCSWithDefault:
        async def get_user_default_model_name(self, user_id, model_type):
            return "default-vlm"

        async def get_vlm_client_by_model(self, user_id, model):
            raise AssertionError("不应到达：vlm_model 留空应先抛错")

    session = _FakeSession()
    with pytest.raises(DocumentProcessingError, match="VLM 模型"):
        await media_processing.process_video_document(
            document=document,
            file_content=b"fake",
            session=session,
            logger=_silent_logger(),
            task=None,
            model_config_port=_MCSWithDefault(),
        )


# ---------------------------------------------------------------------------
# B12：帧上传后立即持久化 storage["frames"]，tail 失败时帧已落库
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_storage_frames_persisted_before_tail(monkeypatch):
    """B12：_run_post_parse_tail 抛错时，storage["frames"] 已在帧上传后写入并 commit，
    帧可追踪（配合 B5 清理避免孤儿）。"""
    document = _make_video_document()
    document.storage = {"minio_object_name": "obj"}
    ctx = SimpleNamespace(
        pipeline_config={"parsing": {"video": {"strategy": "simple", "vlm_model": "v-vlm"}}},
        embedding_config={"model": "emb", "dimension": 8},
    )

    async def fake_load(session, doc, task):
        return ctx

    async def fake_cancel(doc_id):
        return None

    async def fake_extract(content, interval, maxf):
        return [(b"f", 0.0, 0), (b"f", 5.0, 1)]

    async def fake_get_minio(cls):
        return _FakeMinio()

    async def fake_describe_single(frames, vlm_client, prompt, **kw):
        return [("desc", ts, idx) for _, ts, idx in frames]

    async def fake_persist(document, text, session, logger):
        return None

    async def fake_tail(**kw):
        raise RuntimeError("tail boom")

    monkeypatch.setattr(media_processing, "load_pipeline_context", fake_load)
    monkeypatch.setattr(media_processing, "_check_document_cancelled", fake_cancel)
    monkeypatch.setattr(media_processing, "extract_frames_fixed", fake_extract)
    monkeypatch.setattr(
        "novamind.shared.storage.client_factory.ClientFactory.get_minio_client",
        classmethod(fake_get_minio),
    )
    monkeypatch.setattr(media_processing, "describe_single", fake_describe_single)
    monkeypatch.setattr(media_processing, "persist_parsed_text", fake_persist)
    monkeypatch.setattr(media_processing, "_run_post_parse_tail", fake_tail)
    monkeypatch.setattr(
        "novamind.shared.prompts.templates.PromptManager.get_template", lambda name: "prompt"
    )

    class _MCS:
        async def get_vlm_client_by_model(self, user_id, model):
            return object()

    session = _FakeSession()
    with pytest.raises(RuntimeError, match="tail boom"):
        await media_processing.process_video_document(
            document=document,
            file_content=b"fake",
            session=session,
            logger=_silent_logger(),
            task=None,
            model_config_port=_MCS(),
        )

    # 帧已在 tail 之前持久化（按 frame_idx 升序的非空 path 列表）
    assert document.storage.get("frames") == [
        "obj_frames/frame_0000.jpg",
        "obj_frames/frame_0001.jpg",
    ]
    # tail 之前至少 commit 过一次（帧上传后的即时持久化）
    assert session.commit_calls >= 1


# ---------------------------------------------------------------------------
# B9 配置来源：vlm_concurrency 由 YAML 配置控制，非每知识库 VideoParsingConfig
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_video_vlm_concurrency_read_from_yaml_config(monkeypatch):
    """B9 配置来源：并发数读自 YAML knowledge_base.parsing.video_vlm_concurrency，
    不再从每知识库 VideoParsingConfig 读取。monkeypatch 全局 config 返回 7，
    断言传入 describe_single 的 concurrency==7。"""
    document = _make_video_document()
    document.storage = {"minio_object_name": "obj"}
    ctx = SimpleNamespace(
        pipeline_config={"parsing": {"video": {"strategy": "simple", "vlm_model": "v-vlm"}}},
        embedding_config={"model": "emb", "dimension": 8},
    )

    captured: dict = {}

    async def fake_load(session, doc, task):
        return ctx

    async def fake_cancel(doc_id):
        return None

    async def fake_extract(content, interval, maxf):
        return [(b"f", 0.0, 0)]

    async def fake_get_minio(cls):
        return _FakeMinio()

    async def fake_describe_single(frames, vlm_client, prompt, **kw):
        captured["concurrency"] = kw.get("concurrency")
        return [("desc", ts, idx) for _, ts, idx in frames]

    async def fake_persist(document, text, session, logger):
        return None

    async def fake_tail(**kw):
        return {"chunk_count": 1}

    # 全局 YAML config 返回 video_vlm_concurrency=7
    fake_app_config = SimpleNamespace(
        knowledge_base=SimpleNamespace(
            parsing=SimpleNamespace(video_vlm_concurrency=7),
        ),
    )

    monkeypatch.setattr(media_processing, "load_pipeline_context", fake_load)
    monkeypatch.setattr(media_processing, "_check_document_cancelled", fake_cancel)
    monkeypatch.setattr(media_processing, "extract_frames_fixed", fake_extract)
    monkeypatch.setattr(
        "novamind.shared.storage.client_factory.ClientFactory.get_minio_client",
        classmethod(fake_get_minio),
    )
    monkeypatch.setattr(media_processing, "describe_single", fake_describe_single)
    monkeypatch.setattr(media_processing, "persist_parsed_text", fake_persist)
    monkeypatch.setattr(media_processing, "_run_post_parse_tail", fake_tail)
    monkeypatch.setattr(
        "novamind.shared.prompts.templates.PromptManager.get_template", lambda name: "prompt"
    )
    monkeypatch.setattr("novamind.setting.yaml_config.get_config", lambda: fake_app_config)

    class _MCS:
        async def get_vlm_client_by_model(self, user_id, model):
            return object()

    session = _FakeSession()
    await media_processing.process_video_document(
        document=document,
        file_content=b"fake",
        session=session,
        logger=_silent_logger(),
        task=None,
        model_config_port=_MCS(),
    )

    assert captured["concurrency"] == 7  # 来自 YAML config，非 VideoParsingConfig 默认 4


@pytest.mark.asyncio
async def test_video_vlm_concurrency_clamped_to_range(monkeypatch):
    """B9 配置来源：YAML 越界值被 clamp 到 [1,20]（防止误配 0 或超大值）。"""
    document = _make_video_document()
    document.storage = {"minio_object_name": "obj"}
    ctx = SimpleNamespace(
        pipeline_config={"parsing": {"video": {"strategy": "simple", "vlm_model": "v-vlm"}}},
        embedding_config={"model": "emb", "dimension": 8},
    )

    captured: dict = {}

    async def fake_load(session, doc, task):
        return ctx

    async def fake_cancel(doc_id):
        return None

    async def fake_extract(content, interval, maxf):
        return [(b"f", 0.0, 0)]

    async def fake_get_minio(cls):
        return _FakeMinio()

    async def fake_describe_single(frames, vlm_client, prompt, **kw):
        captured["concurrency"] = kw.get("concurrency")
        return [("desc", ts, idx) for _, ts, idx in frames]

    async def fake_persist(document, text, session, logger):
        return None

    async def fake_tail(**kw):
        return {"chunk_count": 1}

    fake_app_config = SimpleNamespace(
        knowledge_base=SimpleNamespace(
            parsing=SimpleNamespace(video_vlm_concurrency=99),  # 越界
        ),
    )

    monkeypatch.setattr(media_processing, "load_pipeline_context", fake_load)
    monkeypatch.setattr(media_processing, "_check_document_cancelled", fake_cancel)
    monkeypatch.setattr(media_processing, "extract_frames_fixed", fake_extract)
    monkeypatch.setattr(
        "novamind.shared.storage.client_factory.ClientFactory.get_minio_client",
        classmethod(fake_get_minio),
    )
    monkeypatch.setattr(media_processing, "describe_single", fake_describe_single)
    monkeypatch.setattr(media_processing, "persist_parsed_text", fake_persist)
    monkeypatch.setattr(media_processing, "_run_post_parse_tail", fake_tail)
    monkeypatch.setattr(
        "novamind.shared.prompts.templates.PromptManager.get_template", lambda name: "prompt"
    )
    monkeypatch.setattr("novamind.setting.yaml_config.get_config", lambda: fake_app_config)

    class _MCS:
        async def get_vlm_client_by_model(self, user_id, model):
            return object()

    session = _FakeSession()
    await media_processing.process_video_document(
        document=document,
        file_content=b"fake",
        session=session,
        logger=_silent_logger(),
        task=None,
        model_config_port=_MCS(),
    )

    assert captured["concurrency"] == 20  # clamp 到上界