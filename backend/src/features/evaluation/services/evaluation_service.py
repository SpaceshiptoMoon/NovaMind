"""
测评核心编排服务

负责：测试集管理 → 创建任务 → 异步执行（并发+进度）→ 结果存 MinIO → 人工评分
"""
import asyncio
import hashlib
import json
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from novamind.features.evaluation.models.evaluation_task import (
    EvaluationStatus,
)
from novamind.features.evaluation.repository.evaluation_repository import (
    EvaluationTestSetRepository,
    EvaluationTaskRepository,
)
from novamind.features.evaluation.schemas.evaluation_schema import EvaluationConfig
from novamind.features.evaluation.services.retrieval_evaluator import RetrievalEvaluator
from novamind.features.evaluation.services.generation_evaluator import GenerationEvaluator
from novamind.features.evaluation.services.embedding_evaluator import EmbeddingEvaluator
from novamind.features.evaluation.services.claim_decomposer import ClaimDecomposer
from novamind.features.evaluation.services.test_set_parser import parse_test_set
from novamind.features.evaluation.services.result_exporter import result_to_json_bytes, result_to_csv
from novamind.features.evaluation.api.exceptions import (
    EvaluationTaskNotFoundError,
    EvaluationTestSetNotFoundError,
    EvaluationTaskPendingError,
    EvaluationTaskNotCancellableError,
    EvaluationTaskNotCompletedError,
)
from novamind.shared.ai_models.base_model import BaseLLM
from novamind.shared.prompts.templates import PromptTemplate, PromptManager
from novamind.shared.storage.minio_client import MinioClient
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

MAX_ERROR_LENGTH = 2000
EVALUATION_CONCURRENCY = 5

# 注意：这是单 worker 进程内的 asyncio.Task 跟踪字典。
# 在多 worker（多进程）部署场景下，此字典无法跨 worker 共享任务状态。
# cancel_task() 已通过数据库状态标记实现了跨 worker 取消的优雅降级：
#   - 若目标 asyncio.Task 在当前 worker 内，直接 cancel()
#   - 若不在当前 worker，数据库 status 已标记为 CANCELLED，远端 worker 的
#     DB 检查点会自然停止任务
# 若需要跨 worker 共享任务进度/状态（如实时进度查询），需迁移至 Redis。
_running_tasks: Dict[int, asyncio.Task] = {}


class EvaluationService:
    """测评编排服务"""

    def __init__(
        self,
        db: AsyncSession,
        search_service: Any,
        model_config_service: Any,
        minio_client: MinioClient,
    ):
        self.db = db
        self.test_set_repo = EvaluationTestSetRepository(db)
        self.task_repo = EvaluationTaskRepository(db)
        self.search_service = search_service
        self.model_config_service = model_config_service
        self.minio_client = minio_client

    # ========== 测试集管理 ==========

    async def create_test_set(
        self,
        space_id: int,
        kb_id: int,
        user_id: int,
        name: str,
        file_content: bytes,
        filename: str,
    ) -> Any:
        test_set = parse_test_set(file_content, filename)
        total_cases = len(test_set.test_cases)
        file_hash = hashlib.sha256(file_content).hexdigest()
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "json"

        test_set_obj = await self.test_set_repo.create(
            space_id=space_id, kb_id=kb_id, creator_id=user_id,
            name=name, filename=filename, file_type=ext,
            file_size=len(file_content), file_hash=file_hash,
            storage={}, total_cases=total_cases,
        )

        upload_result = await self.minio_client.upload_document(
            space_id=space_id, kb_id=kb_id,
            document_id=test_set_obj.id,
            file_data=file_content, filename=filename, file_hash=file_hash,
        )
        test_set_obj.set_minio_info(
            bucket=upload_result["bucket"],
            object_name=upload_result["object_name"],
            etag=upload_result.get("etag"),
        )
        await self.db.commit()
        return test_set_obj

    async def get_test_set(self, test_set_id: int) -> Optional[Any]:
        return await self.test_set_repo.get_by_id(test_set_id)

    async def get_test_set_by_kb(self, test_set_id: int, space_id: int, kb_id: int) -> Optional[Any]:
        return await self.test_set_repo.get_by_id_and_kb(test_set_id, space_id, kb_id)

    async def list_test_sets(
        self, space_id: int, kb_id: int, skip: int = 0, limit: int = 20
    ) -> Tuple[list, int]:
        test_sets = await self.test_set_repo.list_by_kb(kb_id, space_id, skip, limit)
        total = await self.test_set_repo.count_by_kb(kb_id, space_id)
        return test_sets, total

    async def update_test_set(
        self, test_set_id: int, space_id: int, kb_id: int, name: str
    ) -> Any:
        test_set_obj = await self.test_set_repo.get_by_id_and_kb(test_set_id, space_id, kb_id)
        if not test_set_obj:
            raise EvaluationTestSetNotFoundError(test_set_id)
        test_set_obj.name = name
        await self.db.commit()
        await self.db.refresh(test_set_obj)
        return test_set_obj

    async def get_test_set_cases(
        self, test_set_id: int, space_id: int, kb_id: int
    ) -> Optional[Tuple[Any, List[Dict]]]:
        test_set_obj = await self.test_set_repo.get_by_id_and_kb(test_set_id, space_id, kb_id)
        if not test_set_obj:
            raise EvaluationTestSetNotFoundError(test_set_id)

        file_content = await self.minio_client.download_document(
            test_set_obj.get_minio_bucket(),
            test_set_obj.get_minio_object_name(),
        )
        test_set = parse_test_set(file_content, test_set_obj.filename)
        cases = [{"question": c.question, "expected_answer": c.expected_answer} for c in test_set.test_cases]
        return test_set_obj, cases

    async def delete_test_set(self, test_set_id: int) -> bool:
        test_set_obj = await self.test_set_repo.get_by_id(test_set_id)
        if not test_set_obj:
            raise EvaluationTestSetNotFoundError(test_set_id)

        has_active = await self.test_set_repo.has_active_tasks(test_set_id)
        if has_active:
            raise EvaluationTaskPendingError(test_set_id)

        # 先保存 MinIO 信息，删除数据库记录后仍可用于清理文件
        bucket = test_set_obj.get_minio_bucket()
        object_name = test_set_obj.get_minio_object_name()

        tasks = await self.task_repo.list_by_test_set(test_set_id)
        task_result_files = []
        for task in tasks:
            tb = task.get_result_minio_bucket()
            to = task.get_result_minio_object_name()
            if tb and to:
                task_result_files.append((tb, to))

        # 先删数据库记录并 commit，确保不留孤儿记录
        result = await self.test_set_repo.delete(test_set_id)
        await self.db.commit()

        # 数据库删除成功后再清理 MinIO 文件，失败只记 warning
        if bucket and object_name:
            try:
                await self.minio_client.delete_document(bucket, object_name)
            except Exception as e:
                logger.warning("删除测试集文件失败（可后续手动清理）", test_set_id=test_set_id, error=str(e))

        for tb, to in task_result_files:
            try:
                await self.minio_client.delete_document(tb, to)
            except Exception as e:
                logger.warning("删除任务结果文件失败（可后续手动清理）", error=str(e))

        return result

    # ========== 测评任务管理 ==========

    async def create_task(
        self,
        test_set_id: int,
        user_id: int,
        name: str,
        config: Optional[dict] = None,
    ) -> Any:
        if config:
            EvaluationConfig(**config)

        task = await self.task_repo.create(
            test_set_id=test_set_id, user_id=user_id, name=name, config=config,
        )
        await self.db.commit()

        bg_task = asyncio.create_task(
            self._run_evaluation(task.id, user_id)
        )
        _running_tasks[task.id] = bg_task

        def _on_task_done(t: asyncio.Task, tid: int = task.id):
            _running_tasks.pop(tid, None)
            if t.cancelled():
                logger.info("测评任务被取消", task_id=tid)
            elif exc := t.exception():
                logger.error("测评后台任务异常退出", task_id=tid, error=str(exc))

        bg_task.add_done_callback(_on_task_done)

        return task

    async def get_task(self, task_id: int) -> Optional[Any]:
        return await self.task_repo.get_by_id(task_id)

    async def get_task_by_kb(self, task_id: int, space_id: int, kb_id: int) -> Optional[Any]:
        return await self.task_repo.get_by_id_and_kb(task_id, space_id, kb_id)

    async def list_tasks(
        self, space_id: int, kb_id: int, skip: int = 0, limit: int = 20, status: Optional[int] = None
    ) -> Tuple[list, int]:
        tasks = await self.task_repo.list_by_kb(kb_id, space_id, skip, limit, status=status)
        total = await self.task_repo.count_by_kb(kb_id, space_id, status=status)
        return tasks, total

    async def delete_task(self, task_id: int) -> bool:
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            raise EvaluationTaskNotFoundError(task_id)
        if task.status in (EvaluationStatus.PENDING, EvaluationStatus.RUNNING):
            raise EvaluationTaskPendingError(task_id)

        # 先保存 MinIO 信息，删除数据库记录后仍可用于清理文件
        bucket = task.get_result_minio_bucket()
        object_name = task.get_result_minio_object_name()

        # 先删数据库记录并 commit，确保不留孤儿记录
        result = await self.task_repo.delete(task_id)
        await self.db.commit()

        # 数据库删除成功后再清理 MinIO 文件，失败只记 warning
        if bucket and object_name:
            try:
                await self.minio_client.delete_document(bucket, object_name)
            except Exception as e:
                logger.warning("删除任务结果文件失败（可后续手动清理）", task_id=task_id, error=str(e))

        return result

    async def cancel_task(self, task_id: int) -> Any:
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            raise EvaluationTaskNotFoundError(task_id)
        if task.status not in (EvaluationStatus.PENDING, EvaluationStatus.RUNNING):
            status_name = EvaluationStatus(task.status).name.lower()
            raise EvaluationTaskNotCancellableError(task_id, status_name)

        task.status = EvaluationStatus.CANCELLED
        task.error_message = "用户取消"
        await self.db.commit()
        await self.db.refresh(task)

        # 取消正在运行的 asyncio.Task（如果在本 worker 中）
        bg_task = _running_tasks.get(task_id)
        if bg_task and not bg_task.done():
            bg_task.cancel()
        else:
            # 多 worker 部署时，任务可能运行在其他 worker 上，
            # 此时数据库状态已标记为 CANCELLED，后台 worker 在下一个检查点会自然停止
            logger.info(
                "取消请求已记录，后台任务不在当前 worker（将在下一个检查点停止）",
                task_id=task_id,
            )

        return task

    async def get_task_progress(self, task_id: int) -> Optional[Dict[str, Any]]:
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            raise EvaluationTaskNotFoundError(task_id)
        progress = task.progress or {}
        return {
            "task_id": task.id,
            "status": EvaluationStatus(task.status).name.lower(),
            "current": progress.get("current", 0),
            "total": progress.get("total", 0),
        }

    async def submit_human_scores(
        self, task_id: int, scores: List[Dict[str, Any]]
    ) -> int:
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            raise EvaluationTaskNotFoundError(task_id)
        if task.status != EvaluationStatus.COMPLETED:
            status_name = EvaluationStatus(task.status).name.lower()
            raise EvaluationTaskNotCompletedError(task_id, status_name)

        result_data = await self._download_task_result(task)
        if result_data is None:
            logger.error("提交人工评分时下载任务结果失败，可能为存储异常", task_id=task_id)
            return 0

        details = result_data.get("details", [])
        updated = 0
        for score_item in scores:
            index = score_item.get("index", -1)
            if 0 <= index < len(details):
                details[index]["human_score"] = score_item.get("score")
                details[index]["human_comment"] = score_item.get("comment")
                updated += 1

        result_data["details"] = details

        scored = [d for d in details if d.get("human_score") is not None]
        if scored:
            avg = sum(d["human_score"] for d in scored) / len(scored)
            result_data.setdefault("summary", {})["human_scores"] = {
                "scored_count": len(scored),
                "average": round(avg, 2),
            }

        await self._upload_task_result(task, result_data)
        await self.db.commit()
        return updated

    async def get_report(self, task_id: int) -> Optional[Dict[str, Any]]:
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            raise EvaluationTaskNotFoundError(task_id)

        result_data = await self._download_task_result(task)
        test_set_obj = task.test_set
        summary = (result_data or {}).get("summary", {})
        details = (result_data or {}).get("details", [])

        return {
            "task_id": task.id,
            "name": task.name,
            "status": EvaluationStatus(task.status).name.lower(),
            "total_cases": test_set_obj.total_cases if test_set_obj else 0,
            "completed_cases": summary.get("processed_cases", 0),
            "summary": summary,
            "details": details,
        }

    async def export_result(self, task_id: int, format: str = "json") -> Optional[Tuple[bytes, str]]:
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            raise EvaluationTaskNotFoundError(task_id)

        result_data = await self._download_task_result(task)
        if not result_data:
            return None

        task_name = task.name or f"task_{task_id}"

        if format == "csv":
            csv_content = result_to_csv(result_data)
            return csv_content.encode("utf-8-sig"), f"{task_name}.csv"
        else:
            json_bytes = result_to_json_bytes(result_data)
            return json_bytes, f"{task_name}.json"

    # ========== 异步执行 ==========

    async def _run_evaluation(self, task_id: int, user_id: int) -> None:
        from novamind.core.database.database import get_db_session
        async with get_db_session() as session:
            task_repo = EvaluationTaskRepository(session)
            test_set_repo = EvaluationTestSetRepository(session)
            try:
                task = await task_repo.get_by_id(task_id)
                if not task or task.status == EvaluationStatus.CANCELLED:
                    return

                test_set_obj = await test_set_repo.get_by_id(task.test_set_id)
                if not test_set_obj:
                    return

                config = EvaluationConfig(**(task.config or {}))

                # 标记为 RUNNING
                await task_repo.update_status(task_id, EvaluationStatus.RUNNING)
                await task_repo.update_progress(task_id, {"current": 0, "total": 0})
                await session.commit()

                # 从 MinIO 下载测试集
                file_content = await self.minio_client.download_document(
                    test_set_obj.get_minio_bucket(),
                    test_set_obj.get_minio_object_name(),
                )
                test_set = parse_test_set(file_content, test_set_obj.filename)
                cases = [{"question": c.question, "expected_answer": c.expected_answer} for c in test_set.test_cases]

                await task_repo.update_progress(task_id, {"current": 0, "total": len(cases)})
                await session.commit()

                # 创建评估器
                llm_client, resolved_llm_model = await self._get_llm_client(user_id, config.llm_model)
                embedding_client, resolved_embedding_model = await self._get_embedding_client(user_id, config.embedding_model)

                # 客户端不可用时直接失败
                if llm_client is None and embedding_client is None:
                    raise RuntimeError(f"无法获取 LLM 和 Embedding 客户端，测评任务 {task_id} 无法执行")

                # 部分客户端获取失败时记录警告
                if llm_client is None or embedding_client is None:
                    logger.warning("部分模型客户端获取失败", has_llm=llm_client is not None, has_embedding=embedding_client is not None)

                # 用后台任务的独立 session 创建 SearchService，避免共享请求级 session
                from novamind.features.knowledge_space.services.search_service import SearchService
                from novamind.shared.clients import get_elasticsearch_client
                from novamind.features.user.services.model_config_service import ModelConfigService
                bg_es_client = await get_elasticsearch_client()
                bg_model_config_service = ModelConfigService(session)
                bg_search_service = SearchService(session, bg_es_client, bg_model_config_service)

                # 回写实际使用的模型名
                config_changed = False
                if resolved_llm_model and config.llm_model != resolved_llm_model:
                    config.llm_model = resolved_llm_model
                    config_changed = True
                if resolved_embedding_model and config.embedding_model != resolved_embedding_model:
                    config.embedding_model = resolved_embedding_model
                    config_changed = True
                if config_changed:
                    task.config = config.model_dump()
                    flag_modified(task, "config")
                    await session.flush()

                embedding_eval = EmbeddingEvaluator(embedding_client) if embedding_client else None
                claim_decomposer = ClaimDecomposer(llm_client) if llm_client else None

                retrieval_evaluator = RetrievalEvaluator(
                    llm_client=llm_client, embedding_evaluator=embedding_eval,
                )
                generation_evaluator = GenerationEvaluator(
                    llm_client=llm_client, embedding_evaluator=embedding_eval,
                    claim_decomposer=claim_decomposer,
                )

                # 并发评估
                start_time = time.time()
                semaphore = asyncio.Semaphore(EVALUATION_CONCURRENCY)
                cancel_event = asyncio.Event()

                async def evaluate_case(i: int, case: Dict) -> Tuple[int, Dict]:
                    async with semaphore:
                        # 检查共享取消信号
                        if cancel_event.is_set():
                            return i, {"index": i, "question": case["question"],
                                       "expected_answer": case["expected_answer"], "cancelled": True}
                        # DB 取消检查
                        t = await task_repo.get_by_id(task_id)
                        if t and t.status == EvaluationStatus.CANCELLED:
                            cancel_event.set()
                            return i, {"index": i, "question": case["question"],
                                       "expected_answer": case["expected_answer"], "cancelled": True}
                        try:
                            detail = await self._evaluate_single_case(
                                index=i, question=case["question"],
                                expected_answer=case["expected_answer"],
                                test_set_obj=test_set_obj, config=config,
                                retrieval_evaluator=retrieval_evaluator,
                                generation_evaluator=generation_evaluator,
                                embedding_evaluator=embedding_eval,
                                llm_client=llm_client, user_id=user_id,
                                search_service=bg_search_service,
                            )
                            return i, detail
                        except Exception as e:
                            logger.error("测试用例评估失败", index=i, error=str(e))
                            return i, {"index": i, "question": case["question"],
                                       "expected_answer": case["expected_answer"], "error": str(e)}

                coros = [evaluate_case(i, case) for i, case in enumerate(cases)]
                details = []
                completed = 0
                commit_interval = 5

                for coro in asyncio.as_completed(coros):
                    i, detail = await coro
                    details.append(detail)
                    completed += 1
                    if completed % commit_interval == 0:
                        await task_repo.update_progress(task_id, {"current": completed, "total": len(cases)})
                        await session.commit()

                # as_completed 返回顺序不确定，按 index 排序
                details.sort(key=lambda d: d.get("index", 0))

                # 实际完成的用例数（用于取消时进度一致性）
                actual_completed = completed

                # ---- 检查点：所有 case 完成后、汇总计算前 ----
                task = await task_repo.get_by_id(task_id)
                if task and task.status == EvaluationStatus.CANCELLED:
                    logger.info("测评任务已取消（汇总前）", task_id=task_id)
                    await task_repo.update_progress(task_id, {"current": actual_completed, "total": len(cases)})
                    await session.commit()
                    return

                # 更新最终进度
                successful = [d for d in details if "cancelled" not in d and "error" not in d]
                await task_repo.update_progress(task_id, {"current": len(details), "total": len(cases)})

                elapsed = round(time.time() - start_time, 1)

                retrieval_results = [d.get("retrieval", {}) for d in details if "cancelled" not in d and "error" not in d]

                retrieval_summary = RetrievalEvaluator.compute_aggregate_metrics(
                    retrieval_results, enable_mrr=config.enable_mrr,
                )

                gen_scores = {"faithfulness": [], "answer_relevance": [], "correctness": [], "quality": []}
                for d in details:
                    gs = d.get("generation_scores", {})
                    for key in gen_scores:
                        val = gs.get(key)
                        if isinstance(val, tuple):
                            val = val[0]
                        if isinstance(val, (int, float)):
                            gen_scores[key].append(val)

                generation_summary = {}
                for key, scores in gen_scores.items():
                    if scores:
                        generation_summary[key] = round(sum(scores) / len(scores), 1)
                if generation_summary:
                    all_scores = [v for v in generation_summary.values() if isinstance(v, (int, float))]
                    generation_summary["overall"] = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0

                end_to_end = {}
                if config.enable_context_precision:
                    cp_values = [d.get("end_to_end", {}).get("context_precision") for d in details if "cancelled" not in d and "error" not in d]
                    cp_values = [v for v in cp_values if v is not None]
                    end_to_end["context_precision"] = round(sum(cp_values) / len(cp_values), 4) if cp_values else None
                if config.enable_answer_similarity and embedding_eval:
                    sim_values = [d.get("end_to_end", {}).get("answer_similarity") for d in details if "cancelled" not in d and "error" not in d]
                    sim_values = [v for v in sim_values if v is not None]
                    end_to_end["answer_similarity"] = round(sum(sim_values) / len(sim_values), 4) if sim_values else None

                result_data = {
                    "summary": {
                        "total_cases": len(cases),
                        "processed_cases": len(details),
                        "successful_cases": len(successful),
                        "retrieval": retrieval_summary,
                        "generation": generation_summary,
                        "end_to_end": end_to_end,
                        "human_scores": None,
                        "elapsed_seconds": elapsed,
                    },
                    "details": details,
                }

                # ---- 检查点：汇总计算后、MinIO 上传前 ----
                task = await task_repo.get_by_id(task_id)
                if task and task.status == EvaluationStatus.CANCELLED:
                    logger.info("测评任务已取消（上传前）", task_id=task_id)
                    await task_repo.update_progress(task_id, {"current": actual_completed, "total": len(cases)})
                    await session.commit()
                    return

                result_bytes = result_to_json_bytes(result_data)
                result_hash = hashlib.sha256(result_bytes).hexdigest()

                upload_result = await self.minio_client.upload_document(
                    space_id=test_set_obj.space_id, kb_id=test_set_obj.kb_id,
                    document_id=task.id, file_data=result_bytes,
                    filename="result.json", file_hash=result_hash,
                )

                task.set_result_minio_info(
                    bucket=upload_result["bucket"],
                    object_name=upload_result["object_name"],
                    etag=upload_result.get("etag"),
                )
                flag_modified(task, "result_storage")

                # ---- 检查点：MinIO 上传后、最终状态更新前 ----
                task = await task_repo.get_by_id(task_id)
                if task and task.status == EvaluationStatus.CANCELLED:
                    logger.info("测评任务已取消（状态更新前）", task_id=task_id)
                    await session.commit()
                    return

                await task_repo.update_status(task_id, EvaluationStatus.COMPLETED)
                await session.commit()

                logger.info("测评任务完成", task_id=task_id, elapsed=elapsed)

            except Exception as e:
                tb = traceback.format_exc()
                logger.error("测评任务执行失败", task_id=task_id, error=str(e), traceback=tb)
                error_msg = str(e)[:MAX_ERROR_LENGTH]
                try:
                    t = await task_repo.get_by_id(task_id)
                    if t and t.status != EvaluationStatus.CANCELLED:
                        await task_repo.update_error(task_id, error_msg)
                    await session.commit()
                except Exception as e2:
                    logger.error("更新错误状态失败", task_id=task_id, error=str(e2))

    async def _evaluate_single_case(
        self,
        index: int,
        question: str,
        expected_answer: str,
        test_set_obj: Any,
        config: EvaluationConfig,
        retrieval_evaluator: RetrievalEvaluator,
        generation_evaluator: GenerationEvaluator,
        embedding_evaluator: Optional[EmbeddingEvaluator],
        llm_client: Optional[BaseLLM],
        user_id: int,
        search_service: Any = None,
    ) -> Dict[str, Any]:
        detail: Dict[str, Any] = {
            "index": index, "question": question, "expected_answer": expected_answer,
        }

        from novamind.features.knowledge_space.schemas.search_schema import SearchRequest, SearchMode

        search_request = SearchRequest(
            query=question,
            search_mode=SearchMode(config.search_mode),
            top_k=config.top_k,
            score_threshold=config.score_threshold,
        )
        svc = search_service or self.search_service
        search_result = await svc.search(
            space_id=test_set_obj.space_id, kb_id=test_set_obj.kb_id,
            user_id=user_id, request=search_request,
        )

        chunks = search_result.get("results", [])
        chunk_list = [
            {"chunk_id": c.get("chunk_id", ""), "content": c.get("content", ""), "score": c.get("score", 0)}
            for c in chunks
        ]
        detail["retrieved_chunks"] = chunk_list

        retrieval_result = await retrieval_evaluator.evaluate(
            question=question, chunks=chunk_list,
            strategy=config.retrieval_relevance_strategy,
        )
        detail["retrieval"] = retrieval_result

        generated_answer = None
        if config.enable_generation:
            generated_answer = await self._generate_answer(
                question=question, chunks=chunk_list, llm_client=llm_client,
            )
            detail["generated_answer"] = generated_answer

        if generated_answer and config.scoring_dimensions:
            gen_scores = await generation_evaluator.evaluate(
                question=question, expected_answer=expected_answer,
                generated_answer=generated_answer, context_chunks=chunk_list,
                config=config.model_dump(),
            )
            detail["generation_scores"] = gen_scores

        end_to_end = {}
        if config.enable_context_precision:
            end_to_end["context_precision"] = retrieval_result.get("precision_at_k")

        if config.enable_context_recall:
            cr_result = await retrieval_evaluator.evaluate_context_recall(
                question=question, expected_answer=expected_answer,
                chunks=chunk_list, strategy=config.retrieval_relevance_strategy,
            )
            end_to_end["context_recall"] = cr_result.get("context_recall") if cr_result else None

        if config.enable_answer_similarity and embedding_evaluator and generated_answer:
            sim = await embedding_evaluator.compute_similarity(generated_answer, expected_answer)
            end_to_end["answer_similarity"] = round(sim, 4)

        detail["end_to_end"] = end_to_end
        detail["human_score"] = None
        detail["human_comment"] = None
        return detail

    # ========== MinIO 辅助方法 ==========

    async def _download_task_result(self, task: Any) -> Optional[Dict[str, Any]]:
        bucket = task.get_result_minio_bucket()
        object_name = task.get_result_minio_object_name()
        if not bucket or not object_name:
            return None
        try:
            content = await self.minio_client.download_document(bucket, object_name)
            return json.loads(content.decode("utf-8"))
        except Exception as e:
            logger.error("下载任务结果失败（MinIO 异常）", task_id=task.id, error=str(e))
            return None

    async def _upload_task_result(self, task: Any, result_data: Dict[str, Any]) -> None:
        test_set_obj = task.test_set
        result_bytes = result_to_json_bytes(result_data)
        result_hash = hashlib.sha256(result_bytes).hexdigest()

        upload_result = await self.minio_client.upload_document(
            space_id=test_set_obj.space_id, kb_id=test_set_obj.kb_id,
            document_id=task.id, file_data=result_bytes,
            filename="result.json", file_hash=result_hash,
        )
        task.set_result_minio_info(
            bucket=upload_result["bucket"],
            object_name=upload_result["object_name"],
            etag=upload_result.get("etag"),
        )
        flag_modified(task, "result_storage")

    async def _delete_task_result_file(self, task: Any) -> None:
        bucket = task.get_result_minio_bucket()
        object_name = task.get_result_minio_object_name()
        if bucket and object_name:
            try:
                await self.minio_client.delete_document(bucket, object_name)
            except Exception as e:
                logger.warning("删除结果文件失败", task_id=task.id, error=str(e))

    # ========== LLM / Embedding 客户端 ==========

    async def _generate_answer(
        self,
        question: str,
        chunks: List[Dict[str, Any]],
        llm_client: Optional[BaseLLM] = None,
    ) -> Optional[str]:
        if not llm_client:
            return None

        context_text = "\n\n".join(
            f"[{i + 1}] {c.get('content', '')}" for i, c in enumerate(chunks)
        )
        prompt = PromptManager.format_prompt(
            PromptTemplate.EVAL_GENERATE_ANSWER.value,
            context_text=context_text,
            question=question,
        )

        try:
            return await llm_client.generate_text(prompt=prompt, max_tokens=1024, temperature=0.3)
        except Exception as e:
            logger.warning("生成回答失败", error=str(e))
            return None

    async def _get_llm_client(self, user_id: int, model: Optional[str] = None) -> tuple:
        try:
            if not model:
                model = await self.model_config_service.get_user_default_model_name(user_id, "llm")
            if model:
                client = await self.model_config_service.get_llm_client_by_model(user_id, model)
                return (client, model)
            return (None, None)
        except Exception as e:
            logger.warning("获取 LLM 客户端失败", error=str(e))
            return (None, None)

    async def _get_embedding_client(self, user_id: int, model: Optional[str] = None) -> tuple:
        try:
            if not model:
                model = await self.model_config_service.get_user_default_model_name(user_id, "embedding")
            if model:
                client = await self.model_config_service.get_embedding_client_by_model(user_id, model)
                return (client, model)
            return (None, None)
        except Exception as e:
            logger.warning("获取 Embedding 客户端失败", error=str(e))
            return (None, None)

    # ========== 孤儿任务恢复 ==========

    @staticmethod
    async def recover_orphan_tasks() -> int:
        """恢复超时的 PENDING 和 RUNNING 任务（启动时调用）"""
        from novamind.core.database.database import get_db_session
        recovered = 0
        async with get_db_session() as session:
            task_repo = EvaluationTaskRepository(session)
            try:
                orphans = await task_repo.get_orphan_tasks(pending_timeout_minutes=10, running_timeout_minutes=30)
                for task in orphans:
                    task.status = EvaluationStatus.FAILED
                    task.error_message = "任务因服务重启被中断"
                    recovered += 1
                    logger.info("恢复孤儿任务", task_id=task.id)
                if orphans:
                    await session.commit()
            except Exception as e:
                logger.error("恢复孤儿任务失败", error=str(e), recovered=recovered)
        return recovered
