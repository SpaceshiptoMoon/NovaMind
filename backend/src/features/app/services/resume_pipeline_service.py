"""
简历挖掘 Pipeline 服务

从 routes.py 中提取的后台 pipeline 逻辑，
支持 S1-S12 全流程执行、阶段间取消检查。
"""
from typing import Optional

from novamind.core.database.database import get_db_session
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.app.models.resume import ResumeSessionStatus
from novamind.features.app.repository.resume_repository import ResumeSessionRepository
from novamind.features.app.services.resume_parser import ResumeParser
from novamind.features.app.services.resume_analyzer import ResumeAnalyzer
from novamind.features.app.services.resume_probing import AutoProbingEngine
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.clients import get_minio_client
from novamind.shared.mq.task_tracker import is_resume_cancelled

logger = get_logger(__name__)


class ResumePipelineService:
    """简历挖掘全流程服务（供 arq worker 调用）"""

    @staticmethod
    async def execute_pipeline(
        session_id: str,
        user_id: int,
        llm_model: str,
        jd_text: Optional[str],
        config: dict,
        file_bytes: bytes,
        filename: str,
    ) -> None:
        """
        执行完整的 S1-S12 简历挖掘 pipeline。

        使用独立的 get_db_session()，与请求上下文解耦。
        在每个阶段之间检查取消标记。

        Args:
            session_id: 简历会话 ID
            user_id: 用户 ID
            llm_model: LLM 模型名称
            jd_text: 岗位描述文本（可选）
            config: 前端传入的配置参数
            file_bytes: 简历文件二进制内容
            filename: 文件名
        """
        async with get_db_session() as db:
            bg_model_config_service = ModelConfigService(db)
            llm = await bg_model_config_service.get_llm_client_by_model(user_id, llm_model)
            repo = ResumeSessionRepository(db)

            # ── S1-S4: 解析简历 ──
            parser = ResumeParser(llm)
            structured = await parser.parse(file_bytes, filename)
            logger.info("S1-S4 简历解析完成", session_id=session_id)

            # 取消检查
            if await is_resume_cancelled(session_id):
                await _mark_cancelled(repo, session_id, db)
                return

            await repo.update(session_id, {
                "structured_resume": structured.model_dump(),
                "status": ResumeSessionStatus.ANALYZING,
            })
            await db.commit()

            # ── S5-S9: 分析报告 ──
            analyzer = ResumeAnalyzer(llm)
            result = await analyzer.analyze(structured, jd_text, config)
            logger.info("S5-S9 分析报告完成", session_id=session_id)

            # 存中间报告到 MinIO
            intermediate_report = result["md_report"]
            report_path = None
            try:
                bg_minio = await get_minio_client()
                report_path = f"resume/{session_id}/report.md"
                await bg_minio.upload_file(report_path, intermediate_report.encode("utf-8"), content_type="text/markdown")
            except Exception as e:
                logger.warning("中间报告上传 MinIO 失败", session_id=session_id, error=str(e))

            # 取消检查
            if await is_resume_cancelled(session_id):
                await _mark_cancelled(repo, session_id, db)
                return

            await repo.update(session_id, {
                "md_report_url": report_path,
                "status": ResumeSessionStatus.PROBING,
            })
            await db.commit()

            # ── S10: 自动追问 ──
            probing_plan = result["probing_plan"]
            jd_analysis_obj = result["jd_analysis"]
            prefix_knowledge_objs = result["prefix_knowledge"]
            work_units = probing_plan.work_units

            engine = AutoProbingEngine(llm, user_id=user_id, bg_db=db)
            qa_records = await engine.probe_all(
                session_id, structured, probing_plan, jd_analysis_obj, db,
            )
            logger.info("S10 自动追问完成", session_id=session_id, kp_count=len(qa_records))

            # ── S11: 面试准备建议 ──
            preparation_advice = await engine.generate_evaluation(qa_records, structured)
            logger.info("S11 面试准备建议完成", session_id=session_id)

            # ── S11-NEW: 简历优化建议 ──
            resume_advice = await engine.generate_resume_advice(qa_records, structured)
            logger.info("S11-NEW 简历优化建议完成", session_id=session_id)

            # 取消检查（最终阶段前）
            if await is_resume_cancelled(session_id):
                await _mark_cancelled(repo, session_id, db)
                return

            # ── S12: 组装最终报告 ──
            final_report = analyzer._assemble_final_md_report(
                structured, jd_analysis_obj, probing_plan,
                work_units, prefix_knowledge_objs,
                qa_records, preparation_advice, resume_advice,
            )

            # 存最终报告到 MinIO
            final_report_path = f"resume/{session_id}/report.md"
            minio_upload_ok = True
            try:
                bg_minio = await get_minio_client()
                await bg_minio.upload_file(final_report_path, final_report.encode("utf-8"), content_type="text/markdown")
            except Exception as e:
                minio_upload_ok = False
                logger.warning("最终报告上传 MinIO 失败", session_id=session_id, error=str(e))

            update_data = {"status": ResumeSessionStatus.COMPLETED}
            if minio_upload_ok:
                update_data["md_report_url"] = final_report_path
            await repo.update(session_id, update_data)
            await db.commit()
            logger.info("Pipeline 全部完成", session_id=session_id, minio_upload_ok=minio_upload_ok)


async def _mark_cancelled(
    repo: ResumeSessionRepository,
    session_id: str,
    db,
) -> None:
    """标记简历会话为已取消"""
    from novamind.shared.mq.task_tracker import clear_resume_cancel_flag

    await clear_resume_cancel_flag(session_id)
    await repo.update(session_id, {
        "status": ResumeSessionStatus.FAILED,
        "error_message": "[用户取消] 简历挖掘已被用户取消",
    })
    await db.commit()
    logger.info("简历管道已取消", session_id=session_id)
