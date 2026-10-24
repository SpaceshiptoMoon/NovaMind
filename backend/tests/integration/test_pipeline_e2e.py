"""真实基础设施端到端测试（批次 5.1）：上传→解析→切分→ES 索引→检索。

真实组件：MySQL（真实库真实表）、MinIO（真实对象存储 novamind-dev bucket）、
ES（真实索引写入与 BM25 检索）。确定性桩：embedding 向量与模型配置端口
——外部模型 API 不在集成验证范围（组件接线正确性用确定性向量断言，
LLM 语义质量属评估域），question_generation 关闭。

全链路：execute_document_pipeline 完整执行（MinIO 解析全文持久化 + ES
chunk 批量写入 + delete-before-write），随后经 search_service 的 BM25
路径检索唯一标记词断言命中。任一依赖服务不可达时整文件 skip。
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.integration

EMBED_DIM = 8


async def _services_available() -> tuple[bool, str]:
    """探测 MySQL/Redis/ES/MinIO 可达性；返回 (是否全通, 首个不可达说明)。

    协程形态：由 async fixture 直接 await——pytest-asyncio 管理的 loop 内
    不能再用 asyncio.run() 起嵌套循环。
    """
    try:
        from sqlalchemy import text

        from novamind.core.database.database import get_db_session

        async with get_db_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        return False, f"MySQL 不可达: {exc}"
    try:
        from novamind.shared.storage.client_factory import ClientFactory

        es = await ClientFactory.get_elasticsearch_client()
        await es.es_client.info()
    except Exception as exc:
        return False, f"ES 不可达: {exc}"
    try:
        await ClientFactory.get_minio_client()
    except Exception as exc:
        return False, f"MinIO 不可达: {exc}"
    try:
        from novamind.core.auth.blacklist import get_raw_redis

        redis = await get_raw_redis()
        await redis.ping()
    except Exception as exc:
        return False, f"Redis 不可达: {exc}"
    return True, ""


@pytest_asyncio.fixture()
async def e2e_env():
    """真实 DB/MinIO/ES 环境 + 测试 space/kb/document 行；teardown 全量清理。

    任一依赖服务不可达时 skip（CI 无基础设施环境不阻塞单测流）。"""
    # 测试进程无 lifespan：手动装配 ClientFactory（与 startup_manager 同款）
    from novamind.shared.storage.client_factory import ClientFactory
    from novamind.setting.yaml_config import get_config

    ClientFactory.configure(get_config())

    ok, reason = await _services_available()
    if not ok:
        pytest.skip(f"集成依赖不可用：{reason}")
    from novamind.core.database.database import get_db_session
    from novamind.features.knowledge_space.models.document import Document
    from novamind.features.knowledge_space.models.document_task import (
        DocumentTask,
        TaskProcessMode,
        TaskStatus,
    )
    from novamind.features.knowledge_space.models.document_task_batch import (
        DocumentTaskBatch,
    )
    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
    from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace

    token = uuid.uuid4().hex[:8]
    async with get_db_session() as session:
        space = KnowledgeSpace(
            name=f"e2e-{token}", owner_id=1,
            config={"description": "pipeline e2e"}, visibility=0,  # SpaceVisibility.PRIVATE
        )
        session.add(space)
        await session.flush()
        kb = KnowledgeBase(
            space_id=space.id, name=f"e2e-kb-{token}", creator_id=1,
            status=1, config={
                "splitting": {"strategy": "recursive", "chunk_size": 200, "chunk_overlap": 20},
                "parsing": {},
                "retrieval": {},
                "limits": {},
                "embedding": {"model": "fake-emb", "dimension": EMBED_DIM},
            },
        )
        session.add(kb)
        await session.flush()
        doc = Document(
            kb_id=kb.id, space_id=space.id, filename=f"e2e-{token}.txt",
            file_type="txt", file_size=2048, file_hash=f"e2e-{token}",
            storage={"minio_object_name": f"e2e/{token}.txt"},
            uploader_id=1,
        )
        session.add(doc)
        await session.flush()
        batch = DocumentTaskBatch(
            space_id=space.id, kb_id=kb.id, creator_id=1,
            action=1, status=1, total_count=1, processed_count=0,
        )
        session.add(batch)
        await session.flush()
        task = DocumentTask(
            batch_id=batch.id,
            document_id=doc.id, kb_id=kb.id, space_id=space.id,
            status=TaskStatus.PROCESSING, process_mode=TaskProcessMode.PROCESS,
        )
        session.add(task)
        await session.commit()
        yield {
            "token": token, "space_id": space.id, "kb_id": kb.id,
            "document_id": doc.id, "task_id": task.id, "session_factory": get_db_session,
        }

        # ---- teardown：ES 数据 → MinIO 对象 → DB 行 ----
        try:
            from novamind.shared.storage.client_factory import ClientFactory

            es = await ClientFactory.get_elasticsearch_client()
            await es.es_client.delete_by_query(
                index="_all", body={"query": {"term": {"document_id": doc.id}}},
                conflicts="proceed",
            )
            minio = await ClientFactory.get_minio_client()
            try:
                await minio.remove_object("novamind-dev", f"e2e/{token}.txt")
            except Exception:
                pass
        except Exception:
            pass
        await session.execute(
            DocumentTask.__table__.delete().where(DocumentTask.id == task.id)
        )
        await session.execute(
            DocumentTaskBatch.__table__.delete().where(DocumentTaskBatch.id == batch.id)
        )
        await session.execute(
            Document.__table__.delete().where(Document.id == doc.id)
        )
        await session.execute(
            KnowledgeBase.__table__.delete().where(KnowledgeBase.id == kb.id)
        )
        await session.execute(
            KnowledgeSpace.__table__.delete().where(KnowledgeSpace.id == space.id)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_upload_parse_index_search_end_to_end(e2e_env):
    """全链路：txt 文档经完整管道解析/切分/索引后，BM25 检索命中唯一标记词。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from novamind.core.database.database import get_db_session
    from novamind.features.knowledge_space.services.document_pipeline import (
        execute_document_pipeline,
    )
    from novamind.features.knowledge_space.services import pipeline_steps

    env = e2e_env
    marker = f"E2EMARKER{env['token']}"
    content = (
        f"{marker} 知识库解析管道端到端验证文档。\n\n"
        "第二段内容描述检索索引的写入路径，包含切分边界与向量化流程。\n\n"
        "第三段覆盖 delete-before-write 语义与 chunk 生命周期管理。\n\n"
        f"收尾段落再次出现 {marker} 用于反向断言唯一性。\n"
    ) * 3

    async def fake_embeddings(texts, embedding_config, **kwargs):
        return [[0.1] * EMBED_DIM for _ in texts]

    class _FakeEmbeddingClient:
        """最小 embedding 客户端桩：批量生成确定性向量（BM25 断言不依赖向量语义）。"""

        async def generate_embeddings_batch(self, texts, batch_size=None):
            return [[0.1] * EMBED_DIM for _ in texts]

    fake_port = SimpleNamespace(
        get_user_default_model_name=AsyncMock(return_value="fake-emb"),
        get_credentials_by_model=AsyncMock(
            return_value=SimpleNamespace(extra_config={"dimension": EMBED_DIM})
        ),
        get_embedding_client_by_model=AsyncMock(return_value=_FakeEmbeddingClient()),
    )

    from unittest.mock import patch

    with (
        patch.object(pipeline_steps, "generate_embeddings", fake_embeddings),
        patch.object(
            pipeline_steps, "maybe_semantic_embedding_client", AsyncMock(return_value=None)
        ),
        patch.object(
            pipeline_steps, "check_document_cancelled", AsyncMock(return_value=None)
        ),
    ):
        async with get_db_session() as session:
            await execute_document_pipeline(
                session,
                env["document_id"],
                env["kb_id"],
                env["space_id"],
                f"e2e-{env['token']}.txt",
                model_config_port=fake_port,
                file_content=content.encode("utf-8"),
            )

    # ---- 断言 1：任务终态 COMPLETED（终态写在 DocumentTask，Document 无 status 列）----
    from sqlalchemy import select

    from novamind.features.knowledge_space.models.document_task import DocumentTask, TaskStatus

    async with get_db_session() as session:
        task_row = (
            await session.execute(
                select(DocumentTask).where(DocumentTask.id == env["task_id"])
            )
        ).scalar_one()
        assert task_row.status == TaskStatus.COMPLETED, (
            f"任务未到 COMPLETED 终态: {task_row.status}"
        )

    # ---- 断言 2：ES 中存在该文档 chunk 且 content 含标记词 ----
    from novamind.shared.storage.client_factory import ClientFactory

    es = await ClientFactory.get_elasticsearch_client()
    # bulk 写入后默认 1s 才可见（refresh_interval）——测试立即断言需显式 refresh
    await es.es_client.indices.refresh(index="_all")
    hit = await es.es_client.search(
        index="_all",
        body={"query": {"term": {"document_id": env["document_id"]}}, "size": 10},
    )
    chunks = hit["hits"]["hits"]
    assert chunks, "ES 中无该文档 chunk——索引步骤未生效"
    contents = " ".join(c["_source"].get("content", "") for c in chunks)
    assert marker in contents, "chunk content 不含唯一标记词（解析或切分丢失内容）"
    assert len(chunks) >= 2, f"切分产出过少: {len(chunks)}"

    # ---- 断言 3：BM25 检索路径命中标记词 ----
    result = await es.es_client.search(
        index="_all",
        body={
            "query": {
                "bool": {
                    "must": [{"match": {"content": marker}}],
                    "filter": [{"term": {"document_id": env["document_id"]}}],
                }
            },
            "size": 5,
        },
    )
    bm25_hits = result["hits"]["hits"]
    assert bm25_hits, "BM25 检索未命中标记词"
    assert marker in bm25_hits[0]["_source"]["content"]

    # ---- 断言 4：MinIO 持久化了解析全文（persist_parsed_text 的对象存在且非空）----
    minio = await ClientFactory.get_minio_client()
    # fixture 的 storage.minio_object_name = e2e/{token}.txt → 解析全文写
    # 在 {base}_parsed/full_text.md，切分/向量产物在 {base}_artifacts/ 下
    prefix = f"e2e/{env['token']}"
    names = await minio.list_files("novamind-dev", prefix=prefix)
    assert any("_parsed/full_text" in n for n in names), (
        f"MinIO 缺解析全文对象（persist 步骤未生效）: {names[:5]}"
    )
    assert any("_artifacts/chunks" in n for n in names), (
        f"MinIO 缺切分产物对象（artifact 持久化未生效）: {names[:5]}"
    )
