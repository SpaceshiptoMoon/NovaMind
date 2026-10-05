"""图片 VLM fallback / skip-on-quota 配置对齐回归（2026-10 图片链路深度批次2）。

与视频路径同名参数（``vlm_fallback_model`` / ``vlm_skip_on_quota_error``）对齐到
图片 VLM 路径。门禁：
1. schema 两字段存在且默认关闭；
2. 消费侧读嵌套 ``parsing.image.*``（不读被 video 覆盖的扁平键）；
3. fallback 语义：主模型配额/鉴权失败才回退、其它错误原样上抛；
4. skip_on_quota 语义：仅配额/鉴权类失败降级为占位描述，其它错误仍抛；
5. 指纹注入 fallback 模型（换备用模型 = 换产物来源，快照必须失效）。
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pydantic import ValidationError

from novamind.features.knowledge_space.schemas.knowledge_base_schema import ImageParsingConfig
from novamind.features.knowledge_space.services import document_pipeline
from novamind.features.knowledge_space.services.media_processing import (
    _is_vlm_quota_or_auth_error,
)

pytestmark = pytest.mark.unit

_SILENT_LOGGER = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)


# ---------------------------------------------------------------------------
# 1. schema
# ---------------------------------------------------------------------------


def test_image_schema_has_fallback_and_skip_fields():
    cfg = ImageParsingConfig()
    assert cfg.vlm_fallback_model is None
    assert cfg.vlm_skip_on_quota_error is False

    cfg2 = ImageParsingConfig.model_validate({
        "vlm_model": "m1",
        "vlm_fallback_model": "m2",
        "vlm_skip_on_quota_error": True,
    })
    assert cfg2.vlm_fallback_model == "m2"
    assert cfg2.vlm_skip_on_quota_error is True


def test_image_schema_rejects_bad_types():
    with pytest.raises(ValidationError):
        ImageParsingConfig.model_validate({"vlm_skip_on_quota_error": "yes-please"})


# ---------------------------------------------------------------------------
# 2. 消费侧读嵌套配置（源码门禁）
# ---------------------------------------------------------------------------


def test_consumer_reads_nested_image_config():
    src = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "features"
        / "knowledge_space"
        / "services"
        / "document_pipeline.py"
    ).read_text(encoding="utf-8")
    assert 'image_nested_cfg.get("vlm_fallback_model")' in src, (
        "消费侧未读嵌套 image.vlm_fallback_model"
    )
    assert 'image_nested_cfg.get("vlm_skip_on_quota_error"' in src, (
        "消费侧未读嵌套 image.vlm_skip_on_quota_error"
    )
    # 指纹注入必须含 fallback 模型（换备用模型=换产物来源，快照必须失效）
    assert "image_vlm_fallback_model or ''" in src, (
        "图片解析指纹未注入 vlm_fallback_model：换备用模型后快照不会失效"
    )


# ---------------------------------------------------------------------------
# 3. fallback / skip 语义（端到端：_process_image_document_static）
# ---------------------------------------------------------------------------


def _make_document() -> SimpleNamespace:
    return SimpleNamespace(
        id=71,
        space_id=1,
        kb_id=1,
        file_hash="h",
        file_type="png",
        filename="a.png",
        storage={"minio_object_name": "obj"},
        uploader_id=1,
    )


async def _drive(
    monkeypatch,
    *,
    main_error: Exception | None,
    fallback_ok: str | None,
    fallback_error: Exception | None = None,
):
    """装配全部 mock 并驱动 _process_image_document_static（VLM 路径）。"""
    import novamind.features.knowledge_space.services.pipeline_snapshots as snap_mod
    import novamind.shared.storage.client_factory as cf_mod
    from novamind.features.knowledge_space.services import pipeline_steps

    class _EmptySnap:
        SNAPSHOTS_ENABLED = False

    monkeypatch.setattr(snap_mod, "SNAPSHOTS_ENABLED", False)

    async def _fake_minio():
        raise AssertionError("SNAPSHOTS_ENABLED=False 不应触碰 MinIO")

    monkeypatch.setattr(cf_mod.ClientFactory, "get_minio_client", staticmethod(_fake_minio))

    ctx = pipeline_steps.PipelineContext(
        space=SimpleNamespace(owner_id=1),
        kb=None,
        pipeline_config={
            "parsing": {
                "image": {
                    "strategy": "vlm",
                    "vlm_model": "main-vlm",
                    "vlm_fallback_model": "backup-vlm",
                    "vlm_skip_on_quota_error": True,
                }
            },
            "splitting": {},
        },
        embedding_config={"model": "emb", "dimension": 8},
    )

    async def _fake_load_ctx(session, document, task):
        return ctx

    async def _no_cancel(doc_id):
        return None

    monkeypatch.setattr(document_pipeline, "load_pipeline_context", _fake_load_ctx)
    monkeypatch.setattr(document_pipeline, "check_document_cancelled", _no_cancel)

    captured: dict = {}

    class _MCS:
        async def get_vlm_client_by_model(self, user_id, model):
            captured.setdefault("clients", []).append(model)
            if model == "main-vlm" and main_error is not None:
                class _C:
                    async def generate_text(self, **kw):
                        raise main_error

                return _C()

            class _C:
                async def generate_text(self, **kw):
                    if fallback_error is not None:
                        raise fallback_error
                    return fallback_ok

            return _C()

    async def _fake_persist(*a, **k):
        return None

    async def _fake_tail(**kwargs):
        return {"chunk_count": 1, "total_questions": 0}

    monkeypatch.setattr(document_pipeline, "persist_parsed_text", _fake_persist)
    monkeypatch.setattr(document_pipeline, "run_post_parse_tail", _fake_tail)

    class _Session:
        async def commit(self):
            return None

    raised = None
    try:
        await document_pipeline._process_image_document_static(
            document=_make_document(),
            file_content=b"\x89PNG",
            session=_Session(),
            _logger=_SILENT_LOGGER,
            task=None,
            model_config_port=_MCS(),
        )
    except Exception as exc:  # noqa: BLE001
        raised = exc
    return captured, raised


@pytest.mark.asyncio
async def test_fallback_used_on_quota_error(monkeypatch):
    """主模型配额失败 → 换备用模型重试成功 → 入库备用产物。"""
    quota_err = RuntimeError("Arrearage: allocationQuota exhausted (403)")
    assert _is_vlm_quota_or_auth_error(quota_err)
    captured, raised = await _drive(
        monkeypatch, main_error=quota_err, fallback_ok="【主体描述】备用模型描述"
    )
    assert raised is None
    assert captured.get("clients") == ["main-vlm", "backup-vlm"]


@pytest.mark.asyncio
async def test_non_quota_error_skips_fallback(monkeypatch):
    """非配额/鉴权错误（如网络超时）不回退备用模型，直接上抛。"""
    captured, raised = await _drive(
        monkeypatch,
        main_error=TimeoutError("connect timeout"),
        fallback_ok="【主体描述】不应被用到",
    )
    assert raised is not None
    assert captured.get("clients") == ["main-vlm"], "非配额错误不应触碰备用模型"


@pytest.mark.asyncio
async def test_skip_on_quota_writes_placeholder(monkeypatch):
    """主备均配额失败 + skip_on_quota=True → 占位描述继续（任务不失败）。"""
    quota_err = RuntimeError("401 unauthorized")
    captured, raised = await _drive(
        monkeypatch,
        main_error=quota_err,
        fallback_ok=None,
        fallback_error=RuntimeError("401 unauthorized again"),
    )
    assert raised is None, "skip_on_quota 开启时占位降级不应抛错"
    assert captured.get("clients") == ["main-vlm", "backup-vlm"]


@pytest.mark.asyncio
async def test_skip_on_quota_off_reraises(monkeypatch):
    """skip_on_quota=False（默认）→ 主备均配额失败后原样上抛（fail fast）。"""
    import novamind.features.knowledge_space.services.pipeline_snapshots as snap_mod
    import novamind.shared.storage.client_factory as cf_mod
    from novamind.features.knowledge_space.services import pipeline_steps

    monkeypatch.setattr(snap_mod, "SNAPSHOTS_ENABLED", False)

    async def _fake_minio():
        raise AssertionError("SNAPSHOTS_ENABLED=False 不应触碰 MinIO")

    monkeypatch.setattr(cf_mod.ClientFactory, "get_minio_client", staticmethod(_fake_minio))

    ctx = pipeline_steps.PipelineContext(
        space=SimpleNamespace(owner_id=1),
        kb=None,
        pipeline_config={
            "parsing": {
                "image": {
                    "strategy": "vlm",
                    "vlm_model": "main-vlm",
                    "vlm_fallback_model": "backup-vlm",
                    # 不设 vlm_skip_on_quota_error = 默认 False
                }
            },
            "splitting": {},
        },
        embedding_config={"model": "emb", "dimension": 8},
    )

    async def _fake_load_ctx(session, document, task):
        return ctx

    async def _no_cancel(doc_id):
        return None

    monkeypatch.setattr(document_pipeline, "load_pipeline_context", _fake_load_ctx)
    monkeypatch.setattr(document_pipeline, "check_document_cancelled", _no_cancel)

    captured: list = []

    class _MCS:
        async def get_vlm_client_by_model(self, user_id, model):
            captured.append(model)

            class _C:
                async def generate_text(self, **kw):
                    raise RuntimeError("401 unauthorized")

            return _C()

    async def _fake_persist(*a, **k):
        return None

    monkeypatch.setattr(document_pipeline, "persist_parsed_text", _fake_persist)

    class _Session:
        async def commit(self):
            return None

    raised = None
    try:
        await document_pipeline._process_image_document_static(
            document=_make_document(),
            file_content=b"\x89PNG",
            session=_Session(),
            _logger=_SILENT_LOGGER,
            task=None,
            model_config_port=_MCS(),
        )
    except Exception as exc:  # noqa: BLE001
        raised = exc

    assert raised is not None, "skip_on_quota 关闭时必须 fail fast 上抛"
    assert captured == ["main-vlm", "backup-vlm"]
