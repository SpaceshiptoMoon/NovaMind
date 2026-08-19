"""附件预签名 URL 注入，为消息附件中的图片生成 MinIO presigned preview_url。

跨 feature 共用的展示层策略（被 agent / qa 等多 feature 的消息列表端点使用），
只依赖 ``shared/storage/minio_client``，无 ORM / feature 依赖，故归 ``shared``
中立位置——调用方经 ``features → shared`` 单向依赖取用，避免 feature 间互相直连。

历史：曾住在 ``shared/storage/minio_client.py``，后以"宿主展示策略"为由迁至
``features/knowledge_space/adapters/``；但 knowledge_space 自身并不使用它，
实际使用方是 agent 与 qa，放在单个 feature 内导致跨 feature 直连，故回迁 shared。
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