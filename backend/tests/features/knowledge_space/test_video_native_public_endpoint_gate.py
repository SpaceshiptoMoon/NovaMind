"""video_native 策略的 minio.public_endpoint 能力前提前置判定。

外部 VLM 要能下载切片 URL 依赖 public_endpoint；未配置时生成的是内网地址，
服务商必拒（实测 400 "URL does not appear to be valid"）且不命中
VideoInputNotSupportedError 降级判据。回归 doc 980：
- 未配置 + 允许降级 → 一次 video_native 请求都不发，直接走 frame_seq
- 未配置 + 禁止降级 → PermanentProcessingError，文案直达配置项
- 已配置 → 正常走 video_native（相邻正常场景不误伤）
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.exceptions import PermanentProcessingError
from novamind.features.knowledge_space.services import media_processing

pytestmark = pytest.mark.unit


class _FakeSession:
    """只记录 commit 次数的会话桩。"""

    def __init__(self) -> None:
        self.commit_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1

    async def begin_nested(self):
        return self


class _FakeMinio:
    """MinIO 桩；public_endpoint 由用例按场景注入（缺省不设该属性）。"""

    def __init__(self, public_endpoint: str | None = None) -> None:
        if public_endpoint is not None:
            self.public_endpoint = public_endpoint
        self.default_bucket = "novamind-test"

    async def upload_file(self, object_name, data, content_type):
        return None

    async def get_public_file_url(self, bucket, object_name):
        return f"http://{getattr(self, 'public_endpoint', '127.0.0.1:9000')}/{bucket}/{object_name}"

    async def delete_objects_by_prefix(self, bucket, prefix):
        return None


class _VideoVlmClient:
    """同时具备 openai_video 两种入口的 VLM 客户端桩（具体调用被上层函数桩拦截）。"""

    async def generate_text_from_video_url(self, *a, **k):
        raise AssertionError("不应直接到达客户端")

    async def generate_text_from_frames(self, *a, **k):
        raise AssertionError("不应直接到达客户端")


def _silent_logger() -> SimpleNamespace:
    return SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        debug=lambda *a, **k: None,
    )


def _make_video_document() -> SimpleNamespace:
    return SimpleNamespace(
        id=980,
        space_id=38,
        kb_id=108,
        file_hash="h",
        filename="video_t1.mp4",
        file_type="mp4",
        storage={"minio_object_name": "obj"},
        uploader_id=1,
    )


def _patch_common(monkeypatch, *, minio: _FakeMinio, fallback: bool | None, calls: dict):
    """装配 video_native 分支前后所有外部依赖的桩，返回 pipeline ctx。"""
    video_cfg: dict = {"strategy": "video_native", "vlm_model": "v-vlm", "frame_interval": 2.0}
    if fallback is not None:
        video_cfg["video_native_fallback_to_frame_seq"] = fallback
    ctx = SimpleNamespace(
        pipeline_config={"parsing": {"video": video_cfg}},
        embedding_config={"model": "emb", "dimension": 8},
    )

    async def fake_load(session, doc, task):
        return ctx

    async def fake_cancel(doc_id):
        return None

    async def fake_extract_scene(content, max_frames, **kw):
        return [(b"f", 0.0, 0), (b"f", 3.0, 1), (b"f", 6.0, 2)]

    async def fake_get_minio(cls):
        return minio

    async def fake_native(*a, **kw):
        calls["native"] += 1
        return [("片描述", 0.0, 6.0, [0, 1, 2])]

    async def fake_frame_seq(frames, vlm_client, prompt, **kw):
        calls["frame_seq"] += 1
        return [("段描述", frames[0][1], frames[-1][1], [idx for _, _, idx in frames])]

    async def fake_persist(document, text, session, logger):
        return None

    async def fake_tail(inputs=None, **kw):
        calls["tail"] += 1
        return {"chunk_count": 1}

    monkeypatch.setattr(media_processing, "load_pipeline_context", fake_load)
    monkeypatch.setattr(media_processing, "check_document_cancelled", fake_cancel)
    monkeypatch.setattr(media_processing, "extract_frames_scene", fake_extract_scene)
    monkeypatch.setattr(media_processing, "_probe_video_duration", lambda p: 6.5)
    monkeypatch.setattr(
        "novamind.shared.storage.client_factory.ClientFactory.get_minio_client",
        classmethod(fake_get_minio),
    )
    monkeypatch.setattr(media_processing, "describe_video_native", fake_native)
    monkeypatch.setattr(media_processing, "describe_frame_sequence", fake_frame_seq)
    monkeypatch.setattr(media_processing, "persist_parsed_text", fake_persist)
    monkeypatch.setattr(media_processing, "run_post_parse_tail", fake_tail)
    monkeypatch.setattr(
        "novamind.shared.prompts.templates.PromptManager.get_template", lambda name: "prompt"
    )


class _MCS:
    async def get_vlm_client_by_model(self, user_id, model):
        return _VideoVlmClient()


async def _run(document):
    await media_processing.process_video_document(
        document=document,
        file_content=b"fake",
        session=_FakeSession(),
        logger=_silent_logger(),
        task=None,
        model_config_port=_MCS(),
    )


@pytest.mark.asyncio
async def test_no_public_endpoint_falls_back_without_native_request(monkeypatch):
    """未配 public_endpoint 且允许降级（默认）：零次 video_native 调用，直接 frame_seq 并走完 tail。"""
    calls = {"native": 0, "frame_seq": 0, "tail": 0}
    _patch_common(monkeypatch, minio=_FakeMinio(), fallback=None, calls=calls)

    await _run(_make_video_document())

    assert calls["native"] == 0
    assert calls["frame_seq"] == 1
    assert calls["tail"] == 1


@pytest.mark.asyncio
async def test_no_public_endpoint_and_fallback_disabled_raises_permanent(monkeypatch):
    """未配 public_endpoint 且禁止降级：永久错误直达配置项，不发任何 VLM 请求。"""
    calls = {"native": 0, "frame_seq": 0, "tail": 0}
    _patch_common(monkeypatch, minio=_FakeMinio(), fallback=False, calls=calls)

    with pytest.raises(PermanentProcessingError, match="minio.public_endpoint"):
        await _run(_make_video_document())

    assert calls == {"native": 0, "frame_seq": 0, "tail": 0}


@pytest.mark.asyncio
async def test_public_endpoint_configured_runs_native_path(monkeypatch):
    """已配 public_endpoint：正常走 video_native，不触发前置降级（相邻正常场景不误伤）。"""
    calls = {"native": 0, "frame_seq": 0, "tail": 0}
    _patch_common(
        monkeypatch, minio=_FakeMinio(public_endpoint="minio.example.com"),
        fallback=None, calls=calls,
    )

    await _run(_make_video_document())

    assert calls["native"] == 1
    assert calls["frame_seq"] == 0
    assert calls["tail"] == 1
