"""图片管道 prechunked_items 回归测试。

History: 23f424d 接入共享尾 ``_run_post_parse_tail`` 时，图片路径模仿 audio/video 调
``apply_modality_splitting_override(splitting_config, "image")`` + ``full_text`` 走
``_split_md_text`` 切分。但 splitting schema 无 image 子键（只有 audio/video），且
``kb.get_config()`` 返回原始存储 dict 不经 Pydantic 校验，可能携带遗留脏值
``splitting.image.strategy="single"`` 或顶层 ``strategy="single"``。
``apply_modality_splitting_override`` 把脏 image 子键合并到顶层后，``_run_post_parse_tail``
pop 出 ``"single"`` 传给 ``_split_md_text`` → ``ValueError``「不支持的切分策略」，
图片文档处理整个失败（document_id=61, job_id=doc-task-233）。

Fix: 图片语义本就是「一图一 chunk」（原版自写路径整段描述 1 个 chunk），改传
``prechunked_items`` 跳过 ``_split_md_text`` 切分。既还原原版单块语义，又对脏 splitting
策略值健壮；QG/embedded/indexed 仍走共享尾，保留 23f424d 的相似问修复成果。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.services import document_pipeline

pytestmark = pytest.mark.unit


def _make_document() -> SimpleNamespace:
    return SimpleNamespace(
        id=61,
        space_id=1,
        kb_id=1,
        file_hash="h",
        filename="x.png",
        file_type="png",
        storage={"minio_object_name": "obj"},
        uploader_id=1,
    )


def _make_task() -> SimpleNamespace:
    return SimpleNamespace(
        start_step=lambda *a, **k: None,
        finish_step=lambda *a, **k: None,
        mark_completed=lambda *a, **k: None,
    )


@pytest.mark.asyncio
async def test_image_prechunked_tolerates_dirty_splitting_strategy(monkeypatch):
    """图片走 prechunked_items 时，脏 splitting.strategy='single' 不应导致失败。"""

    async def _no_cancel(doc_id: int) -> None:
        return None

    async def _fake_embed(texts, emb_cfg, *, session, user_id, model_config_port=None):
        return [b"\x00\x00\x00\x00"] * len(texts)

    async def _fake_es():
        async def _bulk(*, space_id, chunks, embedding_dim):
            return len(chunks)

        return SimpleNamespace(bulk_index_chunks=_bulk)

    monkeypatch.setattr(document_pipeline, "_check_document_cancelled", _no_cancel)
    monkeypatch.setattr(document_pipeline, "_generate_embeddings_static", _fake_embed)
    monkeypatch.setattr(document_pipeline, "_get_es_client_static", _fake_es)

    result = await document_pipeline._run_post_parse_tail(
        document=_make_document(),
        session=None,
        task=_make_task(),
        model_config_port=None,
        logger=None,
        chunk_type=ChunkType.IMAGE,
        embedding_config={"dimension": 4},
        pipeline_config={"question_generation": {"enabled": False}},
        splitting_config={"strategy": "single"},  # 遗留脏值
        prechunked_items=[("一张猫的图片描述", {})],
        user_id=1,
    )
    assert result["chunk_count"] == 1
    assert result["split_strategy"] == "structural"


@pytest.mark.asyncio
async def test_full_text_with_dirty_strategy_still_raises(monkeypatch):
    """对照：full_text 分支仍调 _split_md_text，脏 strategy='single' 应抛错。

    证明 prechunked_items 是图片路径的正确绕过——脏值在切分分支确实会炸，
    故图片必须走 prechunked_items 而非 full_text。
    """

    async def _no_cancel(doc_id: int) -> None:
        return None

    monkeypatch.setattr(document_pipeline, "_check_document_cancelled", _no_cancel)

    with pytest.raises(ValueError, match="不支持的切分策略"):
        await document_pipeline._run_post_parse_tail(
            document=_make_document(),
            session=None,
            task=_make_task(),
            model_config_port=None,
            logger=None,
            chunk_type=ChunkType.IMAGE,
            embedding_config={"dimension": 4},
            pipeline_config={"question_generation": {"enabled": False}},
            splitting_config={"strategy": "single"},
            full_text="一张猫的图片描述",
            user_id=1,
        )