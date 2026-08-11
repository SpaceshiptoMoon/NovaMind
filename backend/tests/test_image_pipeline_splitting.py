"""图片管道切分回归测试。

History: 23f424d 图片路径接入共享尾 ``_run_post_parse_tail`` 时模仿 audio/video 调
``apply_modality_splitting_override(splitting_config, "image")`` + ``full_text`` 走
``_split_md_text``。但 splitting schema 无 image 子键（只有 audio/video），且
``kb.get_config()`` 返回原始存储 dict 不经 Pydantic 校验，遗留脏值
``splitting.image.strategy="single"``（旧版前端图片专属切分选项，现 schema 已移除但
旧 KB 配置 DB 残留）经 ``apply_modality_splitting_override`` 合并到顶层后被
``_split_md_text`` 拒绝 → ``ValueError``「不支持的切分策略」，图片文档处理整个失败
（document_id=61, job_id=doc-task-233）。

Fix: 图片描述文本与 MD 文档同构，按顶层通用切分策略（recursive/markdown/fixed_size/semantic）
切成多块（与文本/音频/视频同路径）。不调 ``apply_modality_splitting_override``（splitting
无 image 子键 schema），并 pop 掉遗留脏 image 子键，避免覆盖顶层 strategy。
QG/embedded/indexed 仍走共享尾，保留 23f424d 相似问修复成果。
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


def _patch_tail_deps(monkeypatch):
    """mock 共享尾的外部依赖（向量化/ES/取消检查），让 _split_md_text 真实跑。"""

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


@pytest.mark.asyncio
async def test_image_dirty_image_subkey_does_not_break_split(monkeypatch):
    """遗留脏 splitting.image.strategy='single' 不应让图片处理失败。

    复现 document_id=61 场景：顶层 strategy=recursive（前端配的有效值）+ 脏 image 子键
    strategy=single。修复后 image 子键被 pop，顶层 recursive 生效，图片描述正常切分。
    """
    _patch_tail_deps(monkeypatch)

    result = await document_pipeline._run_post_parse_tail(
        document=_make_document(),
        session=None,
        task=_make_task(),
        model_config_port=None,
        logger=None,
        chunk_type=ChunkType.IMAGE,
        embedding_config={"dimension": 4},
        pipeline_config={"question_generation": {"enabled": False}},
        splitting_config={
            "strategy": "recursive",
            "chunk_size": 100,
            "image": {"strategy": "single"},  # 遗留脏值
        },
        full_text="一只橘猫趴在窗台上晒太阳，窗外是城市的远景。",
        user_id=1,
    )
    assert result["split_strategy"] == "recursive"
    assert result["chunk_count"] >= 1


@pytest.mark.asyncio
async def test_image_description_is_splittable_into_multiple_chunks(monkeypatch):
    """图片描述文本可按通用切分策略切成多块（用户诉求：图片也可以切）。"""
    _patch_tail_deps(monkeypatch)

    long_description = "这是一张图片的描述。" * 60  # 约 600 字

    result = await document_pipeline._run_post_parse_tail(
        document=_make_document(),
        session=None,
        task=_make_task(),
        model_config_port=None,
        logger=None,
        chunk_type=ChunkType.IMAGE,
        embedding_config={"dimension": 4},
        pipeline_config={"question_generation": {"enabled": False}},
        splitting_config={"strategy": "fixed_size", "chunk_size": 100, "chunk_overlap": 0},
        full_text=long_description,
        user_id=1,
    )
    assert result["split_strategy"] == "fixed_size"
    assert result["chunk_count"] > 1, "图片描述应能切成多块"


@pytest.mark.asyncio
async def test_full_text_with_dirty_top_level_strategy_still_raises(monkeypatch):
    """对照：顶层 strategy='single'（脏值）仍会抛错。

    前端顶层 splitting 只提交 recursive/fixed_size/markdown/semantic，顶层不会是 single；
    脏 single 只在遗留 image 子键。此用例确认顶层脏值不在本次修复范围
    （``_migrate_legacy_splitting_strategy`` 故意留 clear error）。
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
            full_text="x",
            user_id=1,
        )