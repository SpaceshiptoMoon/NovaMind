"""空间未固化 embedding 配置时的口径统一（2026-10-21 space1 索引失败回归）。

复现场景：space.config.embedding 只有 {normalize, batch_size}，既无 model 也无
dimension。处理管道按「用户默认 embedding 模型」生成向量（既有兜底语义），但
索引步骤只读空间配置的 dimension → None → bulk_index_chunks 拒绝建索引，
报错发生在切分之后，用户看到「解析失败、没有产出分块」而解析其实早已成功。

修复口径：run_post_parse_tail 入口把配置补足到真实执行口径（维度取自
user_model_configs.extra_config.dimension），补不出才抛永久错误；空间配置
更新门禁按「生效 embedding」比较，使未固化空间可以把当前默认模型固化进配置
而不被「已有文档禁改」门禁误伤。
"""
from types import SimpleNamespace

import pytest
from novamind.features.knowledge_space.exceptions import PermanentProcessingError
from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.services import pipeline_steps
from novamind.features.knowledge_space.services.pipeline_steps import TailInputs
from novamind.features.knowledge_space.services.space_service import SpaceService


class _FakeSession:
    async def commit(self):
        return None


def _make_document(document_id: int = 42):
    return SimpleNamespace(
        id=document_id,
        space_id=7,
        kb_id=3,
        uploader_id=1,
        filename="a.md",
        file_type="md",
        file_hash="h" * 32,
        storage={},
    )


class _FakeModelConfigService:
    """只实现 resolve_embedding_config 用到的两个查询。"""

    def __init__(self, *, default_model=None, dimensions=None):
        self.default_model = default_model
        self.dimensions = dimensions or {}
        self.credentials_calls: list[tuple[int, str, str]] = []

    async def get_user_default_model_name(self, user_id: int, model_type: str):
        assert model_type == "embedding"
        return self.default_model

    async def get_credentials_by_model(self, user_id: int, model_type: str, model: str):
        self.credentials_calls.append((user_id, model_type, model))
        dim = self.dimensions.get(model)
        if dim is None:
            return None
        return SimpleNamespace(extra_config={"dimension": dim})


class _RaisingCredentials(_FakeModelConfigService):
    async def get_credentials_by_model(self, user_id: int, model_type: str, model: str):
        raise RuntimeError("db down")


def _patch_tail_deps(monkeypatch, captured: dict):
    async def _no_cancel(doc_id):
        return None

    async def _fake_embed(texts, emb_cfg, *, session, user_id, model_config_port=None):
        captured["embedding_model"] = emb_cfg.get("model")
        captured["embedding_dim"] = emb_cfg.get("dimension")
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    es_client = SimpleNamespace(
        bulk_index_chunks=_capture_bulk(captured),
        delete_document_chunks=_noop,
    )

    async def _fake_es():
        return es_client

    monkeypatch.setattr(pipeline_steps, "check_document_cancelled", _no_cancel)
    monkeypatch.setattr(pipeline_steps, "generate_embeddings", _fake_embed)
    monkeypatch.setattr(pipeline_steps, "get_es_client", _fake_es)


async def _noop(*args, **kwargs):
    return None


def _capture_bulk(captured: dict):
    async def _bulk(*, space_id, chunks, embedding_dim):
        captured["bulk_dim"] = embedding_dim
        return len(chunks)

    return _bulk


async def _run_tail(*, embedding_config, model_config_port, monkeypatch, captured):
    _patch_tail_deps(monkeypatch, captured)
    return await pipeline_steps.run_post_parse_tail(
TailInputs(
        document=_make_document(),
        session=_FakeSession(),
        task=SimpleNamespace(
            start_step=lambda name: None,
            finish_step=lambda name, metrics=None: None,
        ),
        model_config_port=model_config_port,
        logger=None,
        chunk_type=ChunkType.TEXT,
        embedding_config=embedding_config,
        pipeline_config={"question_generation": {"enabled": False}},
        splitting_config={"strategy": "fixed_size", "chunk_size": 50, "chunk_overlap": 0},
        full_text="内容丁。" * 30,
        user_id=1,
    ))


@pytest.mark.asyncio
async def test_space_without_embedding_uses_user_default_dimension(monkeypatch):
    """空间只配 batch_size/normalize 时：按用户默认模型取维度，索引照常完成。"""
    captured: dict = {}
    service = _FakeModelConfigService(
        default_model="qwen3.7-text-embedding-flash",
        dimensions={"qwen3.7-text-embedding-flash": 1024},
    )
    result = await _run_tail(
        embedding_config={"normalize": True, "batch_size": 32},
        model_config_port=service,
        monkeypatch=monkeypatch,
        captured=captured,
    )
    assert captured["bulk_dim"] == 1024
    assert captured["embedding_model"] == "qwen3.7-text-embedding-flash"
    assert result["indexed_count"] >= 1
    assert service.credentials_calls == [(1, "embedding", "qwen3.7-text-embedding-flash")]


@pytest.mark.asyncio
async def test_space_dimension_wins_over_model_config(monkeypatch):
    """空间已固化 dimension 时以空间配置为准，不再查模型配置（回填口径一致）。"""
    captured: dict = {}
    service = _FakeModelConfigService(
        default_model="other-model",
        dimensions={"other-model": 1536},
    )
    await _run_tail(
        embedding_config={"model": "space-model", "dimension": 768},
        model_config_port=service,
        monkeypatch=monkeypatch,
        captured=captured,
    )
    assert captured["bulk_dim"] == 768
    assert captured["embedding_model"] == "space-model"
    assert service.credentials_calls == []


@pytest.mark.asyncio
async def test_no_embedding_anywhere_raises_permanent_error_before_split(monkeypatch):
    """空间与用户都没有可用 embedding 模型：抛永久错误（不重试），且不进入索引。"""
    captured: dict = {}

    async def _must_not_split(*args, **kwargs):
        raise AssertionError("配置缺口应在切分之前抛错")

    monkeypatch.setattr(pipeline_steps, "split_md_text", _must_not_split)
    _patch_tail_deps(monkeypatch, captured)

    with pytest.raises(PermanentProcessingError, match="无法确定 embedding 向量维度"):
        await pipeline_steps.run_post_parse_tail(
TailInputs(
            document=_make_document(),
            session=_FakeSession(),
            task=SimpleNamespace(
                start_step=lambda name: None,
                finish_step=lambda name, metrics=None: None,
            ),
            model_config_port=_FakeModelConfigService(default_model=None),
            logger=None,
            chunk_type=ChunkType.TEXT,
            embedding_config={"batch_size": 32},
            pipeline_config={"question_generation": {"enabled": False}},
            splitting_config={"strategy": "fixed_size", "chunk_size": 50, "chunk_overlap": 0},
            full_text="内容戊。" * 30,
            user_id=1,
    ))
    assert "bulk_dim" not in captured


@pytest.mark.asyncio
async def test_credentials_lookup_failure_degrades_to_config_missing_error(monkeypatch):
    """凭证查询异常不能被当成「维度已配置」放行，也不能裸抛 500 类错误。"""
    captured: dict = {}
    with pytest.raises(PermanentProcessingError):
        await _run_tail(
            embedding_config={"model": "space-model"},
            model_config_port=_RaisingCredentials(default_model="space-model"),
            monkeypatch=monkeypatch,
            captured=captured,
        )


# ========== 空间配置更新门禁：按生效 embedding 比较 ==========


def _service_with_effective(effective: dict) -> SpaceService:
    """构造只具备 _is_embedding_changed 所需依赖的服务实例（免 DB）。"""
    service = object.__new__(SpaceService)
    return service


def _check(update: dict, current: dict, effective: dict | None = None) -> bool:
    service = object.__new__(SpaceService)
    return service._is_embedding_changed(update, current, effective)


def test_pinning_current_default_model_is_not_a_change():
    """未固化空间把「当前默认模型」固化进配置：不触发换模型门禁。"""
    assert _check(
        {"embedding": {"model": "qwen3.7-text-embedding-flash", "batch_size": 32}},
        {"embedding": {"normalize": True, "batch_size": 32}},
        {"model": "qwen3.7-text-embedding-flash", "dimension": 1024},
    ) is False


def test_pinning_different_model_still_blocked():
    """未固化空间换成非当前生效的模型：仍按变更处理（门禁拦截）。"""
    assert _check(
        {"embedding": {"model": "text-embedding-v3"}},
        {"embedding": {"normalize": True}},
        {"model": "qwen3.7-text-embedding-flash", "dimension": 1024},
    ) is True


def test_only_batch_size_change_not_detected_with_effective():
    """只改批大小/归一化：始终不算 embedding 语义变更。"""
    assert _check(
        {"embedding": {"batch_size": 64, "normalize": False}},
        {"embedding": {"normalize": True, "batch_size": 32}},
        {"model": "qwen3.7-text-embedding-flash", "dimension": 1024},
    ) is False


def test_literal_comparison_without_effective_preserved():
    """不传生效配置时退化为字面比较（既有测试与纯函数语义不变）。"""
    assert _check(
        {"embedding": {"model": "text-embedding-v3"}},
        {"embedding": {"normalize": True}},
    ) is True
