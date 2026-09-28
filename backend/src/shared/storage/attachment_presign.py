"""附件预签名 URL 注入：为消息附件中的图片生成 MinIO presigned preview_url（agent/qa 消息列表端点共用的展示层策略）。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from novamind.shared.storage.minio_client import IMAGE_FILE_TYPES

if TYPE_CHECKING:
    from novamind.shared.storage.minio_client import MinioClient


async def enrich_attachments_with_presigned_urls(
    extra: dict | None,
    minio_client: MinioClient,
    bucket: str | None = None,
    expires: int = 3600,
) -> None:
    """为 extra 中的图片附件就地注入 preview_url（MinIO presigned URL）。

    Args:
        extra: 消息 extra dict（含 attachments 键）；None 或缺 attachments 时原样返回。
        minio_client: MinIO 客户端实例。
        bucket: 存储桶名；None 用客户端默认桶。
        expires: 预签名有效期秒数。

    Returns:
        无返回值；预签名失败时该附件静默跳过（不抛）。
    """
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