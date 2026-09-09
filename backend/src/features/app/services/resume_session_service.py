"""
简历会话服务：承接路由层的多步原子写与事务边界（commit 归 service 控制，
对齐 docs/transaction-boundary-conventions.md——路由层不做 commit）。
"""
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.app.models.resume import ResumeSessionStatus
from novamind.features.app.repository.resume_repository import ResumeSessionRepository
from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.storage.client_factory import get_minio_client

logger = get_logger(__name__)


class ResumeSessionService:
    """简历会话创建/删除的多步编排（MinIO 副作用 + DB 写入，commit 在此收口）"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ResumeSessionRepository(db)

    async def create_session(
        self,
        user_id: int,
        filename: str,
        jd_text: Optional[str],
        cfg: Dict[str, Any],
        file_bytes: bytes,
    ):
        """创建会话（commit）→ 上传原始文件到 MinIO → 回写 file_url（commit）。

        MinIO 失败不阻断主流程：会话已创建，仅记录 warning 到 config。
        """
        session = await self.repo.create({
            "user_id": user_id,
            "resume_filename": filename,
            "jd_text": jd_text or None,
            "status": ResumeSessionStatus.PARSING,
            "config": cfg,
        })
        await self.db.commit()

        session_id = session.id
        try:
            minio_client = await get_minio_client()
            original_path = f"resume/{session_id}/{filename}"
            await minio_client.upload_file(original_path, file_bytes)
            await self.repo.update(session_id, {"resume_file_url": original_path})
            await self.db.commit()
        except Exception as e:
            logger.warning("原始文件上传 MinIO 失败", session_id=session_id, error=str(e))
            cfg["file_upload_warning"] = "原始文件存储失败，但不影响解析"

        return await self.repo.get_by_id(session_id)

    async def delete_session(self, session_id: str) -> None:
        """删除 MinIO 文件 + DB 会话记录（commit）。MinIO 删除失败仅告警。"""
        session = await self.repo.get_by_id(session_id)
        if session is not None:
            try:
                minio_client = await get_minio_client()
                if session.resume_file_url:
                    await minio_client.delete_document(minio_client.default_bucket, session.resume_file_url)
                if session.md_report_url:
                    await minio_client.delete_document(minio_client.default_bucket, session.md_report_url)
            except Exception as e:
                logger.warning("删除 MinIO 文件失败", session_id=session_id, error=str(e))

        await self.repo.delete_by_id(session_id)
        await self.db.commit()


__all__ = ["ResumeSessionService"]