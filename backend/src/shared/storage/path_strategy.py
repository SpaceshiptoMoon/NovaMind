"""
MinIO 对象路径策略端口

把「对象存储路径方案」从 `MinioClient` 中解耦：引擎（`shared/storage/minio_client.py`，
批次 6 迁 `novamind-knowledge-engine`）经 `PathStrategy` 协议获取对象名与列表前缀，
不再硬编码宿主 NovaMind 的 ``spaces/{id}/kbs/{id}/documents/{id}/...`` 路径方案。
宿主在 `features/knowledge_space/adapters/novamind_path_strategy.py` 实现
`NovamindPathStrategy` 并经 `ClientFactory` 注入。

设计约束：
  - `DefaultPathStrategy` 逐字复刻 `minio_client.py` 原路径方案，保证不注入策略时
    行为与旧版逐字一致（对象路径不变，旧索引/对象仍兼容）。
  - 依赖方向：宿主 -> 引擎 -> 本协议；引擎 ✗-> 宿主 features/setting。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PathStrategy(Protocol):
    """对象路径策略端口：引擎经此获取对象名与列表前缀，不硬编码宿主路径方案。"""

    def document_object_name(
        self, space_id: int, kb_id: int, document_id: int, storage_name: str
    ) -> str:
        """单文档对象名（含存储文件名）。"""
        ...

    def document_prefix_for_kb(self, space_id: int, kb_id: int) -> str:
        """知识库下所有对象的列表前缀（用于按 KB 批量删除/列举）。"""
        ...

    def document_prefix_for_space(self, space_id: int) -> str:
        """空间下所有对象的列表前缀（用于按空间批量删除/列举）。"""
        ...

    def avatar_object_name(self, user_id: int, extension: str) -> str:
        """用户头像对象名。"""
        ...

    def avatar_prefix_for_user(self, user_id: int) -> str:
        """用户头像列表前缀（用于删除旧头像）。"""
        ...

    def temp_object_name(self, session_id: str, filename: str) -> str:
        """临时文件对象名。"""
        ...

    def temp_prefix_for_session(self, session_id: str) -> str:
        """会话临时文件列表前缀（用于清理）。"""
        ...


class DefaultPathStrategy:
    """默认路径策略：逐字复刻 NovaMind 现行路径方案。

    不注入策略时 ``MinioClient`` 使用本实现，对象路径与端口化前逐字一致。
    宿主可注入 ``NovamindPathStrategy``（同值，归 knowledge_space adapter 所有）。
    """

    def document_object_name(
        self, space_id: int, kb_id: int, document_id: int, storage_name: str
    ) -> str:
        return f"spaces/{space_id}/kbs/{kb_id}/documents/{document_id}/{storage_name}"

    def document_prefix_for_kb(self, space_id: int, kb_id: int) -> str:
        return f"spaces/{space_id}/kbs/{kb_id}/"

    def document_prefix_for_space(self, space_id: int) -> str:
        return f"spaces/{space_id}/"

    def avatar_object_name(self, user_id: int, extension: str) -> str:
        return f"avatars/{user_id}/avatar.{extension}"

    def avatar_prefix_for_user(self, user_id: int) -> str:
        return f"avatars/{user_id}/"

    def temp_object_name(self, session_id: str, filename: str) -> str:
        return f"temp/{session_id}/{filename}"

    def temp_prefix_for_session(self, session_id: str) -> str:
        return f"temp/{session_id}/"


__all__ = ["PathStrategy", "DefaultPathStrategy"]