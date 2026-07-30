"""
附件预签名 URL 注入（宿主展示策略）

从 ``shared/storage/minio_client.py`` 迁出：为消息 ``extra["attachments"]`` 中的图片
附件注入 ``preview_url``（MinIO presigned URL）。这是宿主展示层策略（决定哪些附件
类型生成预览 URL），不属于通用存储客户端，故归 ``features/knowledge_space/adapters/``。

被 ``features/agent/api/routes.py``、``features/qa/api/ai_chat_routes.py``、
``features/qa/api/qa_routes.py`` 消费。放在 knowledge_space adapter 下是因为 agent
与 qa 都已依赖 knowledge_space（批次1 拓扑），避免引入 agent→qa 新耦合。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from novamind_engine_core.storage.minio_client import IMAGE_FILE_TYPES

if TYPE_CHECKING:
    from novamind_engine_core.storage.minio_client import MinioClient


async def enrich_attachments_with_presigned_urls(
    extra: Optional[dict],
    minio_client: "MinioClient",
    bucket: Optional[str] = None,
    expires: int = 3600,
) -> None:
    """为 extra["attachments"] 中的图片附件注入 preview_url（MinIO presigned URL）"""
    if not extra or "attachments" not in extra:
        return
    bucket = bucket or minio_client.default_bucket
    for att in extra["attachments"]:
        if (
            att.get("file_type", "").lower() in IMAGE_FILE_TYPES
            and "storage_path" in att
            and "preview_url" not in att
        ):
            try:
                att["preview_url"] = await minio_client.get_file_url(
                    bucket, att["storage_path"], expires
                )
            except Exception:
                pass


__all__ = ["enrich_attachments_with_presigned_urls"]