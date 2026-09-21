"""
简历会话服务：承接路由层的多步原子写与事务边界（commit 归 service 控制，
对齐 docs/transaction-boundary-conventions.md——路由层不做 commit）。
"""
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.app.models.resume import ResumeSessionStatus
from novamind.features.app.repository.resume_repository import ResumeSessionRepository
from novamind.shared.storage.client_factory import get_minio_client
from sqlalchemy.ext.asyncio import AsyncSession

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
        jd_text: str | None,
        cfg: dict[str, Any],
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

    # ==================== 读侧（批次 4 自路由层下沉） ====================

    async def list_user_sessions(
        self, user_id: int, limit: int, offset: int, status: int | None = None,
    ):
        """用户会话分页列表。Returns: (sessions, total)。"""
        return await self.repo.list_by_user(user_id, limit, offset, status=status)

    async def get_owned_session(self, session_id: str, user_id: int):
        """取会话并校验归属（不存在/非本人抛 ResumeSessionNotFoundError）。"""
        from novamind.features.app.api.exceptions import ResumeSessionNotFoundError

        session = await self.repo.get_by_id(session_id)
        if not session or session.user_id != user_id:
            raise ResumeSessionNotFoundError(session_id)
        return session

    async def get_cancellable_session(self, session_id: str, user_id: int):
        """取会话并校验归属 + 可取消状态（PARSING/ANALYZING/PROBING）。

        状态不允许取消时抛 ResumeParseError。
        """
        from novamind.features.app.api.exceptions import ResumeParseError

        session = await self.get_owned_session(session_id, user_id)
        if session.status not in (
            ResumeSessionStatus.PARSING,
            ResumeSessionStatus.ANALYZING,
            ResumeSessionStatus.PROBING,
        ):
            raise ResumeParseError("当前会话状态不允许取消")
        return session

    async def read_report(self, session_id: str, user_id: int) -> tuple[bytes, str]:
        """读报告 MD 内容。Returns: (content, report_filename)。

        报告未生成/MinIO 读取失败抛 ResumeParseError。
        """
        from novamind.features.app.api.exceptions import ResumeParseError

        session = await self.get_owned_session(session_id, user_id)
        if not session.md_report_url:
            raise ResumeParseError("报告尚未生成")

        try:
            minio_client = await get_minio_client()
            content = await minio_client.download_document(
                minio_client.default_bucket, session.md_report_url
            )
        except Exception as e:
            logger.error("从 MinIO 读取报告失败", session_id=session_id, error=str(e))
            raise ResumeParseError("报告读取失败")
        filename = (session.resume_filename or "resume").rsplit(".", 1)[0] + "_report.md"
        return content, filename


__all__ = ["ResumeSessionService"]