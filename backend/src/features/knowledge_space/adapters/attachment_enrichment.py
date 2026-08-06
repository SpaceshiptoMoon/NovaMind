"""
附件预签名 URL 注入，为消息附件中的图片生成 MinIO presigned preview_url。

从 shared/storage/minio_client.py 迁出，属宿主展示层策略。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from novamind.shared.storage.minio_client import IMAGE_FILE_TYPES

if TYPE_CHECKING:
    from novamind.shared.storage.minio_client import MinioClient


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