"""
Wiki 生成 arq 任务

- process_wiki_ingest_task：单文档 wiki 生成（四阶段管道宿主）
- enqueue_wiki_ingest：入队（WikiIngestRecord 行 + arq job 原子提交）

触发点在 document_tasks 的成功分支（文档终态落库、ES 可检索之后）。
并发模型：per-KB Redis 锁串行化同 KB 的 wiki 生成；拿不到锁抛
TransientBusyError 延后重入队（复用文档任务已有的拥塞语义）。
"""
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.mq.exceptions import TransientBusyError

logger = get_logger(__name__)

WIKI_KB_LOCK_PREFIX = "wiki:kb_lock:"
WIKI_KB_LOCK_TTL = 1800  # 30 分钟，防 worker 崩溃后锁死；管道超时由 arq job_timeout 兜底

WIKI_INGEST_JOB_TIMEOUT = 1800


async def acquire_kb_lock(kb_id: int) -> Optional[str]:
    """拿 per-KB wiki 生成锁（Redis SET NX EX）。成功返回锁值，失败 None。"""
    import uuid

    from novamind.shared.cache.redis_client import get_redis_client

    redis = await get_redis_client()
    raw_client = redis.redis_client
    token = f"wiki-lock-{uuid.uuid4().hex}"
    got = await raw_client.set(f"{WIKI_KB_LOCK_PREFIX}{kb_id}", token, nx=True, ex=WIKI_KB_LOCK_TTL)
    return token if got else None


async def release_kb_lock(kb_id: int, token: str) -> None:
    """释放 per-KB 锁（校验 token 防误删他人锁）"""
    from novamind.shared.cache.redis_client import get_redis_client

    redis = await get_redis_client()
    raw_client = redis.redis_client
    key = f"{WIKI_KB_LOCK_PREFIX}{kb_id}"
    current = await raw_client.get(key)
    if current and (current.decode() if isinstance(current, bytes) else str(current)) == token:
        await raw_client.delete(key)


async def process_wiki_ingest_task(
    ctx: dict,
    kb_id: int,
    space_id: int,
    document_id: int,
) -> dict:
    """单文档 wiki 生成任务（arq worker 入口）。

    流程：校验配置 → 拿 per-KB 锁 → 取输入（MinIO parsed_text + ES chunks）
    → 四阶段管道 → 终态落库 + 通知。所有失败最终标记 record failed，
    不影响文档任务状态。
    """
    from novamind.core.database.database import get_db_session
    from novamind.features.knowledge_space.models.wiki import WikiIngestStatus
    from novamind.features.knowledge_space.repository.knowledge_base_repository import (
        KnowledgeBaseRepository,
    )
    from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
    from novamind.features.knowledge_space.repository.wiki_repository import WikiIngestRecordRepository
    from novamind.features.knowledge_space.repository.wiki_repository import WikiIngestRecordRepository
    from novamind.features.knowledge_space.services.wiki_ingest_service import (
        WikiGenerationError,
        WikiIngestService,
    )
    from novamind.features.user.services.model_config_service import ModelConfigService
    from novamind.shared.storage.client_factory import ClientFactory
    from novamind.shared.utils.time_utils import now_china

    record_id: Optional[int] = None
    lock_token: Optional[str] = None

    async with get_db_session() as session:
        try:
            # 1. KB 与配置校验
            kb_repo = KnowledgeBaseRepository(session)
            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                logger.warning("wiki 生成：KB 不存在，跳过", kb_id=kb_id)
                return {"skipped": "kb_not_found"}
            kb_config = kb.get_config() or {}
            wiki_config = kb_config.get("wiki") or {}
            if not wiki_config.get("enabled"):
                logger.info("wiki 生成：KB 未启用 wiki，跳过", kb_id=kb_id)
                return {"skipped": "wiki_disabled"}

            # 2. 找到本文档的履历行（入队时已创建）
            record_repo = WikiIngestRecordRepository(session)
            record = await _find_pending_record(record_repo, kb_id, document_id)
            if record is None:
                record = await record_repo.create({
                    "space_id": space_id, "kb_id": kb_id, "document_id": document_id,
                })
            record_id = record.id
            record.mark_running()
            await session.commit()

            # 3. per-KB 锁（同 KB 串行；拿不到 → 延后重入队）
            lock_token = await acquire_kb_lock(kb_id)
            if not lock_token:
                raise TransientBusyError("wiki: 同一知识库的上一轮生成仍在进行", defer_seconds=60)

            # 4. 输入收集：parsed_text（MinIO）+ chunks（ES）
            doc_repo = DocumentRepository(session)
            document = await doc_repo.get_by_id(document_id)
            if not document:
                record.mark_failed("文档不存在")
                await session.commit()
                return {"skipped": "document_not_found"}

            full_text = await _load_parsed_text(document)

            from novamind.shared.storage.client_factory import ClientFactory
            es_client = await ClientFactory.get_elasticsearch_client()
            chunks_result = await es_client.get_document_chunks(space_id, document_id, skip=0, limit=1000)
            chunks = chunks_result.get("items") or []

            # 5. LLM 客户端（KB 配置的模型，缺省回用户默认）
            model_config_service = ModelConfigService(session)
            llm_client = await _resolve_llm_client(model_config_service, wiki_config, kb.creator_id)

            # 6. 四阶段管道
            svc = WikiIngestService(
                session,
                llm_client=llm_client,
                minio_client=None,  # P1 输入只走 parsed_text，无需额外 MinIO 操作
                es_client=es_client,
                wiki_config=wiki_config,
                kb_id=kb_id,
                space_id=space_id,
                document_id=document_id,
            )
            svc.bind_record(record)
            outcome = await svc.ingest_document(full_text=full_text, chunks=chunks)

            # 6.5 wiki 页 ES 同步（批5 检索对齐：published 页进向量库参与检索）。
            # best-effort：embedding 模型缺失/同步失败不影响管道结果。
            es_synced = await _sync_wiki_pages_to_es(session, kb_id, space_id)

            record.mark_done(outcome.pages_created, outcome.pages_updated)
            await session.commit()
            logger.info(
                "wiki 生成完成",
                kb_id=kb_id, document_id=document_id,
                pages_created=outcome.pages_created, pages_updated=outcome.pages_updated,
            )

            # 7. 终态通知（best-effort，失败不影响结果）
            await _notify_wiki_terminal(
                "completed", user_id=kb.creator_id, kb_id=kb_id, space_id=space_id,
                document_id=document_id, filename=document.filename,
                pages_created=outcome.pages_created, pages_updated=outcome.pages_updated,
            )
            return {
                "pages_created": outcome.pages_created,
                "pages_updated": outcome.pages_updated,
                "truncated": outcome.truncated,
            }

        except TransientBusyError:
            # 拥塞信号：交给 arq 延后重入队（worker 侧统一处理）
            raise
        except WikiGenerationError as e:
            await _fail_record(session, record_id, str(e))
            await _notify_wiki_terminal(
                "failed", user_id=None, kb_id=kb_id, space_id=space_id,
                document_id=document_id, filename="", detail=str(e),
            )
            return {"error": str(e)}
        except Exception as e:
            await _fail_record(session, record_id, f"wiki 生成异常: {e}")
            logger.error("wiki 生成任务失败", kb_id=kb_id, document_id=document_id, error=str(e))
            return {"error": str(e)}
        finally:
            if lock_token:
                await release_kb_lock(kb_id, lock_token)


async def _find_pending_record(record_repo, kb_id: int, document_id: int):
    """找该文档最近一条未终态的履历（入队时创建的 PENDING 行）"""
    from novamind.features.knowledge_space.models.wiki import WikiIngestStatus

    records = await record_repo.list_by_kb(kb_id, limit=10)
    for r in records:
        if r.document_id == document_id and r.status in (WikiIngestStatus.PENDING, WikiIngestStatus.RUNNING):
            return r
    return None


async def _sync_wiki_pages_to_es(session, kb_id: int, space_id: int) -> int:
    """把本 KB 的 published wiki 页同步进 ES（全量收敛，幂等）。

    逐页生成 embedding 后 upsert（wp-{page_id}）；embedding 模型缺失时整体
    跳过（可装配语义）。完成后失效该 KB 的检索缓存。
    """
    try:
        from novamind.features.knowledge_space.models.wiki import WikiPageStatus
        from novamind.features.knowledge_space.repository.wiki_repository import WikiPageRepository
        from novamind.features.knowledge_space.services.wiki_es_sync import WikiEsSyncService
        from novamind.features.user.services.model_config_service import ModelConfigService
        from novamind.shared.storage.client_factory import ClientFactory

        repo = WikiPageRepository(session)
        pages = [
            p for p in await repo.all_live_pages(kb_id)
            if p.status == WikiPageStatus.PUBLISHED and (p.content or "").strip()
        ]
        if not pages:
            return 0

        # 页面向量：用空间 embedding 模型对「title+summary+content 摘样」生成。
        # 内容采样 2000 字符（embedding 输入有长度上限，采样足够检索定位）。
        space_repo = None
        try:
            from novamind.features.knowledge_space.repository.knowledge_space_repository import (
                KnowledgeSpaceRepository,
            )
            space_repo = KnowledgeSpaceRepository(session)
            space = await space_repo.get_by_id(space_id, use_cache=True)
            embedding_model = space.embedding_model if space else None
        except Exception:
            embedding_model = None
        if not embedding_model:
            logger.info("wiki ES 同步跳过：空间未配置 embedding 模型", kb_id=kb_id)
            return 0

        model_config_service = ModelConfigService(session)
        embedding_client = await model_config_service.get_embedding_client_by_model(
            user_id=0, model=embedding_model,
        )
        if not embedding_client:
            logger.info("wiki ES 同步跳过：embedding 客户端解析失败", kb_id=kb_id)
            return 0

        es_client = await ClientFactory.get_elasticsearch_client()
        sync_svc = WikiEsSyncService(session, es_client)

        synced = 0
        for p in pages:
            text = f"{p.title}\n{p.summary or ''}\n{(p.content or '')[:2000]}"
            try:
                vector = await embedding_client.generate_embedding(text)
                ok = await sync_svc.sync_page(space_id, p, embedding=vector)
                if ok:
                    synced += 1
            except Exception as e:
                logger.warning("wiki 页 embedding/同步失败", slug=p.slug, error=str(e))

        if synced:
            await _invalidate_search_cache(kb_id)
            logger.info("wiki 页 ES 同步完成", kb_id=kb_id, synced=synced, total=len(pages))
        return synced
    except Exception as e:
        logger.warning("wiki 页 ES 同步失败（不影响管道）", kb_id=kb_id, error=str(e))
        return 0


async def _invalidate_search_cache(kb_id: int) -> None:
    """失效 KB 级检索缓存（best-effort）"""
    try:
        from novamind.shared.cache.redis_client import get_redis_client

        cache = await get_redis_client()
        await cache.delete_by_pattern(f"search:{kb_id}:*", batch_size=100)
    except Exception as e:
        logger.warning("wiki 检索缓存失效失败", kb_id=kb_id, error=str(e))


async def _load_parsed_text(document) -> str:
    """从 MinIO 读解析全文（storage.parsed_text_object 指针）"""
    from novamind.shared.storage.client_factory import ClientFactory

    storage = document.get_storage_info()
    object_name = storage.get("parsed_text_object")
    if not object_name:
        return ""
    try:
        minio_client = await ClientFactory.get_minio_client()
        data = await minio_client.download_document(
            bucket_name=storage.get("minio_bucket"),
            object_name=object_name,
        )
        return data.decode("utf-8-sig", errors="replace")
    except Exception as e:
        logger.warning("解析全文读取失败", document_id=document.id, error=str(e))
        return ""


async def _resolve_llm_client(model_config_service, wiki_config: dict, fallback_user_id: Optional[int]):
    """优先 wiki.llm.model，缺省回退 KB 创建者的默认 LLM"""
    llm_config = wiki_config.get("llm") or {}
    model_name = llm_config.get("model")
    if not model_name:
        model_name = await model_config_service.get_user_default_model_name(fallback_user_id or 0, "llm")
    if not model_name:
        raise WikiGenerationError("未配置 LLM 模型，请在模型配置中添加")
    return await model_config_service.get_llm_client_by_model(user_id=fallback_user_id or 0, model=model_name)


async def _fail_record(session: AsyncSession, record_id: Optional[int], error: str) -> None:
    """履历标记失败（独立容错：失败处理本身不能抛）"""
    try:
        if record_id is None:
            return
        from novamind.features.knowledge_space.repository.wiki_repository import WikiIngestRecordRepository

        record_repo = WikiIngestRecordRepository(session)
        record = await record_repo.get_by_id(record_id)
        if record:
            record.mark_failed(error[:2000])
            await session.commit()
    except Exception as e:
        logger.warning("wiki 履历标记失败", record_id=record_id, error=str(e))


async def _notify_wiki_terminal(
    status: str,
    *,
    user_id: Optional[int],
    kb_id: int,
    space_id: int,
    document_id: int,
    filename: str = "",
    pages_created: int = 0,
    pages_updated: int = 0,
    detail: str = "",
) -> None:
    """wiki 生成终态通知（仿 _notify_document_terminal，失败静默）"""
    from novamind.features.notification.adapters.notification_port_adapter import (
        as_notification_port,
    )

    if not user_id:
        return
    if status == "completed":
        title = "Wiki 更新完成"
        content = f"本次生成新增 {pages_created} 页、更新 {pages_updated} 页。"
    else:
        title = "Wiki 生成失败"
        content = detail or "Wiki 生成出现问题，请稍后重试或联系管理员。"

    try:
        await as_notification_port(None).send(
            user_id=user_id,
            type="wiki_ready",
            title=title,
            content=content,
            link=f"/home/spaces/{space_id}/knowledge-bases/{kb_id}/wiki",
            extra_data={
                "kb_id": kb_id, "space_id": space_id, "document_id": document_id,
                "status": status,
            },
        )
    except Exception as e:
        logger.warning("wiki 终态通知发送失败", kb_id=kb_id, error=str(e))


async def enqueue_wiki_ingest(
    kb_id: int,
    space_id: int,
    document_id: int,
) -> Optional[str]:
    """入队 wiki 生成任务。

    WikiIngestRecord(PENDING) 行与 arq enqueue 原子提交（失败一起回滚），
    仿 enqueue_process_document 的原子性论证。
    """
    from novamind.core.database.database import get_db_session
    from novamind.features.knowledge_space.models.wiki import WikiIngestStatus
    from novamind.features.knowledge_space.repository.wiki_repository import WikiIngestRecordRepository
    from novamind.shared.mq import get_arq_pool

    pool = await get_arq_pool()

    async with get_db_session() as session:
        record_repo = WikiIngestRecordRepository(session)
        record = await record_repo.create({
            "space_id": space_id, "kb_id": kb_id, "document_id": document_id,
            "status": WikiIngestStatus.PENDING,
        })
        try:
            job = await pool.enqueue_job(
                "process_wiki_ingest_task",
                kb_id=kb_id, space_id=space_id, document_id=document_id,
            )
        except Exception:
            await session.rollback()
            raise
        if job is None:
            # job_id 冲突等场景 enqueue 返回 None
            await session.rollback()
            logger.warning("wiki 任务入队返回 None", kb_id=kb_id, document_id=document_id)
            return None
        record.job_id = job.job_id
        await session.commit()
        return job.job_id


async def process_wiki_retract_task(
    ctx: dict,
    kb_id: int,
    space_id: int,
    document_id: int,
) -> dict:
    """wiki 来源回收任务（arq worker 入口，幂等可重试）。

    删除文档时 delete_document 已同步对账一次；本任务作为异步兜底再跑一遍
    （覆盖同步路径失败/竞态窗口漏网的页面）。失败由 arq 重试，对账幂等。
    """
    from novamind.core.database.database import get_db_session
    from novamind.features.knowledge_space.services.wiki_retract_service import WikiRetractService

    async with get_db_session() as session:
        svc = WikiRetractService(session, kb_id=kb_id, space_id=space_id)
        result = await svc.reconcile_document_removal(document_id)
        await session.commit()

        # 被删页面的 ES 文档一并清理（best-effort）
        if result["deleted"]:
            try:
                from novamind.shared.storage.client_factory import ClientFactory
                from novamind.features.knowledge_space.services.wiki_es_sync import (
                    WikiEsSyncService,
                    wiki_chunk_id,
                )

                es_client = await ClientFactory.get_elasticsearch_client()
                sync_svc = WikiEsSyncService(session, es_client)
                for slug in result["deleted"]:
                    # slug → page_id：软删页需 include_deleted 才查得到
                    page = await svc.page_repo.get_by_slug(kb_id, slug, include_deleted=True)
                    if page:
                        await sync_svc.delete_page(space_id, page.id)
            except Exception as e:
                logger.warning("wiki retract ES 清理失败", kb_id=kb_id, error=str(e))

        if result["deleted"] or result["stripped"]:
            logger.info(
                "wiki retract 对账完成",
                kb_id=kb_id, document_id=document_id,
                deleted=len(result["deleted"]), stripped=len(result["stripped"]),
            )
        return result


async def enqueue_wiki_retract(
    kb_id: int,
    space_id: int,
    document_id: int,
) -> Optional[str]:
    """入队 wiki retract 任务（fire-and-forget：删除主流程不因入队失败阻断）"""
    from novamind.shared.mq import get_arq_pool

    try:
        pool = await get_arq_pool()
        job = await pool.enqueue_job(
            "process_wiki_retract_task",
            kb_id=kb_id, space_id=space_id, document_id=document_id,
        )
        return job.job_id if job else None
    except Exception as e:
        logger.warning(
            "wiki retract 入队失败（同步对账仍在）",
            kb_id=kb_id, document_id=document_id, error=str(e),
        )
        return None
